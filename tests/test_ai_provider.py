import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import server
import ai_provider as ai
from model_fixtures import glb


class MeshyTests(unittest.TestCase):
    def setUp(self):
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Live upstream traffic is forbidden in unit tests'));network.start();self.addCleanup(network.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(server,'DB',Path(self.temp.name)/'db.sqlite3');self.db.start()
    def tearDown(self):
        self.db.stop();self.temp.cleanup()
    def submit(self,image=None):
        with patch.object(ai,'request_json',return_value={'result':'remote-123'}) as request:
            job=ai.submit(server.connect,{'prompt':'a mechanical assembly','image_data_url':image})
        return job,request
    def test_text_and_image_payloads(self):
        job,request=self.submit()
        self.assertEqual(request.call_args.args,('/openapi/v2/text-to-3d',{'mode':'preview','prompt':'a mechanical assembly'}))
        image='data:image/png;base64,aGVsbG8='
        job,request=self.submit(image)
        self.assertEqual(request.call_args.args,('/openapi/v1/image-to-3d',{'image_url':image,'should_texture':False}))
        with server.connect() as con:
            serialized=str(con.execute('SELECT * FROM generation_jobs').fetchall())
        self.assertNotIn(image,serialized)
        self.assertEqual(job['status'],'PENDING')
    def test_progress_completion_saved_only_once(self):
        job,_=self.submit()
        with patch.object(ai,'request_json',return_value={'status':'IN_PROGRESS','progress':25}):
            self.assertEqual(ai.poll(server.connect,job['id'])['progress'],25)
        with server.connect() as con:con.execute('UPDATE generation_jobs SET last_checked=0')
        with patch.object(ai,'request_json',return_value={'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/a.glb?signature=private'}}),patch.object(ai,'download_glb',return_value=glb()) as download:
            done=ai.poll(server.connect,job['id'])
            again=ai.poll(server.connect,job['id'])
            self.assertEqual(done['status'],'SUCCEEDED')
            self.assertEqual(done['asset']['id'],again['asset']['id'])
            self.assertEqual(download.call_count,1)
        with server.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM models').fetchone()[0],1)
            self.assertNotIn('signature',str(con.execute('SELECT * FROM generation_jobs').fetchall()))
    def test_download_error_is_retryable_without_resubmit(self):
        job,_=self.submit()
        with patch.object(ai,'request_json',return_value={'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/a.glb'}}),patch.object(ai,'download_glb',side_effect=ai.ProviderError('download failed')):
            pending=ai.poll(server.connect,job['id'])
        self.assertEqual(pending['status'],'PENDING')
        self.assertEqual(pending['error'],'download failed')
        with server.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM generation_jobs').fetchone()[0],1)
    def test_failed_remote_task(self):
        job,_=self.submit()
        with patch.object(ai,'request_json',return_value={'status':'FAILED'}):
            result=ai.poll(server.connect,job['id'])
        self.assertEqual(result['status'],'FAILED')
        self.assertIsNone(result['asset_id'])
    def test_malformed_response_and_url(self):
        with patch.object(ai,'request_json',return_value={'result':'../escape'}):
            with self.assertRaises(ai.ProviderError):ai.submit(server.connect,{'prompt':'test'})
        for url in ['http://assets.meshy.ai/a','https://evil.invalid/a','https://assets.meshy.ai.evil.invalid/a','https://key@assets.meshy.ai/a']:
            with self.assertRaises(ai.ProviderError):ai.download_glb(url)
    def test_download_does_not_forward_token(self):
        opener=Mock();opener.open.return_value=io.BytesIO(glb())
        with patch.dict(os.environ,{'MESHY_API_KEY':'test-key'}),patch('ai_provider.urllib.request.build_opener',return_value=opener):
            ai.download_glb('https://assets.meshy.ai/a.glb')
        self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
    def test_unconfigured_provider_is_disabled(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(server.generator_config()['configured'])
            with self.assertRaises(ai.ProviderError):ai.request_json('/path')

class SubmissionDedupTests(unittest.TestCase):
    def setUp(self):
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Live upstream traffic is forbidden in unit tests'));network.start();self.addCleanup(network.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(server,'DB',Path(self.temp.name)/'db.sqlite3');self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_repeated_request_returns_same_job_without_new_charge(self):
        request={'prompt':'test stool','client_request_id':'a'*32}
        with patch.object(ai,'request_json',return_value={'result':'remote-one'}) as upstream:
            first=ai.submit(server.connect,request)
            second=ai.submit(server.connect,request)
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(upstream.call_count,1)
    def test_uncertain_submission_is_not_automatically_retried(self):
        request={'prompt':'test stool','client_request_id':'b'*32}
        with patch.object(ai,'request_json',side_effect=ai.ProviderError('outcome unknown')) as upstream:
            for _ in range(2):
                with self.assertRaises(ai.ProviderError):ai.submit(server.connect,request)
        self.assertEqual(upstream.call_count,1)
        self.assertEqual(ai.list_jobs(server.connect),[])
    def test_bad_request_id_is_rejected_before_submission(self):
        with patch.object(ai,'request_json') as upstream:
            with self.assertRaises(ValueError):ai.submit(server.connect,{'prompt':'test','client_request_id':'bad'})
        upstream.assert_not_called()
