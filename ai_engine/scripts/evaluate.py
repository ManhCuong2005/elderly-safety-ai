import argparse
from dataclasses import asdict, replace
import csv
import json
from pathlib import Path
import time
from src.config import Config
from src.camera import Source, input_layout
from src.pose import PoseTracker
from src.engine import Engine
from src.evaluation import report

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'ai_engine'/'datasets'


def extract_records(records, config, model, output):
    output.mkdir(exist_ok=True)
    for record in records:
        path = output/f"{record['video_id']}.landmarks.jsonl"
        if path.exists():
            performance=output/f"{record['video_id']}.performance.json"
            layout=input_layout(str(ROOT/record['path']))
            cached=json.loads(performance.read_text()) if performance.exists() else {}
            if layout=='ur-rgbd' and cached.get('input_layout')!='ur-rgbd':
                raise ValueError('Legacy cache contains composite frames. Use a fresh --cache-tag such as rgb_input_fixed.')
            print(f"Cache exists: {record['video_id']}", flush=True)
            continue
        source = Source(str(ROOT/record['path']), str(ROOT/record['sync_path']),layout=record.get('input_layout','auto'))
        tracker = PoseTracker(model, config)
        engine = Engine(config)
        start = time.perf_counter()
        count = 0
        temp = path.with_suffix('.partial')
        try:
            with temp.open('w') as f, (output/f"{record['video_id']}.features.csv").open('w', newline='') as features:
                writer = csv.DictWriter(features, fieldnames=['t','posture','fsm','lean','hip_y','torso','speed','pose_valid'])
                writer.writeheader()
                for t, frame in source:
                    pose, reason = tracker.process(frame, t)
                    h, w = frame.shape[:2]
                    f.write(json.dumps({'t':t,'landmarks':pose,'reason':reason,'width':w,'height':h})+'\n')
                    result = engine.process(t, pose, w, h, reason)
                    geo = result['features'] or {}
                    writer.writerow({'t':t,'posture':result['posture'],'fsm':result['fsm'],
                                     'lean':geo.get('lean'),'hip_y':geo.get('hip_y'),'torso':geo.get('torso'),
                                     'speed':result['motion']['speed'],'pose_valid':bool(geo)})
                    count += 1
            temp.rename(path)
            seconds = time.perf_counter()-start
            (output/f"{record['video_id']}.performance.json").write_text(json.dumps(
                {'frames':count,'processing_seconds':seconds,'throughput_fps':count/seconds,
                 'includes_decode_and_inference':True,'webcam_fps_measured':False,'input_layout':source.layout},indent=2))
            print(f"Extracted {record['video_id']}: {count} frames, {count/seconds:.2f} FPS", flush=True)
        finally:
            source.close()
            tracker.close()
            temp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description='Offline dataset evaluation. Never imports Firebase or sends FCM.')
    p.add_argument('--extract', action='store_true')
    p.add_argument('--calibrate', action='store_true')
    p.add_argument('--split', choices=['calibration','test','test_final','test_v1_1','test_v1_2','test_v1_3','test_v1_4'], default='test')
    p.add_argument('--extract-split', choices=['all','calibration','test','test_final','test_v1_1','test_v1_2','test_v1_3','test_v1_4'], default='all')
    p.add_argument('--config')
    p.add_argument('--model', default=str(ROOT/'ai_engine/models/pose_landmarker_lite.task'))
    p.add_argument('--cache-tag', default='',help='Separate versioned caches for algorithm/model changes')
    p.add_argument('--report-tag', default='',help='Preserve earlier reports when testing a new algorithm version')
    args = p.parse_args()
    records = json.loads((DATA/'metadata/manifest.json').read_text())
    config = Config.load(args.config)
    if args.cache_tag and not args.cache_tag.replace('_','').isalnum():
        p.error('Cache tag must contain letters, digits or underscores')
    if args.report_tag and not args.report_tag.lstrip('-').replace('_','').isalnum():
        p.error('Report tag must contain a leading hyphen and letters/digits/underscores only')
    directory=DATA/'processed'/args.cache_tag if args.cache_tag else DATA/'processed'
    if args.extract:
        extract_records([r for r in records if args.extract_split=='all' or r['split']==args.extract_split], config, args.model,directory)
    if args.calibrate:
        # Calibration split only. Final held-out videos are never read in this branch.
        trials = []
        for visibility in [.5, .6]:
            for lean in [55., 62.]:
                c = replace(config, visibility=visibility, lying_lean=lean)
                result = report(records, directory, c, 'calibration')
                trials.append((result['metrics']['f1'], -result['metrics']['fp'], c, result))
        best = max(trials, key=lambda item: item[:2])
        path = ROOT/f'ai_engine/configs/calibrated{args.report_tag}.json'
        path.write_text(json.dumps(asdict(best[2]), indent=2))
        (ROOT/f'docs/calibration-report{args.report_tag}.json').write_text(json.dumps(best[3],indent=2))
        print(f'Calibration only; frozen config: {path}')
    else:
        result = report(records, directory, config, args.split)
        path = ROOT/f'docs/evaluation-{args.split}{args.report_tag}.json'
        path.write_text(json.dumps(result, indent=2))
        print(json.dumps(result['metrics'], indent=2))
        print(f'Report: {path}')


if __name__ == '__main__':
    main()
