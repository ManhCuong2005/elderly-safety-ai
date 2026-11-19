"""Brief local camera smoke; records counts only and always releases the camera."""
from pathlib import Path
import json
import sys
import time
import statistics
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.camera import Source
from src.pose import PoseTracker
from src.config import Config
from src.engine import Engine


def main():
    root=Path(__file__).resolve().parents[1]
    result={'source_index':0,'opened':False,'frames':0,'reliable_pose_frames':0,
            'camera_release':'PENDING','publication':'DISABLED_LOCAL_TEST','frames_saved':False,
            'human_posture_test':'PENDING_USER_TEST'}
    source=tracker=None
    started=time.perf_counter()
    frame_ends=[];inference_ms=[]
    try:
        config=Config.load(root/'ai_engine/configs/calibrated-v1_4.json')
        source=Source(0,fps=15,width=640,height=480)
        result['opened']=True
        tracker=PoseTracker(root/'ai_engine/models/pose_landmarker_full.task',config)
        engine=Engine(config)
        for t,frame in source:
            inference_started=time.perf_counter()
            pose,reason=tracker.process(frame,t)
            h,w=frame.shape[:2]
            analysis=engine.process(t,pose,w,h,reason)
            inference_ms.append((time.perf_counter()-inference_started)*1000)
            frame_ends.append(time.perf_counter())
            result['resolution']=[w,h]
            result['frames']+=1
            result['reliable_pose_frames']+=int(analysis['features'] is not None)
            if result['frames']>=15:break
        result['status']='PASS_CAPTURE_AND_LOCAL_INFERENCE'
    except Exception as error:
        result['status']='PENDING_CAMERA_ACCESS'
        result['error_type']=type(error).__name__
    finally:
        if source:source.close()
        if tracker:tracker.close()
        result['camera_release']='RELEASE_CALLED' if source else 'NOT_OPENED'
        result['elapsed_s']=time.perf_counter()-started
        result['end_to_end_fps']=result['frames']/result['elapsed_s']
        result['includes_open_and_model_startup']=True
        if len(frame_ends)>6:
            result['warm_sample_fps']=(len(frame_ends)-6)/(frame_ends[-1]-frame_ends[5])
            result['warm_inference_median_ms']=statistics.median(inference_ms[5:])
        (root/'docs/camera-probe.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
