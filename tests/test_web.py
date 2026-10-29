"""Functional tests for auth, per-user CRUD, durable task states and selective retry.

Model calls are mocked here. The Docker smoke run separately exercises real models.
"""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from web.api import create_app
from web.config import ROOT, Settings
from web.database import Comparison
from web.inference import InferenceError
from web.tasks import run_comparison


def photo():
    output = io.BytesIO()
    Image.new('RGB',(80,60),'#b5c98f').save(output,format='PNG')
    return output.getvalue()


def prediction():
    return {'status':'success','dishes':[{'name':'watermelon','weight_g':68,'kcal':20.4}],
            'total':{'kcal':20.4,'protein_g':0.4,'fat_g':0.1,'carb_g':5.2}}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.settings=Settings(state_dir=Path(self.directory.name)/'state',model_dir=Path(self.directory.name)/'models')
        self.app=create_app(self.settings)
        self.client=TestClient(self.app)
        self.client.__enter__()
        self.dispatch=Mock()
        self.app.state.enqueue=self.dispatch
        self.queue_patch=patch('web.api.terminal_failure',return_value=False)
        self.queue_patch.start()
        self.register()

    def tearDown(self):
        self.queue_patch.stop()
        self.client.__exit__(None,None,None)
        self.directory.cleanup()

    def register(self,username='tester_one'):
        response=self.client.post('/api/auth/register',json={'username':username,'password':'fixture-password-123'})
        self.assertEqual(response.status_code,201,response.text)
        return response

    def upload(self):
        response=self.client.post('/api/jobs',files={'file':('plate.png',photo(),'image/png')})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()

    def record(self,identifier):
        return self.client.get(f'/api/jobs/{identifier}').json()

    def test_cookie_is_http_only_and_no_token_in_response(self):
        response=self.client.post('/api/auth/login',json={'username':'tester_one','password':'fixture-password-123'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('token',response.json())
        cookie=response.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie)
        self.assertIn('samesite=strict',cookie)

    def test_login_and_duplicate_registration(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'tester_one','password':'wrong-password'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'TESTER_ONE','password':'another-password'}).status_code,409)

    def test_logout_revokes_captured_bearer_token(self):
        token=self.client.cookies.get('canteen_session')
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}'}).status_code,401)

    def test_tampered_token_and_cross_origin_writes_rejected(self):
        self.assertEqual(self.client.get('/api/jobs',headers={'Authorization':'Bearer invalid'}).status_code,401)
        response=self.client.post('/api/jobs',headers={'Origin':'https://untrusted.example'},files={'file':('p.png',photo(),'image/png')})
        self.assertEqual(response.status_code,403)

    def test_user_isolation_includes_files_updates_delete_and_retry(self):
        job=self.upload();self.client.post('/api/auth/logout');self.register('tester_two')
        self.assertEqual(self.client.get('/api/jobs').json()['total'],0)
        endpoints=[('get',f"/api/jobs/{job['id']}"),('get',f"/api/jobs/{job['id']}/image"),
                   ('get',f"/api/jobs/{job['id']}/overlay"),('delete',f"/api/jobs/{job['id']}"),
                   ('post',f"/api/jobs/{job['id']}/retry")]
        for method,path in endpoints:
            with self.subTest(path=path,method=method):
                self.assertEqual(getattr(self.client,method)(path).status_code,404)
        self.assertEqual(self.client.patch(f"/api/jobs/{job['id']}",json={'title':'stolen','note':''}).status_code,404)

    def test_upload_validation_checks_actual_image_not_extension(self):
        for content,filename in ((b'not an image','fake.jpg'),(b'<svg onload="alert(1)"></svg>','fake.png')):
            response=self.client.post('/api/jobs',files={'file':(filename,content,'image/png')})
            self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.post('/api/jobs',files={'file':('huge.jpg',b'x'*(10*1024*1024+1),'image/jpeg')}).status_code,413)
        self.assertEqual(self.client.post('/api/jobs',files={'file':('empty.jpg',b'','image/jpeg')}).status_code,413)
        self.assertEqual(self.dispatch.call_count,0)

    def test_upload_queues_and_keeps_image_private(self):
        job=self.upload()
        self.dispatch.assert_called_once_with(job['id'],0)
        self.assertEqual(job['status'],'queued')
        self.assertIsNone(job['a_result']);self.assertIsNone(job['b_result'])
        self.assertEqual(self.client.get(job['image_url']).content,photo())
        self.assertNotIn('input_path',job)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(job['image_url']).status_code,401)

    def test_storage_failure_does_not_create_or_enqueue_a_false_task(self):
        with patch('web.api.Path.mkdir',side_effect=OSError('fixture: no space left')):
            response=self.client.post('/api/jobs',files={'file':('p.png',photo(),'image/png')})
        self.assertEqual(response.status_code,507)
        self.dispatch.assert_not_called()
        self.assertEqual(self.client.get('/api/jobs').json()['total'],0)

    def test_per_user_inflight_limit(self):
        for _ in range(3): self.upload()
        response=self.client.post('/api/jobs',files={'file':('p.png',photo(),'image/png')})
        self.assertEqual(response.status_code,429)

    def test_queue_failure_is_recorded_and_retryable(self):
        self.dispatch.side_effect=ConnectionError('fixture queue down')
        job=self.upload()
        self.assertEqual(job['status'],'failed')
        self.assertIsNone(job['a_result']);self.assertIsNone(job['b_result'])
        self.dispatch.side_effect=None
        retried=self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(retried.status_code,202)
        self.assertEqual(retried.json()['generation'],1)
        self.assertEqual(retried.json()['status'],'queued')

    def test_worker_partial_failure_retry_preserves_success(self):
        job=self.upload()
        with patch('web.tasks.run_a',return_value=prediction()) as run_a, \
             patch('web.tasks.run_b',side_effect=InferenceError('fixture format failure')) as run_b:
            run_comparison(job['id'],0,self.settings)
            failed=self.record(job['id'])
            self.assertEqual(failed['status'],'partial')
            self.assertEqual(failed['a_result']['total']['kcal'],20.4)
            self.assertIsNone(failed['b_result'])
            self.assertEqual(failed['b_status'],'failed')
            self.client.post(f"/api/jobs/{job['id']}/retry")
            run_b.side_effect=None;run_b.return_value=prediction()
            run_comparison(job['id'],1,self.settings)
            result=self.record(job['id'])
            self.assertEqual(result['status'],'succeeded')
            self.assertEqual(run_a.call_count,1)
            self.assertEqual(run_b.call_count,2)
            self.assertEqual(result['a_attempts'],1);self.assertEqual(result['b_attempts'],2)

    def test_duplicate_or_stale_queue_delivery_never_runs_twice(self):
        job=self.upload()
        with patch('web.tasks.run_a',return_value=prediction()) as a,patch('web.tasks.run_b',return_value=prediction()) as b:
            run_comparison(job['id'],99,self.settings)
            self.assertEqual(a.call_count,0)
            run_comparison(job['id'],0,self.settings)
            run_comparison(job['id'],0,self.settings)
            self.assertEqual(a.call_count,1);self.assertEqual(b.call_count,1)

    def test_queue_terminal_failure_marks_interrupted_not_zero(self):
        job=self.upload()
        with patch('web.api.terminal_failure',return_value=True):
            record=self.record(job['id'])
        self.assertEqual(record['status'],'failed')
        self.assertEqual(record['a_status'],'failed')
        self.assertIsNone(record['a_result'])

    def test_rq_timeout_is_not_swallowed_as_an_ordinary_model_error(self):
        from rq.timeouts import JobTimeoutException
        job=self.upload()
        with patch('web.tasks.run_a',side_effect=JobTimeoutException('fixture timeout')), \
             patch('web.tasks.run_b') as b, self.assertRaises(JobTimeoutException):
            run_comparison(job['id'],0,self.settings)
        b.assert_not_called()
        record=self.record(job['id'])
        self.assertEqual(record['status'],'failed')
        self.assertIsNone(record['a_result']);self.assertIsNone(record['b_result'])

    def test_live_b_adapter_preserves_bad_reply_and_retries(self):
        from web.inference import run_b
        job=self.upload()
        directory=self.settings.state_dir/'jobs'/job['id']
        bad='{"status":"failed","items":[]}'
        valid='{"items":[{"name":"watermelon","grams":68}]}'
        with patch.dict(os.environ,{'VLM_API_KEY':'fixture-adapter-secret','VLM_MODEL':'fixture'}), \
             patch('vlm.client.call_vlm',side_effect=[bad,valid]) as call:
            result=run_b(directory/'input.png',directory,self.settings)
        self.assertEqual(call.call_count,2)
        self.assertEqual(result['total']['kcal'],20.4)
        failed=json.loads((directory/'b_failures.json').read_text())
        self.assertEqual(failed[0]['status'],'failed')
        self.assertEqual(failed[0]['raw'],bad)

    def test_live_b_adapter_propagates_global_queue_timeout(self):
        from web.inference import run_b
        from rq.timeouts import JobTimeoutException
        job=self.upload()
        directory=self.settings.state_dir/'jobs'/job['id']
        with patch.dict(os.environ,{'VLM_API_KEY':'fixture-adapter-secret','VLM_MODEL':'fixture'}), \
             patch('vlm.client.call_vlm',side_effect=JobTimeoutException('deadline')) as call, \
             self.assertRaises(JobTimeoutException):
            run_b(directory/'input.png',directory,self.settings)
        self.assertEqual(call.call_count,1)

    def test_title_note_crud_and_running_delete_guard(self):
        job=self.upload()
        self.assertEqual(self.client.delete(f"/api/jobs/{job['id']}").status_code,409)
        response=self.client.patch(f"/api/jobs/{job['id']}",json={'title':'午餐记录','note':'测试备注'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['note'],'测试备注')
        self.assertEqual(self.client.patch(f"/api/jobs/{job['id']}",json={'title':'  '}).status_code,422)
        with patch('web.tasks.run_a',return_value=prediction()),patch('web.tasks.run_b',return_value=prediction()):
            run_comparison(job['id'],0,self.settings)
        self.assertEqual(self.client.delete(f"/api/jobs/{job['id']}").status_code,200)
        self.assertFalse((self.settings.state_dir/'jobs'/job['id']).exists())
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").status_code,404)

    def test_real_saved_replay_validates_raw_and_uses_no_api(self):
        response=self.client.post('/api/jobs/from-sample',json={'sample_id':'dish_1558027001','mode':'replay'})
        self.assertEqual(response.status_code,202)
        job=response.json()
        with patch('web.tasks.run_a') as a,patch('web.tasks.run_b') as b:
            run_comparison(job['id'],0,self.settings)
            a.assert_not_called();b.assert_not_called()
        result=self.record(job['id'])
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['b_result']['provenance']['mode'],'replay')
        self.assertIn('watermelon',result['b_result']['raw'])
        self.assertEqual(self.client.get(result['overlay_url']).status_code,200)

    def test_secret_and_records_survive_app_restart(self):
        job=self.upload()
        cookie=self.client.cookies.get('canteen_session')
        second_app=create_app(self.settings)
        with TestClient(second_app) as client:
            client.cookies.set('canteen_session',cookie)
            self.assertEqual(client.get('/api/auth/me').status_code,200)
            self.assertEqual(client.get('/api/jobs').json()['items'][0]['id'],job['id'])

    def test_static_app_and_openapi_are_served(self):
        self.assertIn('Canteen Lab',self.client.get('/').text)
        self.assertEqual(self.client.get('/static/app.js').status_code,200)
        schema=self.client.get('/openapi.json').json()
        self.assertIn('/api/jobs/{job_id}/retry',schema['paths'])
        self.assertNotIn('VLM_API_KEY',schema['paths'])


if __name__=='__main__':
    unittest.main()
