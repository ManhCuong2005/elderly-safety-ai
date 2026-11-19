"""Explicitly labeled transport test; never claim it is algorithm detection."""
import argparse
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.firebase import connect, validate_id, Publisher


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',required=True)
    p.add_argument('--confirm',required=True)
    p.add_argument('--notify',action='store_true',help='Send one explicitly labeled test notification to linked devices')
    args=p.parse_args()
    if validate_id(args.profile)!=args.confirm:
        p.error('--confirm must exactly match --profile')
    db,app=connect()
    from firebase_admin import firestore
    profile=db.collection('profiles').document(args.profile)
    if not profile.get().exists:raise ValueError('Provision the test profile first')
    event_id='test_'+uuid.uuid4().hex
    payload={'event_id':event_id,'kind':'SIMULATED_TRANSPORT_TEST','origin':'simulation',
             'severity':'test','createdAt':firestore.SERVER_TIMESTAMP,'seenAt':None,'seenBy':None,'safeAt':None,'safeBy':None,
             'details':{'note':'Transport test only. Not an algorithm-detected fall.'}}
    alert=profile.collection('alerts').document(event_id)
    alert.create(payload)
    if args.notify:
        publisher=object.__new__(Publisher)
        publisher.db,publisher.app,publisher.profile,publisher.profile_id=db,app,profile,args.profile
        publisher.notify(alert,payload)
    result=alert.get().to_dict()
    print(f"Created and read SIMULATED_TRANSPORT_TEST {event_id}. FCM receipt and acknowledgment still require phone verification.")
    if result.get('origin')!='simulation':raise RuntimeError('Read-back mismatch')


if __name__=='__main__':main()
