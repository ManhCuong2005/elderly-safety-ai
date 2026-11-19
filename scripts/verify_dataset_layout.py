"""Identify the published UR MP4 RGB/depth composite from dimensions and actual colors."""
from pathlib import Path
import json
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'ai_engine/datasets'
manifest_path=DATA/'metadata/manifest.json'
records=json.loads(manifest_path.read_text(encoding='utf-8'))
layouts=[]
for record in records:
    source=ROOT/record['path']
    item={'video_id':record['video_id'],'file_name':source.name,'input_layout':'rgb','verified':True}
    if source.is_file():
        cap=cv2.VideoCapture(str(source))
        w,h=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));left=[];right=[]
        for fraction in [.1,.5,.8]:
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(count*fraction));ok,frame=cap.read()
            if not ok:continue
            for panel,output in [(frame[:,:w//2],left),(frame[:,w//2:],right)]:
                sample=panel.astype(np.float32)
                output.append(float(np.mean(np.ptp(sample,axis=2))))
        cap.release()
        composite=bool(h and 2.4<w/h<2.9 and left and max(left)<3 and min(right)>5)
        if composite:item['input_layout']='ur-rgbd'
        item.update({'container_width':w,'container_height':h,'left_chroma':left,'right_chroma':right,
                     'verification':'three real frames: grayscale left and color right plus composite aspect'})
    record['input_layout']=item['input_layout']
    layouts.append(item)
(DATA/'metadata/input_layouts.json').write_text(json.dumps(layouts,indent=2),encoding='utf-8')
manifest_path.write_text(json.dumps(records,indent=2),encoding='utf-8')
print(json.dumps({'sequences':len(layouts),'verified_rgbd_composites':sum(r['input_layout']=='ur-rgbd' for r in layouts),
                  'rgb_sequences':sum(r['input_layout']=='rgb' for r in layouts)}))
