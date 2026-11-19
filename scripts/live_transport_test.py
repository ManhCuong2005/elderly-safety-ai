"""Isolated production watch + FCM validate-only. No real notification is delivered."""
from pathlib import Path
import json
import sys
import threading
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.firebase import connect


def main():
    if '--run' not in sys.argv:raise SystemExit('Use --run for an isolated production transport test')
    db,app=connect()
    from firebase_admin import firestore,messaging
    run_id=uuid.uuid4().hex
    profile=db.document('profiles/system-transport-'+run_id)
    status=profile.collection('status').document('current')
    signal=threading.Event()
    watch=None;created=False
    result={'project':'elderly-safety-ai','origin':'isolated transport test','firestore_watch':'PENDING',
            'fcm_validate_only':'PENDING','fcm_device_receipt':'PENDING_DEVICE_TEST','cleanup':'PENDING'}
    try:
        profile.create({'displayName':'TEMPORARY TRANSPORT TEST','origin':'system_smoke'})
        created=True
        status.set({'probe':0,'heartbeat':firestore.SERVER_TIMESTAMP})
        def callback(snapshots,changes,read_time):
            if any(doc.to_dict().get('probe')==1 for doc in snapshots):signal.set()
        watch=status.on_snapshot(callback)
        status.set({'probe':1,'heartbeat':firestore.SERVER_TIMESTAMP})
        if not signal.wait(timeout=20):raise TimeoutError('Firestore watch did not observe the change')
        result['firestore_watch']='PASS'
        print('PASS production Firestore snapshot listener observed a server update',flush=True)
        messaging.send(messaging.Message(topic='system-smoke-'+run_id,
            data={'kind':'SIMULATED_TRANSPORT_TEST'},notification=messaging.Notification(title='VALIDATE ONLY',body='No delivery')),
            dry_run=True,app=app)
        result['fcm_validate_only']='PASS'
        print('PASS FCM Admin SDK validate-only request. No device delivery was attempted.',flush=True)
    except Exception as error:
        result['error_type']=type(error).__name__
        print('Transport test failed: '+type(error).__name__)
    finally:
        if watch:watch.unsubscribe()
        if created:
            try:
                status.delete();profile.delete();result['cleanup']='PASS'
            except Exception as error:
                result['cleanup']='FAIL';result['cleanup_error_type']=type(error).__name__
        (Path(__file__).resolve().parents[1]/'docs/live-transport-test.json').write_text(json.dumps(result,indent=2))
    return 0 if all(result[k]=='PASS' for k in ['firestore_watch','fcm_validate_only','cleanup']) else 1


if __name__=='__main__':sys.exit(main())
