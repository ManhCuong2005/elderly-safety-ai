"""Loopback-only HTTP bridge for the Flutter web test screen; no cloud side effects."""
import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import threading
import time
import cv2
import numpy as np
from src.config import Config
from src.engine import Engine
from src.pose import PoseTracker

HERE=Path(__file__).resolve().parent
MAX_BODY=1_500_000


class SessionExpired(ValueError):
    pass


class PoseSession:
    def __init__(self,config,model):
        self.config,self.model=config,Path(model)
        self.lock=threading.RLock()
        self.tracker=self.engine=self.session_id=None
        self.frames=0

    def start(self):
        with self.lock:
            self.close()
            self.tracker=PoseTracker(self.model,self.config)
            self.engine=Engine(self.config)
            self.session_id=secrets.token_urlsafe(24)
            self.frames=0
            return {'session_id':self.session_id,'mode':'local','notifications':False}

    def validate_session(self,key):
        if not self.session_id or not isinstance(key,str) or not secrets.compare_digest(key,self.session_id):
            raise SessionExpired('Phiên đã kết thúc hoặc được thay bởi tab khác. Bấm bắt đầu lại.')

    def analyze(self,payload):
        t=payload.get('timestamp_s')
        if isinstance(t,bool) or not isinstance(t,(float,int)) or not math.isfinite(t) or t<0:
            raise ValueError('Timestamp phải là số hữu hạn không âm.')
        encoded=payload.get('frame')
        if not isinstance(encoded,str) or not encoded.startswith('data:image/jpeg;base64,'):
            raise ValueError('Chỉ chấp nhận frame JPEG base64.')
        try:
            raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
        except (ValueError,binascii.Error):
            raise ValueError('Frame base64 không hợp lệ.') from None
        frame=cv2.imdecode(np.frombuffer(raw,dtype=np.uint8),cv2.IMREAD_COLOR)
        if frame is None or max(frame.shape[:2])>1280 or min(frame.shape[:2])<16:
            raise ValueError('Frame không đọc được hoặc kích thước ngoài giới hạn16–1280px.')
        with self.lock:
            self.validate_session(payload.get('session_id'))
            if self.engine.last_t is not None and (t<=self.engine.last_t or round(t*1000)<=self.tracker.last_ms):
                raise ValueError('Timestamp phải tăng; tạo phiên mới khi tua hoặc phát lại video.')
            before=time.perf_counter()
            pose,reason=self.tracker.process(frame,t)
            h,w=frame.shape[:2]
            result=self.engine.process(t,pose,w,h,reason,world_landmarks=self.tracker.last_world_landmarks, people_count=self.tracker.last_people_count)
            self.frames+=1
            result.update({'landmarks':pose,'width':w,'height':h,'processed_frames':self.frames,
                           'inference_ms':(time.perf_counter()-before)*1000,'mode':'local','notifications':False})
            return result

    def stop(self,key):
        with self.lock:
            self.validate_session(key)
            self.close()
            return {'stopped':True}

    def close(self):
        with self.lock:
            if self.tracker:self.tracker.close()
            self.tracker=self.engine=self.session_id=None


class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass  # Never log frame request bodies or session identifiers.

    def allowed(self,mutating=False):
        host=self.headers.get('Host','')
        if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            self.reply(403,{'error':'Host không được phép.'});return False
        origin=self.headers.get('Origin')
        if (origin and origin not in self.server.origins) or (mutating and not origin):
            self.reply(403,{'error':'Chỉ cho phép trang Flutter local đã cấu hình.'});return False
        return True

    def reply(self,status,data=None):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8') if data is not None else b''
        self.send_response(status)
        origin=self.headers.get('Origin')
        if origin in self.server.origins:
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.send_header('Access-Control-Allow-Private-Network','true')
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if body:self.wfile.write(body)

    def do_OPTIONS(self):
        if self.allowed(mutating=True):self.reply(204)

    def do_GET(self):
        if not self.allowed():return
        if self.path!='/api/health':self.reply(404,{'error':'Endpoint không tồn tại.'});return
        self.reply(200,{'status':'ready','mode':'local','notifications':False,
                        'model_present':self.server.pose.model.is_file(),
                        'ml_model_present':bool(self.server.pose.config.ml_model_path),
                        'algorithm_version':'2.0-ml' if self.server.pose.config.ml_model_path else '1.4',
                        'api_version':'2.0.0'})

    def do_POST(self):
        if not self.allowed(mutating=True):return
        try:
            length=int(self.headers.get('Content-Length','0'))
        except ValueError:
            self.reply(400,{'error':'Content-Length không hợp lệ.'});return
        if not 0<=length<=MAX_BODY:
            self.reply(413,{'error':'Frame quá lớn.'});return
        if self.headers.get_content_type()!='application/json':
            self.reply(400,{'error':'Yêu cầu application/json.'});return
        try:
            payload=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(payload,dict):raise ValueError('Body phải là JSON object.')
            if self.path=='/api/start':result=self.server.pose.start()
            elif self.path=='/api/analyze':result=self.server.pose.analyze(payload)
            elif self.path=='/api/stop':result=self.server.pose.stop(payload.get('session_id'))
            else:self.reply(404,{'error':'Endpoint không tồn tại.'});return
            self.reply(200,result)
        except SessionExpired as error:self.reply(409,{'error':str(error)})
        except (ValueError,cv2.error,UnicodeError):self.reply(400,{'error':'Frame/timestamp/body không hợp lệ; dùng phiên mới nếu phát lại video.'})
        except Exception as error:
            self.reply(503,{'error':f'AI chưa sẵn sàng ({type(error).__name__}). Kiểm tra model và console Python.'})


def make_server(port=8765,config=None,model=None,origins=None):
    server=LocalServer(('127.0.0.1',port),Handler)
    default_cfg=HERE/'configs/v2_ml.json' if (HERE/'configs/v2_ml.json').is_file() else HERE/'configs/calibrated-v1_4.json'
    server.pose=PoseSession(config or Config.load(default_cfg),
                            model or HERE/'models/pose_landmarker_full.task')
    server.origins=set(origins or ['http://localhost:7357','http://127.0.0.1:7357'])
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--frontend-origin',action='append')
    args=parser.parse_args()
    server=make_server(args.port,origins=args.frontend_origin)
    print(f'Local pose API: http://127.0.0.1:{server.server_port} | Firebase/FCM disabled',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.pose.close();server.server_close()


if __name__=='__main__':main()
