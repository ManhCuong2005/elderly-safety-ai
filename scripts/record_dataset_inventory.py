"""Record source timing/container metadata and compare against actual decoded counts."""
from pathlib import Path
import csv
import json
import statistics
import cv2
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'ai_engine/datasets'
records=json.loads((DATA/'metadata/manifest.json').read_text())
perf={}
for path in (DATA/'processed').rglob('*.performance.json'):
    perf[path.name.split('.performance.json')[0]]=json.loads(path.read_text())
inventory=[]
for record in records:
    path=ROOT/record['path']
    if path.is_dir():
        frames=len(list(path.rglob('*.png')))
        rows=list(csv.reader((ROOT/record['sync_path']).open()))
        times=[float(row[1])/1000 for row in rows if row]
        intervals=[b-a for a,b in zip(times,times[1:]) if b>a]
        fps=1/statistics.median(intervals) if intervals else None
        timing='authentic synchronization CSV; median interval FPS only'
    else:
        cap=cv2.VideoCapture(str(path))
        if not cap.isOpened():raise RuntimeError('Cannot inspect '+record['video_id'])
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS)
        cap.release();timing='MP4 container nominal FPS; processing uses presentation timestamps'
    decoded=perf.get(record['video_id'],{}).get('frames')
    inventory.append({'video_id':record['video_id'],'label':record['label'],'split':record['split'],
                      'source_frame_count':frames,'source_nominal_fps':fps,'timing_note':timing,
                      'actual_decoded_frames':decoded,'decode_count_matches':decoded==frames})
(DATA/'metadata/inventory.json').write_text(json.dumps(inventory,indent=2))
summary={'sequences':len(inventory),'source_frames':sum(r['source_frame_count'] for r in inventory),
         'all_decoded_counts_match':all(r['decode_count_matches'] for r in inventory)}
print(json.dumps(summary))
if not summary['all_decoded_counts_match']:raise SystemExit(1)
