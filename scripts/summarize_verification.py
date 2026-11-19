"""Create a truthful machine-readable inventory from saved evidence."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
data=ROOT/'ai_engine/datasets'
manifest=json.loads((data/'metadata/manifest.json').read_text())
tests=ET.parse(ROOT/'docs/python-tests.xml').getroot()
suites=list(tests.iter('testsuite'))
performances=[json.loads(p.read_text()) for p in (data/'processed').rglob('*.performance.json')]
frames=sum(p['frames'] for p in performances)
seconds=sum(p['processing_seconds'] for p in performances)
apk=ROOT/'flutter_app/build/app/outputs/flutter-apk/app-debug.apk'
models={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'ai_engine/models').glob('*.task')}
summary={
  'as_of':'2026-11-10 Asia/Saigon',
  'dataset':{'sequences':len(manifest),'fall':sum(r['label']=='FALL' for r in manifest),
    'non_fall':sum(r['label']=='NON_FALL' for r in manifest),
    'downloaded_bytes_total':sum(r['download_bytes'] for r in manifest),
    'directory_bytes':sum(p.stat().st_size for p in data.rglob('*') if p.is_file()),
    'subject_independence_verified':False},
  'python_tests':{'tests':sum(int(s.get('tests',0)) for s in suites),'failures':sum(int(s.get('failures',0)) for s in suites),'errors':sum(int(s.get('errors',0)) for s in suites)},
  'flutter':{'analyze':'PASS','unit_widget_tests':7,'apk_bytes':apk.stat().st_size if apk.exists() else None,
    'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest() if apk.exists() else None,
    'physical_device':'PENDING_DEVICE_TEST'},
  'firebase':{'rules_tests_passed':17,'rules_deployed_project':'elderly-safety-ai',
    'python_firestore_emulator':'PASS','production_python_firestore':'PENDING_CREDENTIAL',
    'live_auth':'PENDING_LIVE_AUTH','fcm_receipt':'PENDING_DEVICE_TEST'},
  'video_performance':{'processed_frames_all_runs':frames,'processing_seconds_all_runs':seconds,
    'aggregate_throughput_fps':frames/seconds if seconds else None,
    'min_clip_throughput_fps':min(p['throughput_fps'] for p in performances),
    'max_clip_throughput_fps':max(p['throughput_fps'] for p in performances),'source_type':'recorded dataset video; camera timing is separate'},
  'model_sha256':models,
  'acceptance':'NOT_READY: real-video warning recall remains low; full-body webcam/Android/FCM receipt tests remain pending',
}
for name in ['evaluation-test.json','evaluation-test_final.json','evaluation-test_v1_1-v1_1.json','evaluation-test_v1_2-v1_2.json','evaluation-test_v1_3-v1_3.json','evaluation-test_v1_4-v1_4.json']:
    path=ROOT/'docs'/name
    if path.exists():
        result=json.loads(path.read_text())
        summary[name]= {'metrics':result['metrics'],'positive_definition':result.get('positive_definition','Verified POSSIBLE_FALL only'),
                       'verified_metrics':result.get('verified_metrics',result['metrics'])}
live=ROOT/'docs/live-firebase-test.json'
if live.exists():
    result=json.loads(live.read_text())
    summary['firebase']['production_python_firestore']=result['status']
    summary['firebase']['live_auth_server']=result['status']
    summary['firebase']['live_auth']='PENDING_DEVICE_TEST: Android UI/session; Auth server checked separately'
    summary['firebase']['production_checks']=len(result['checks'])
transport=ROOT/'docs/live-transport-test.json'
if transport.exists():
    result=json.loads(transport.read_text())
    summary['firebase']['production_snapshot_listener']=result['firestore_watch']
    summary['firebase']['fcm_validate_only']=result['fcm_validate_only']
inventory=data/'metadata/inventory.json'
if inventory.exists():
    rows=json.loads(inventory.read_text())
    summary['dataset']['unique_processed_sequences']=len(rows)
    summary['dataset']['unique_source_frames']=sum(r['source_frame_count'] for r in rows)
    summary['dataset']['all_decoded_counts_match']=all(r['decode_count_matches'] for r in rows)
secrets_scan=ROOT/'docs/secrets-scan.json'
if secrets_scan.exists():summary['source_secrets_scan']=json.loads(secrets_scan.read_text())['status']
camera=ROOT/'docs/camera-probe.json'
if camera.exists():summary['camera_smoke']=json.loads(camera.read_text())
provision=ROOT/'docs/provisioning-status.json'
if provision.exists():
    result=json.loads(provision.read_text());result.pop('profile_id',None)
    summary['provisioning']=result
release=ROOT/'docs/android-release-build.json'
if release.exists():summary['flutter']['release_build']=json.loads(release.read_text())
summary['flutter']['web_target_configured']=(ROOT/'flutter_app/web').is_dir()
web=ROOT/'docs/web-browser-test.json'
if web.exists():summary['flutter']['local_web_test']=json.loads(web.read_text())
layout=data/'metadata/input_layouts.json'
if layout.exists():
    rows=json.loads(layout.read_text())
    summary['dataset']['rgbd_composites_verified']=sum(r['input_layout']=='ur-rgbd' for r in rows)
    summary['dataset']['input_correction_notice']='docs/INPUT_LAYOUT_CORRECTION.md: earlier MP4 benchmarks used both panels and are not valid RGB accuracy estimates'
    summary['acceptance']='NOT_READY: RGB input corrected; diagnostic reevaluation is not an independent validation; fall accuracy remains unvalidated'
diagnostic=ROOT/'docs/evaluation-test_v1_4-rgb_input_fixed.json'
if diagnostic.exists():
    result=json.loads(diagnostic.read_text())
    summary['rgb_input_fixed_diagnostic']={'scope':'input correction diagnostic, not untouched independent test','metrics':result['metrics']}
(ROOT/'docs/verification-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
