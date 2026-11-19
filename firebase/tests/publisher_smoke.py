"""Real Python Admin SDK -> local Firestore emulator. No production credentials or FCM."""
from pathlib import Path
import os
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ai_engine'))
from google.cloud import firestore
from google.auth.credentials import AnonymousCredentials
from src.firebase import Publisher
from src.config import Config
import threading
import time

assert os.environ.get('FIRESTORE_EMULATOR_HOST'), 'Must run inside emulators:exec'
db=firestore.Client(project='demo-elderly-safety',credentials=AnonymousCredentials())
profile=db.document('profiles/python-test')
profile.set({'displayName':'EMULATOR TEST'})
publisher=Publisher('python-test',Config(),client=db)
result={'timestamp_s':1.0,'posture':'STANDING','person_status':'DETECTED','fsm':'NORMAL',
        'active_event_id':None,'events':[{'event_id':'test-event','kind':'POSSIBLE_FALL','timestamp':1.0,'details':{}}]}
publisher.submit(result)
deadline=time.monotonic()+10
alert=profile.collection('alerts').document('test-event')
while not alert.get().exists and time.monotonic()<deadline:time.sleep(.1)
assert alert.get().exists
status=profile.collection('status').document('current')
while not status.get().exists and time.monotonic()<deadline:time.sleep(.1)
assert status.get().exists
alert.update({'seenBy':'test-caregiver','seenAt':firestore.SERVER_TIMESTAMP})
publisher.write_event(result['events'][0])
assert alert.get().to_dict()['seenBy']=='test-caregiver', 'Retry must preserve acknowledgment'
early=profile.collection('alerts').document('early-event')
publisher.write_event({'event_id':'early-event','kind':'SUSPECTED_FALL','timestamp':2.0,'details':{}})
assert early.get().to_dict()['verification']=='VERIFYING'
early.update({'seenBy':'test-caregiver','seenAt':firestore.SERVER_TIMESTAMP})
publisher.write_event({'event_id':'early-event','kind':'POSSIBLE_FALL','timestamp':3.0,'details':{}})
assert early.get().to_dict()['kind']=='POSSIBLE_FALL'
assert early.get().to_dict()['seenBy']=='test-caregiver'
publisher.write_event({'event_id':'early-event','kind':'UNVERIFIED_CANDIDATE','timestamp':4.0,'details':{}})
assert early.get().to_dict()['verification']=='UNVERIFIED_CANDIDATE'
while len(list(profile.collection('events').stream()))<2 and time.monotonic()<deadline:time.sleep(.1)
assert len(list(profile.collection('events').stream()))==5, 'Status and unique event-kind documents only; duplicate retries must not append'
publisher.close()
assert profile.collection('status').document('current').get().to_dict()['engine_online'] is False
print('PASS: Python -> emulator status/event/alert, idempotent retries, preserved acknowledgment, offline shutdown; no FCM sent')
