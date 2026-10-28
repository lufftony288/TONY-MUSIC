import io
import threading
import tempfile
import unittest
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch,Mock
import server
import ai_provider as ai
from model_fixtures import glb


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        guard=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No live upstream in tests'))
        guard.start();self.addCleanup(guard.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        db=patch.object(server,'DB',Path(self.temp.name)/'db.sqlite3');db.start();self.addCleanup(db.stop)
        with server.connect():pass
    def test_concurrent_duplicate_submissions_create_one_remote_task(self):
        started=threading.Event();release=threading.Event()
        def remote(*args):started.set();self.assertTrue(release.wait(10));return {'result':'one-remote'}
        request={'prompt':'one object','client_request_id':'c'*32}
        with patch.object(ai,'request_json',side_effect=remote) as upstream,ThreadPoolExecutor(max_workers=9) as pool:
            first=pool.submit(ai.submit,server.connect,request)
            try:
                self.assertTrue(started.wait(5))
                def repeated(_):
                    try:ai.submit(server.connect,request)
                    except ai.ProviderError:return 'blocked'
                results=list(pool.map(repeated,range(40)))
                self.assertEqual(results,['blocked']*40)
            finally:release.set()
            initial=first.result(10)
            self.assertEqual(ai.submit(server.connect,request)['id'],initial['id'])
            self.assertEqual(upstream.call_count,1)
    def test_interrupted_submission_reservation_does_not_resubmit(self):
        request_id='d'*32
        with server.connect() as con:con.execute('INSERT INTO generation_submissions (id) VALUES (?)',(request_id,))
        with patch.object(ai,'request_json') as upstream:
            with self.assertRaises(ai.ProviderError):ai.submit(server.connect,{'prompt':'test','client_request_id':request_id})
        upstream.assert_not_called()
    def test_http_error_messages_are_actionable_and_do_not_echo_body(self):
        for code,fragment in [(400,'参数'),(401,'授权'),(402,'额度'),(403,'授权'),(429,'频率'),(500,'接口')]:
            opener=Mock();opener.open.side_effect=urllib.error.HTTPError('https://api.meshy.ai',code,'error',{},io.BytesIO(b'private-key-do-not-echo'))
            with patch.dict('os.environ',{'MESHY_API_KEY':'test-only'}),patch('ai_provider.urllib.request.build_opener',return_value=opener):
                with self.assertRaises(ai.ProviderError) as result:ai.request_json('/openapi/v2/text-to-3d',{'prompt':'test'})
            self.assertIn(fragment,str(result.exception));self.assertNotIn('private-key',str(result.exception))
    def test_unrecognized_status_preserves_job_for_manual_recheck(self):
        with patch.object(ai,'request_json',return_value={'result':'remote'}):job=ai.submit(server.connect,{'prompt':'test'})
        with patch.object(ai,'request_json',return_value={'status':'NEW_UNKNOWN_STATE'}):result=ai.poll(server.connect,job['id'])
        self.assertEqual(result['status'],'PENDING');self.assertIn('未知',result['error'])
    def test_invalid_progress_is_normalized(self):
        for progress in [float('nan'),float('inf'),'50',None,-20,200]:
            with patch.object(ai,'request_json',return_value={'result':'remote'}):job=ai.submit(server.connect,{'prompt':'test'})
            with patch.object(ai,'request_json',return_value={'status':'IN_PROGRESS','progress':progress}):result=ai.poll(server.connect,job['id'])
            self.assertTrue(0<=result['progress']<=100)
    def test_invalid_download_can_be_retried_without_new_submission(self):
        with patch.object(ai,'request_json',return_value={'result':'remote'}):job=ai.submit(server.connect,{'prompt':'test'})
        response={'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/model.glb'}}
        with patch.object(ai,'request_json',return_value=response),patch.object(ai,'download_glb',return_value=b'not a glb'):
            self.assertIsNone(ai.poll(server.connect,job['id'])['asset_id'])
        with server.connect() as con:con.execute('UPDATE generation_jobs SET last_checked=0 WHERE id=?',(job['id'],))
        with patch.object(ai,'request_json',return_value=response),patch.object(ai,'download_glb',return_value=glb()):
            self.assertEqual(ai.poll(server.connect,job['id'])['status'],'SUCCEEDED')
        with server.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM generation_jobs').fetchone()[0],1)
    def test_concurrent_completion_downloads_only_once(self):
        with patch.object(ai,'request_json',return_value={'result':'remote'}):job=ai.submit(server.connect,{'prompt':'test'})
        started=threading.Event();release=threading.Event()
        def download(url):started.set();self.assertTrue(release.wait(10));return glb()
        with patch.object(ai,'request_json',return_value={'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/a.glb'}}),patch.object(ai,'download_glb',side_effect=download) as downloader,ThreadPoolExecutor(max_workers=8) as pool:
            first=pool.submit(ai.poll,server.connect,job['id'])
            try:
                self.assertTrue(started.wait(5));list(pool.map(lambda _:ai.poll(server.connect,job['id']),range(30)))
            finally:release.set()
            self.assertEqual(first.result(10)['status'],'SUCCEEDED');self.assertEqual(downloader.call_count,1)
    def test_download_rejects_credential_urls_and_invalid_ports(self):
        for url in ['https://assets.meshy.ai:invalid/a','https://assets.meshy.ai:444/a','file:///etc/passwd','https://assets.meshy.ai@evil.invalid/a']:
            with self.assertRaises(ai.ProviderError):ai.download_glb(url)
    def test_same_nonce_with_changed_input_is_rejected(self):
        with patch.object(ai,'request_json',return_value={'result':'one'}) as upstream:
            ai.submit(server.connect,{'prompt':'first object','client_request_id':'e'*32})
            with self.assertRaises(ai.ProviderError):ai.submit(server.connect,{'prompt':'different object','client_request_id':'e'*32})
        self.assertEqual(upstream.call_count,1)
