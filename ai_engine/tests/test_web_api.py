import base64
import json
import threading
from pathlib import Path
import cv2
import numpy as np
import pytest
import requests
from web_server import make_server

ORIGIN={'Origin':'http://localhost:7357'}


@pytest.fixture
def api():
    server=make_server(port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    root=f'http://127.0.0.1:{server.server_port}'
    yield root
    server.shutdown();server.pose.close();server.server_close();thread.join(timeout=3)


def post(root,route,body):
    return requests.post(root+'/api/'+route,headers=ORIGIN,json=body,timeout=15)


def image():
    ok,encoded=cv2.imencode('.jpg',np.zeros((240,320,3),dtype=np.uint8))
    assert ok
    return 'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()


def test_health_is_local_without_cloud_or_notification(api):
    result=requests.get(api+'/api/health',timeout=3)
    assert result.status_code==200
    assert result.json()['mode']=='local' and result.json()['notifications'] is False


def test_contract_is_parseable_and_documents_session_expiry():
    contract=json.loads((Path(__file__).resolve().parents[2]/'api/local_pose.openapi.json').read_text())
    assert '409' in contract['paths']['/api/analyze']['post']['responses']


@pytest.mark.parametrize('origin',['https://untrusted.example','null',None])
def test_other_websites_and_missing_origin_cannot_start_capture_session(api,origin):
    headers={'Origin':origin} if origin else {}
    assert requests.post(api+'/api/start',headers=headers,json={},timeout=3).status_code==403


def test_host_and_cors_preflight(api):
    assert requests.get(api+'/api/health',headers={'Host':'untrusted.example'},timeout=3).status_code==403
    response=requests.options(api+'/api/analyze',headers=ORIGIN,timeout=3)
    assert response.status_code==204
    assert response.headers['Access-Control-Allow-Origin']=='http://localhost:7357'


def test_real_model_on_blank_frame_never_predicts_a_fall_and_timestamps_must_increase(api):
    session=post(api,'start',{}).json()['session_id']
    payload={'session_id':session,'timestamp_s':0,'frame':image()}
    response=post(api,'analyze',payload)
    assert response.status_code==200
    assert response.json()['posture']=='UNKNOWN'
    assert response.json()['notifications'] is False
    assert not any(e['kind'] in ['SUSPECTED_FALL','POSSIBLE_FALL'] for e in response.json()['events'])
    assert post(api,'analyze',payload).status_code==400
    assert post(api,'stop',{'session_id':session}).json()['stopped'] is True
    payload['timestamp_s']=1
    assert post(api,'analyze',payload).status_code==409


def test_new_session_invalidates_previous_and_resets_timestamp(api):
    old=post(api,'start',{}).json()['session_id']
    new=post(api,'start',{}).json()['session_id']
    assert old!=new
    assert post(api,'analyze',{'session_id':old,'timestamp_s':0,'frame':image()}).status_code==409
    assert post(api,'analyze',{'session_id':new,'timestamp_s':0,'frame':image()}).status_code==200


@pytest.mark.parametrize('body',[[],{'timestamp_s':-1,'frame':'data:image/jpeg;base64,AAAA'},{'timestamp_s':True,'frame':'x'},{'timestamp_s':1,'frame':'invalid'}])
def test_invalid_bodies_rejected_without_opening_a_model(api,body):
    assert post(api,'analyze',body).status_code==400
