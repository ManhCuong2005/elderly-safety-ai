"""Trusted laptop only. Bounded in-memory queue; no camera-thread network IO."""
from collections import deque
from datetime import datetime, timezone
import hashlib
import os
import re
import threading
import time
import logging

PROJECT = 'elderly-safety-ai'
ALERT_KINDS = {'SUSPECTED_FALL', 'POSSIBLE_FALL', 'LYING_TOO_LONG', 'ABNORMAL_INACTIVITY'}
log = logging.getLogger(__name__)


def validate_id(value):
    if not value or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Profile ID must use 1-100 letters, digits, underscores or hyphens')
    return value


def connect():
    import firebase_admin
    from firebase_admin import credentials, firestore
    path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not path:
        raise RuntimeError('Set GOOGLE_APPLICATION_CREDENTIALS to a private service-account JSON path; never paste keys into chat')
    credential = credentials.Certificate(path)
    if credential.project_id != PROJECT:
        raise ValueError('Credential project must be elderly-safety-ai')
    try:
        app = firebase_admin.get_app('elderly-safety-engine')
    except ValueError:
        app = firebase_admin.initialize_app(credential, {'projectId': PROJECT, 'httpTimeout': 10}, name='elderly-safety-engine')
    return firestore.client(app), app


class Publisher:
    def __init__(self, profile, config, client=None, app=None):
        self.profile_id = validate_id(profile)
        self.c = config
        self.db, self.app = (client, app) if client else connect()
        self.profile = self.db.collection('profiles').document(profile)
        if not self.profile.get(timeout=10).exists:
            raise ValueError('Profile not provisioned. Use scripts/admin.py before monitoring.')
        self.condition = threading.Condition()
        self.events = deque()
        self.latest = None
        self.sample_received = float('-inf')
        self.stopping = False
        self.health = 'STARTING'
        self.safe = set()
        self.safe_delivered = set()
        self.last_signature = None
        self.last_push = float('-inf')
        self.worker = threading.Thread(target=self.run, name='firebase-publisher', daemon=True)
        self.worker.start()

    def submit(self, result):
        with self.condition:
            self.latest = result
            self.sample_received = time.monotonic()
            for event in result['events']:
                if event['kind'] == 'POSTURE_CHANGE':
                    continue  # coalesced history entry when current status is actually published
                if len(self.events) >= 128:
                    self.health = 'QUEUE_FULL'
                    log.error('Firebase event queue full; new event not queued. Check optional local JSONL telemetry.')
                    continue
                self.events.append(event)
            self.condition.notify()

    def take_safe_confirmations(self):
        with self.condition:
            result = list(self.safe)
            self.safe.clear()
            return result

    def pause(self):
        self.submit({'timestamp_s':0,'posture':'UNKNOWN','person_status':'PAUSED','fsm':'NORMAL',
                     'active_event_id':None,'events':[],'camera_online':False})

    def run(self):
        backoff = 1
        while True:
            with self.condition:
                self.condition.wait(timeout=1)
                stopping = self.stopping
                snapshot = dict(self.latest) if self.latest else None
                if snapshot:
                    snapshot['camera_online'] = snapshot.get('camera_online',True) and time.monotonic()-self.sample_received < 3
                event = self.events[0] if self.events else None
            try:
                if event:
                    self.write_event(event)
                    with self.condition:
                        self.events.popleft()
                if snapshot:
                    signature = tuple(snapshot.get(k) for k in ('posture','person_status','fsm','active_event_id','camera_online'))
                    now = time.monotonic()
                    due = now-self.last_push >= self.c.heartbeat_s
                    changed = signature != self.last_signature and now-self.last_push >= max(15,self.c.status_min_interval_s)
                    if due or changed or stopping:
                        self.write_status(snapshot, signature != self.last_signature, stopping)
                        self.last_signature, self.last_push = signature, now
                self.health = 'ONLINE'
                backoff = 1
            except Exception as error:
                # Do not log exception payloads: provider messages may contain tokens.
                self.health = 'RETRYING'
                log.warning('Firebase operation failed (%s); retrying', type(error).__name__)
                with self.condition:
                    if not self.stopping:
                        self.condition.wait(timeout=backoff)
                backoff = min(backoff*2, 30)
            if stopping:
                break

    def write_status(self, snapshot, changed, stopping=False):
        from firebase_admin import firestore
        payload = {key:snapshot.get(key) for key in ['posture','person_status','fsm','active_event_id','timestamp_s']}
        payload.update({'updatedAt':firestore.SERVER_TIMESTAMP,'heartbeat':firestore.SERVER_TIMESTAMP,
                        'engine_online':not stopping and snapshot.get('camera_online',True),'camera_online':not stopping and snapshot.get('camera_online',True),
                        'mode':'connected','schemaVersion':1})
        self.profile.collection('status').document('current').set(payload)
        if changed and not stopping:
            # Stable hash makes retries of this exact transition idempotent.
            event_id = hashlib.sha256(f"{snapshot['timestamp_s']}:{snapshot['posture']}:{snapshot['fsm']}".encode()).hexdigest()
            self.profile.collection('events').document(event_id).set({**payload,'kind':'STATUS_CHANGE','createdAt':firestore.SERVER_TIMESTAMP})
        active = snapshot.get('active_event_id')
        if active and active not in self.safe_delivered:
            doc = self.profile.collection('alerts').document(active).get(timeout=10)
            if doc.exists and doc.to_dict().get('safeAt'):
                with self.condition:
                    self.safe.add(active)
                    self.safe_delivered.add(active)
                    if len(self.safe_delivered)>1000:
                        self.safe_delivered={active}

    def write_event(self, event):
        from firebase_admin import firestore
        from google.api_core.exceptions import AlreadyExists
        key = f"{event['event_id']}_{event['kind']}"
        payload = {**event,'createdAt':firestore.SERVER_TIMESTAMP,'origin':'algorithm','schemaVersion':1}
        ref = self.profile.collection('events').document(key)
        try:
            ref.create(payload)
        except AlreadyExists:
            pass
        if event['kind'] in ALERT_KINDS:
            alert = self.profile.collection('alerts').document(event['event_id'])
            try:
                alert.create({**payload,'severity':'high' if event['kind']=='POSSIBLE_FALL' else 'warning',
                              'verification':'VERIFYING' if event['kind']=='SUSPECTED_FALL' else 'ALERT',
                              'seenBy':None,'seenAt':None,'safeBy':None,'safeAt':None})
            except AlreadyExists:
                if event['kind']=='POSSIBLE_FALL':
                    alert.set({'kind':'POSSIBLE_FALL','severity':'high','verification':'ALERT',
                               'verifiedAt':firestore.SERVER_TIMESTAMP,'details':event.get('details',{})},merge=True)
                # Caregiver acknowledgment is never overwritten during retries/escalation.
            self.notify(alert, event)
        elif event['kind'] in ('RECOVERED','UNVERIFIED_CANDIDATE'):
            alert=self.profile.collection('alerts').document(event['event_id'])
            if alert.get(timeout=10).exists:
                alert.set({'verification':event['kind'],'verificationUpdatedAt':firestore.SERVER_TIMESTAMP},merge=True)

    def notify(self, alert, event):
        from firebase_admin import messaging, firestore
        from google.api_core.exceptions import AlreadyExists
        for caregiver in self.profile.collection('caregivers').stream(timeout=10):
            for device in self.db.collection('users').document(caregiver.id).collection('devices').stream(timeout=10):
                data = device.to_dict()
                if not data.get('enabled') or not data.get('token'):
                    continue
                delivery_key = hashlib.sha256(f'{caregiver.id}:{device.id}'.encode()).hexdigest()
                claim = alert.collection('deliveries').document(delivery_key)
                try:
                    claim.create({'state':'claimed','createdAt':firestore.SERVER_TIMESTAMP})
                except AlreadyExists:
                    continue
                try:
                    messaging.send(messaging.Message(
                        token=data['token'], notification=messaging.Notification(
                            title='[KIỂM THỬ] An Tâm' if event['kind']=='SIMULATED_TRANSPORT_TEST' else 'Cảnh báo an toàn',
                            body='Thử đường truyền, không phải phát hiện ngã.' if event['kind']=='SIMULATED_TRANSPORT_TEST' else 'Có sự kiện cần kiểm tra. Mở ứng dụng để xem chi tiết.'),
                        data={'profileId':self.profile_id,'alertId':event['event_id'],'kind':event['kind']},
                        android=messaging.AndroidConfig(priority='high',ttl=300,
                            notification=messaging.AndroidNotification(channel_id='safety_alerts',tag=event['event_id']))), app=self.app)
                    claim.set({'state':'accepted_by_fcm','updatedAt':firestore.SERVER_TIMESTAMP},merge=True)
                except messaging.UnregisteredError:
                    device.reference.delete()
                    claim.set({'state':'invalid_token'},merge=True)
                except Exception:
                    # At-most-once claim: ambiguous transport failures must not be retried blindly.
                    claim.set({'state':'delivery_unknown','updatedAt':firestore.SERVER_TIMESTAMP},merge=True)

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        self.worker.join(timeout=15)
        if self.worker.is_alive():
            log.warning('Publisher shutdown timed out; mobile heartbeat expiry will mark offline')
        if self.events:
            log.warning('Publisher stopped with %s unsent in-memory events; no durable offline queue',len(self.events))
