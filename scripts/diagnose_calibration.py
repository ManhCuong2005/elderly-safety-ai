"""Inspect detector ambiguity on calibration clips only."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.pose import PoseTracker
from src.camera import Source
from src.config import Config
import mediapipe as mp
import cv2
import json

root=Path(__file__).resolve().parents[1]
records=json.loads((root/'ai_engine/datasets/metadata/manifest.json').read_text())
for r in records:
    if r['split']!='calibration' or r['label']!='FALL':continue
    src=Source(str(root/r['path']),str(root/r['sync_path']))
    tracker=PoseTracker(root/'ai_engine/models/pose_landmarker_lite.task',Config())
    for i,(t,frame) in enumerate(src):
        result=tracker.detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),round(t*1000))
        if len(result.pose_landmarks)>1:
            print(r['video_id'],round(t,2),[{'hip':[round((p[23].x+p[24].x)/2,2),round((p[23].y+p[24].y)/2,2)],'vis':[round(p[j].visibility,2) for j in [11,12,23,24,25,26,27,28]],'presence':round(sum(p[j].presence for j in [11,12,23,24])/4,2)} for p in result.pose_landmarks],flush=True)
            break
    tracker.close();src.close()
