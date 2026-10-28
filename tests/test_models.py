import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import server
from models import save_model,validate_model,generator_config
from model_fixtures import glb,OBJ,STL,BINARY_STL


class ModelTests(unittest.TestCase):
    def setUp(self):
        # Published environments may contain live credentials; custom-contract tests must never select Meshy.
        guard=patch.dict(os.environ,{'MODEL_GENERATOR_PROVIDER':'custom','MESHY_API_KEY':''})
        guard.start();self.addCleanup(guard.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Live upstream traffic is forbidden in unit tests'))
        network.start();self.addCleanup(network.stop)
    def test_supported_files_and_corruption(self):
        for name,data in [('model.glb',glb()),('model.obj',OBJ),('model.stl',STL),('binary.stl',BINARY_STL)]:
            self.assertEqual(validate_model(name,data),Path(name).suffix)
        for name,data in [('bad.glb',glb()[:-1]),('bad.stl',b'bad'),('empty.obj',b'v 0 0 0'),('bad.html',b'anything')]:
            with self.assertRaises(ValueError):validate_model(name,data)

    def test_saved_files_have_safe_names_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'):
            a=save_model(server.connect,'../../模型.glb',glb())
            b=save_model(server.connect,'../../模型.glb',glb())
            self.assertNotEqual(a['id'],b['id'])
            self.assertEqual(a['name'],'模型.glb')
            self.assertEqual((Path(folder)/'models'/(a['id']+'.glb')).read_bytes(),glb())
            with server.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM models').fetchone()[0],2)

    def test_external_glb_resources_rejected(self):
        with self.assertRaisesRegex(ValueError,'内嵌'):
            validate_model('external.glb',glb(external=True))

    def test_invalid_upstream_output_is_not_saved(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'),patch.dict(os.environ,{'MODEL_GENERATOR_URL':'https://provider.invalid/generate'}):
            opener=Mock();opener.open.return_value=io.BytesIO(b'not a model')
            handler=object.__new__(server.Handler);handler.reply=Mock()
            with patch('server.urllib.request.build_opener',return_value=opener):
                handler.generate_model({'prompt':'test'})
            self.assertEqual(handler.reply.call_args.args[0],502)
            self.assertFalse((Path(folder)/'models').exists())

    def test_generator_unconfigured_is_explicit(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(generator_config()['configured'])
            handler=object.__new__(server.Handler);handler.reply=Mock()
            handler.generate_model({'prompt':'object'})
            self.assertEqual(handler.reply.call_args.args[0],503)

    def test_custom_adapter_contract_with_mocked_upstream(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'),patch.dict(os.environ,{'MODEL_GENERATOR_URL':'https://provider.invalid/generate','MODEL_GENERATOR_KEY':'test-key'}):
            response=io.BytesIO(glb())
            opener=Mock();opener.open.return_value=response
            handler=object.__new__(server.Handler);handler.reply=Mock()
            with patch('server.urllib.request.build_opener',return_value=opener):
                handler.generate_model({'prompt':'an assembly','image_data_url':None})
            request=opener.open.call_args.args[0]
            self.assertEqual(json.loads(request.data)['format'],'glb')
            self.assertEqual(request.get_header('Authorization'),'Bearer test-key')
            self.assertEqual(handler.reply.call_args.args[0],201)
            self.assertTrue((Path(folder)/'models'/(handler.reply.call_args.args[1]['id']+'.glb')).exists())

    def test_generator_rejects_bad_input(self):
        with patch.dict(os.environ,{'MODEL_GENERATOR_URL':'https://provider.invalid/generate'}):
            handler=object.__new__(server.Handler);handler.reply=Mock()
            for value in [None,{}, {'prompt':''},{'prompt':'x','image_data_url':'https://example.com/a.png'}]:
                with self.assertRaises(ValueError):handler.generate_model(value)
        with patch.dict(os.environ,{'MODEL_GENERATOR_URL':'http://provider.invalid/generate'}):
            handler.generate_model({'prompt':'test'})
            self.assertEqual(handler.reply.call_args.args[0],503)
