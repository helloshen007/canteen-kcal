"""Exercise a running deployment through nginx. --live makes a paid VLM request.

Default: replay only, no model/API calls. Temporary passwords are never printed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import time

import httpx

ROOT=Path(__file__).resolve().parent.parent


def expect(response,status):
    if response.status_code!=status:
        raise RuntimeError(f'{response.request.method} {response.request.url.path}: expected {status}, got {response.status_code}')
    return response.json()


def wait(client,identifier,timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=expect(client.get(f'/api/jobs/{identifier}'),200)
        if job['status'] not in {'queued','running'}:
            return job
        time.sleep(0.5)
    raise RuntimeError('Comparison did not reach a terminal status before the smoke-test deadline')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8080')
    parser.add_argument('--output',type=Path,default=ROOT/'results/stage3/smoke.json')
    parser.add_argument('--live',action='store_true',help='Upload a real image and run both models; incurs API fees')
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--browser-state',type=Path,help='Optional private browser session file, outside repository only')
    args=parser.parse_args()
    if args.browser_state and args.browser_state.resolve().is_relative_to(ROOT):
        parser.error('Browser session files must be outside the repository')
    started=time.monotonic()
    checks={}
    username='smoke_'+secrets.token_hex(5)
    credentials={'username':username,'password':secrets.token_urlsafe(24)}
    with httpx.Client(base_url=args.base_url,timeout=20) as client:
        health=expect(client.get('/api/health'),200)
        assert health['status']=='ok', 'Background worker is not ready'
        assert 'Canteen Lab' in client.get('/').text
        expect(client.post('/api/auth/register',json=credentials),201)
        expect(client.post('/api/jobs',files={'file':('invalid.png',b'not an image','image/png')}),422)
        checks['invalid_image_rejected']=True
        queued=expect(client.post('/api/jobs/from-sample',json={'sample_id':'dish_1558027001','mode':'replay'}),202)
        record=wait(client,queued['id'],args.timeout)
        assert record['status']=='succeeded',record['status']
        assert record['a_result']['provenance']['mode']==record['b_result']['provenance']['mode']=='replay'
        assert client.get(record['overlay_url']).status_code==200
        checks['redis_worker_replay_completed']=True
        edited=expect(client.patch(f"/api/jobs/{record['id']}",json={'title':'三阶段演示 · 西瓜','note':'真实历史回放；不是新推理'}),200)
        assert edited['note']=='真实历史回放；不是新推理'
        checks['update_persisted']=True
        with httpx.Client(base_url=args.base_url,timeout=20) as other:
            expect(other.post('/api/auth/register',json={'username':username+'_other','password':secrets.token_urlsafe(24)}),201)
            for path in (f"/api/jobs/{record['id']}",record['image_url'],record['overlay_url']):
                expect(other.get(path),404)
            assert expect(other.get('/api/jobs'),200)['total']==0
        checks['other_account_cannot_read_record_or_images']=True
        token=client.cookies.get('canteen_session')
        expect(client.post('/api/auth/logout'),200)
        expect(client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}'}),401)
        expect(client.post('/api/auth/login',json=credentials),200)
        checks['logout_revokes_jwt']=True
        assert expect(client.get('/api/jobs'),200)['items'][0]['id']==record['id']
        checks['history_persisted']=True
        expect(client.delete(f"/api/jobs/{record['id']}"),200)
        expect(client.get(f"/api/jobs/{record['id']}"),404)
        checks['delete_removes_record']=True
        live=None
        if args.live:
            print('Submitting one real comparison through nginx; VLM API fees apply.',flush=True)
            source=ROOT/'web/examples/dish_1558027001/input.jpg'
            queued=expect(client.post('/api/jobs',files={'file':('stage3-watermelon.jpg',source.read_bytes(),'image/jpeg')}),202)
            live=wait(client,queued['id'],args.timeout)
            if live['status']!='succeeded':
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps({'checks':checks,'health':health,'live_job':live},ensure_ascii=False,indent=2)+'\n')
                raise RuntimeError('Live comparison failed; inspect the saved safe result and retry failed methods only')
            assert live['mode']=='live'
            assert live['a_result']['provenance']['mode']==live['b_result']['provenance']['mode']=='live'
            assert live['b_result']['raw']
            checks['real_upload_yolo_sam_and_vlm_completed']=True
        if args.browser_state:
            cookies=[{'name':cookie.name,'value':cookie.value,'url':args.base_url,'httpOnly':True,'sameSite':'Strict'} for cookie in client.cookies.jar]
            args.browser_state.parent.mkdir(parents=True,exist_ok=True)
            descriptor=os.open(args.browser_state,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(descriptor,'w') as stream:
                json.dump({'cookies':cookies,'username':username,'live_job_id':live['id'] if live else None},stream)
    output={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-started,2),
            'checks':checks,'health':health,'live_job':live}
    text=json.dumps(output,ensure_ascii=False,indent=2)+'\n'
    secret=os.getenv('VLM_API_KEY')
    if secret and secret in text:
        raise RuntimeError('Refusing to write a credential into evidence')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text)
    print(json.dumps({'checks':checks,'live_status':live['status'] if live else 'not requested',
                      'elapsed_seconds':output['elapsed_seconds'],'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':
    main()
