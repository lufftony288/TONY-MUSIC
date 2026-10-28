import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
import ai_provider as ai

class MeshOptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        db=patch.object(server,'DB',Path(self.temp.name)/'db.sqlite3');db.start();self.addCleanup(db.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No live provider traffic in tests'));network.start();self.addCleanup(network.stop)
    def submitted(self,options,image=None):
        with patch.object(ai,'request_json',return_value={'result':'remote'}) as remote:
            job=ai.submit(server.connect,{'prompt':'assembly','image_data_url':image,'generation_options':options})
        return job,remote.call_args.args
    def test_standard_target_enables_remesh(self):
        job,(path,payload)=self.submitted({'target_polycount':20000})
        self.assertTrue(payload['should_remesh']);self.assertEqual(payload['target_polycount'],20000)
        self.assertEqual(payload['topology'],'triangle');self.assertNotIn('ai_model',payload)
        self.assertEqual(job['generation_options'],{'mesh_mode':'standard','target_polycount':20000})
    def test_parts_defaults_are_explicit(self):
        job,(_,payload)=self.submitted({'mesh_mode':'parts'})
        self.assertEqual(payload['model_type'],'smart-topology');self.assertEqual(payload['ai_model'],'meshy-t2')
        self.assertEqual(payload['target_polycount'],4000);self.assertNotIn('should_remesh',payload)
        self.assertEqual(job['generation_options']['target_polycount'],4000)
    def test_detail_uses_t25_with_its_own_range(self):
        _,(_,payload)=self.submitted({'mesh_mode':'detail','target_polycount':25000})
        self.assertEqual(payload['ai_model'],'meshy-t2.5');self.assertEqual(payload['target_polycount'],25000)
        self.assertEqual(payload['topology'],'triangle')
    def test_image_receives_same_explicit_options(self):
        image='data:image/png;base64,aGVsbG8='
        _,(path,payload)=self.submitted({'mesh_mode':'parts','target_polycount':8000},image)
        self.assertEqual(path,'/openapi/v1/image-to-3d');self.assertEqual(payload['image_url'],image)
        self.assertFalse(payload['should_texture']);self.assertEqual(payload['target_polycount'],8000)
    def test_invalid_options_never_contact_provider(self):
        cases=[None,[],{'mesh_mode':'lowpoly'},{'mesh_mode':'other'},{'mesh_mode':'parts','target_polycount':15001},{'mesh_mode':'detail','target_polycount':30001},{'target_polycount':300001},{'target_polycount':99},{'target_polycount':True},{'target_polycount':100.5},{'target_polycount':'4000'},{'topology':'quad'}]
        with patch.object(ai,'request_json') as remote:
            for options in cases:
                with self.subTest(options=options),self.assertRaises(ValueError):
                    ai.submit(server.connect,{'prompt':'assembly','generation_options':options})
            remote.assert_not_called()
    def test_long_text_rejected_but_image_label_is_not_sent_as_prompt(self):
        with patch.object(ai,'request_json',return_value={'result':'remote'}) as remote:
            with self.assertRaisesRegex(ValueError,'800'):ai.submit(server.connect,{'prompt':'x'*801})
            remote.assert_not_called()
            ai.submit(server.connect,{'prompt':'x'*800})
            ai.submit(server.connect,{'prompt':'x'*801,'image_data_url':'data:image/png;base64,aGVsbG8='})
            self.assertNotIn('prompt',remote.call_args.args[1])
    def test_nonce_binds_mesh_strategy_and_target(self):
        request={'prompt':'assembly','client_request_id':'f'*32,'generation_options':{'mesh_mode':'parts','target_polycount':4000}}
        with patch.object(ai,'request_json',return_value={'result':'remote'}) as remote:
            first=ai.submit(server.connect,request)
            self.assertEqual(ai.submit(server.connect,request)['id'],first['id'])
            request['generation_options']['target_polycount']=5000
            with self.assertRaises(ai.ProviderError):ai.submit(server.connect,request)
            self.assertEqual(remote.call_count,1)
    def test_snapshot_is_immutable_after_input_changes(self):
        options={'mesh_mode':'detail','target_polycount':24000};job,_=self.submitted(options)
        options['target_polycount']=100
        restored=ai.get_job(server.connect,job['id'])
        self.assertEqual(restored['generation_options']['target_polycount'],24000)
        with server.connect() as con:
            self.assertEqual(json.loads(con.execute('SELECT options FROM generation_job_options').fetchone()[0])['mesh_mode'],'detail')
