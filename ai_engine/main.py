import argparse
import json
from pathlib import Path
import time
import cv2
from src.config import Config
from src.camera import Source
from src.pose import PoseTracker
from src.engine import Engine

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description='Elderly Safety V1: q=stop, space=pause, r=reacquire person')
    p.add_argument('--source', default='0', help='Camera index, video filename, or RGB sequence directory')
    p.add_argument('--sync', help='Required UR timestamp CSV for image sequences')
    p.add_argument('--input-layout',choices=['auto','rgb','ur-rgbd'],default='auto')
    p.add_argument('--mode', choices=['local','connected'], default='local')
    p.add_argument('--profile', help='Provisioned Firestore profile ID; required in connected mode')
    p.add_argument('--config', default=str(HERE/'configs/v2_ml.json'))
    p.add_argument('--model', default=str(HERE/'models/pose_landmarker_full.task'))
    p.add_argument('--demo', action='store_true', help='Short lying/inactivity timers; LOCAL ONLY')
    p.add_argument('--headless', action='store_true')
    p.add_argument('--fps', type=int, default=15)
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--max-frames', type=int)
    p.add_argument('--output', help='Optional local JSONL telemetry')
    args = p.parse_args()
    if args.mode == 'connected' and (not args.source.isdigit() or args.demo or not args.profile):
        p.error('Connected mode requires live camera, --profile, and normal thresholds. Video/demo tests stay local.')
    config = Config.load(args.config)
    if args.demo:
        config = config.demo()
    publisher = tracker = source = output = None
    engine = Engine(config)
    count = 0
    started = time.perf_counter()
    try:
        if args.mode == 'connected':
            from src.firebase import Publisher
            publisher = Publisher(args.profile, config)
        source = Source(int(args.source) if args.source.isdigit() else args.source, args.sync,
                        args.fps, args.width, args.height,layout=args.input_layout)
        tracker = PoseTracker(args.model, config)
        output = open(args.output, 'w', encoding='utf-8') if args.output else None
        for t, frame in source:
            before = time.perf_counter()
            pose, reason = tracker.process(frame, t)
            h, w = frame.shape[:2]
            result = engine.process(t, pose, w, h, reason, world_landmarks=tracker.last_world_landmarks, people_count=tracker.last_people_count)
            if publisher:
                safe = publisher.take_safe_confirmations()
                for event_id in safe:
                    engine.fsm.confirm_safe(t, event_id)
                publisher.submit(result)
            if output:
                output.write(json.dumps(result, allow_nan=False)+'\n')
            count += 1
            elapsed = time.perf_counter()-before
            if not args.headless:
                tracker.draw(frame, pose)
                risk_pct = int(round(result.get('fall_score', 0.0) * 100))
                lines = [f"{args.mode.upper()} [{result.get('algorithm_version','1.4')}] | {result['posture']} | {result['person_status']}",
                         f"FSM {result['fsm']} | Fall Risk {risk_pct}% | motion {result['motion']['speed']:.2f} torso/s",
                         f"AI {1/max(elapsed,1e-6):.1f} FPS | Firebase {publisher.health if publisher else 'DISABLED'}",
                         'Q stop | SPACE pause | R select person again']
                if args.demo:
                    lines.append('DEMO - local only; shortened timers')
                for i, text in enumerate(lines):
                    cv2.putText(frame, text, (14,28+i*26), cv2.FONT_HERSHEY_SIMPLEX, .48, (20,20,20), 3)
                    cv2.putText(frame, text, (14,28+i*26), cv2.FONT_HERSHEY_SIMPLEX, .48, (255,255,255), 1)
                cv2.imshow('Elderly Safety V1', frame)
                key = cv2.waitKey(1)&0xff
                if key == ord('q'):
                    break
                if key == ord('r'):
                    tracker.reset_identity()
                    engine = Engine(config)
                if key == ord(' '):
                    if publisher:
                        publisher.pause()
                    while True:
                        paused_key=cv2.waitKey(100)&0xff
                        if paused_key in (32,ord('q')):
                            break
                    if paused_key==ord('q'):
                        break
                    # Continuity lost while paused: clear temporal evidence.
                    engine = Engine(config)
                    tracker.reset_identity()
            if args.max_frames and count >= args.max_frames:
                break
    finally:
        if source:
            source.close()
        if tracker:
            tracker.close()
        if output:
            output.close()
        if publisher:
            publisher.close()
        cv2.destroyAllWindows()
        seconds = time.perf_counter()-started
        print(json.dumps({'frames':count,'elapsed_s':seconds,'overall_fps':count/max(seconds,1e-6)}))


if __name__ == '__main__':
    main()
