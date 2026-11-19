"""Production smoke using isolated temporary users/profile. Never logs credentials/tokens.

Explicit --run is required. Cleans only resources created by this invocation.
No real users are linked and no FCM messages or password-reset emails are sent.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys
import uuid
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.firebase import connect, Publisher
from src.config import Config

ROOT=Path(__file__).resolve().parents[1]


def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if not args.run:parser.error('Use --run to authorize temporary production smoke resources')
    db,app=connect()
    from firebase_admin import auth,firestore
    public=json.loads((ROOT/'flutter_app/android/app/google-services.json').read_text())
    api_key=public['client'][0]['api_key'][0]['current_key']
    run_id=uuid.uuid4().hex[:16]
    profile_id='system-smoke-'+run_id
    profile=db.collection('profiles').document(profile_id)
    users=[];profile_created=False;results=[];cleanup=[]
    report={'run_id':run_id,'project':'elderly-safety-ai','origin':'isolated production smoke',
            'started_utc':datetime.now(timezone.utc).isoformat(),'checks':results,'cleanup':cleanup,
            'fcm_receipt':'PENDING_DEVICE_TEST','android_ui':'PENDING_DEVICE_TEST'}

    def check(name,passed):
        results.append({'name':name,'pass':bool(passed)})
        print(('PASS ' if passed else 'FAIL ')+name,flush=True)
        if not passed:raise AssertionError(name)

    def login(email,password):
        response=requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword',
            params={'key':api_key},json={'email':email,'password':password,'returnSecureToken':True},timeout=20)
        check('Firebase Auth Email/Password sign-in',response.status_code==200)
        return response.json()['idToken']

    prefix=f'https://firestore.googleapis.com/v1/projects/elderly-safety-ai/databases/(default)/documents'
    nameprefix='projects/elderly-safety-ai/databases/(default)/documents'
    try:
        # No existing user/profile enumeration; only unique test resources are touched.
        for kind in ['caregiver','unlinked']:
            email=f'codex-smoke-{kind}-{run_id}@example.com'
            password=secrets.token_urlsafe(30)
            user=auth.create_user(email=email,password=password,display_name='TEMPORARY SYSTEM TEST',app=app)
            users.append(user.uid)
            token=login(email,password)
            if kind=='caregiver':caregiver_uid,caregiver_token=user.uid,token
            else:unlinked_uid,unlinked_token=user.uid,token
        profile.create({'displayName':'TEMPORARY SYSTEM TEST','createdAt':firestore.SERVER_TIMESTAMP,'origin':'system_smoke'})
        profile_created=True
        profile.collection('caregivers').document(caregiver_uid).create({'role':'caregiver'})
        db.collection('users').document(caregiver_uid).collection('profiles').document(profile_id).set({'profileId':profile_id,'role':'caregiver'})
        publisher=object.__new__(Publisher)
        publisher.db,publisher.app,publisher.profile,publisher.profile_id=db,app,profile,profile_id
        publisher.write_event({'event_id':'test-alert','kind':'SUSPECTED_FALL','timestamp':0,'details':{'simulation':True}})
        # Mark test provenance; this is a transport smoke, not a detected fall.
        alert=profile.collection('alerts').document('test-alert')
        alert.set({'origin':'simulation'},merge=True)
        alert_path=f'profiles/{profile_id}/alerts/test-alert'
        check('Python Admin creates and reads isolated test alert',alert.get().to_dict()['origin']=='simulation')
        linked={'Authorization':'Bearer '+caregiver_token}
        unlinked={'Authorization':'Bearer '+unlinked_token}
        check('Linked client reads production profile',requests.get(prefix+'/profiles/'+profile_id,headers=linked,timeout=20).status_code==200)
        check('Unlinked account denied production profile',requests.get(prefix+'/profiles/'+profile_id,headers=unlinked,timeout=20).status_code==403)
        check('Anonymous account denied production profile',requests.get(prefix+'/profiles/'+profile_id,timeout=20).status_code in (401,403))
        status=profile.collection('status').document('current')
        status.set({'posture':'STANDING','engine_online':True,'heartbeat':firestore.SERVER_TIMESTAMP})
        check('Client reads Python-written status',requests.get(prefix+f'/profiles/{profile_id}/status/current',headers=linked,timeout=20).status_code==200)
        fake=prefix+f'/profiles/{profile_id}/events/forged'
        check('Client cannot forge a fall event',requests.patch(fake,headers=linked,json={'fields':{'kind':{'stringValue':'POSSIBLE_FALL'}}},timeout=20).status_code==403)
        for field in ['seen','safe']:
            write={'update':{'name':nameprefix+'/'+alert_path,'fields':{field+'By':{'stringValue':caregiver_uid}}},
                   'updateMask':{'fieldPaths':[field+'By']},
                   'updateTransforms':[{'fieldPath':field+'At','setToServerValue':'REQUEST_TIME'}]}
            response=requests.post(prefix+':commit',headers=linked,json={'writes':[write]},timeout=20)
            check('Client '+field+' acknowledgment with server timestamp',response.status_code==200)
            data=alert.get().to_dict()
            check('Admin reads back '+field+' acknowledgment',data.get(field+'By')==caregiver_uid and data.get(field+'At') is not None)
        publisher.write_event({'event_id':'test-alert','kind':'POSSIBLE_FALL','timestamp':1,'details':{'simulation':True}})
        check('Escalation preserves caregiver safety confirmation',alert.get().to_dict().get('safeBy')==caregiver_uid)
        # Disabled fake registration exercises rules without ever sending a push.
        device_path=f'users/{caregiver_uid}/devices/smoke'
        write={'update':{'name':nameprefix+'/'+device_path,'fields':{
                    'token':{'stringValue':'disabled-system-smoke-'+run_id},'platform':{'stringValue':'android'},'enabled':{'booleanValue':False}}},
               'updateTransforms':[{'fieldPath':'updatedAt','setToServerValue':'REQUEST_TIME'}]}
        check('Own device registration allowed',requests.post(prefix+':commit',headers=linked,json={'writes':[write]},timeout=20).status_code==200)
        check('Other account denied device token',requests.get(prefix+'/'+device_path,headers=unlinked,timeout=20).status_code==403)
        report['status']='PASS'
    except Exception as error:
        report['status']='FAIL'
        report['error_type']=type(error).__name__
        print('Live smoke failed: '+type(error).__name__,flush=True)
    finally:
        # Every path below belongs to this unique run. Never delete existing resources.
        if profile_created:
            try:
                for sub in ['events','status','caregivers','alerts']:
                    for doc in profile.collection(sub).stream():
                        if sub=='alerts':
                            for delivery in doc.reference.collection('deliveries').stream():delivery.reference.delete()
                        doc.reference.delete()
                profile.delete();cleanup.append({'resource':'temporary profile','deleted':True})
            except Exception as error:cleanup.append({'resource':'temporary profile','deleted':False,'error_type':type(error).__name__})
        for uid in users:
            try:
                ref=db.collection('users').document(uid)
                for sub in ['profiles','devices']:
                    for doc in ref.collection(sub).stream():doc.reference.delete()
                ref.delete()
                auth.delete_user(uid,app=app)
                cleanup.append({'resource':'temporary test account','deleted':True})
            except Exception as error:cleanup.append({'resource':'temporary test account','deleted':False,'error_type':type(error).__name__})
        if any(not item['deleted'] for item in cleanup):report['status']='FAIL_CLEANUP'
        (ROOT/'docs/live-firebase-test.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Report: docs/live-firebase-test.json. Tokens, passwords and key contents were not logged.')
    return 0 if report.get('status')=='PASS' else 1


if __name__=='__main__':sys.exit(run())
