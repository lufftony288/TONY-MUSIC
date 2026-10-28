import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import server
from models import save_model, validate_model
from step_import import convert_step, StepUnavailable, CONVERSION_SLOT
from step_fixtures import step_fixture


def document(data):
    length=struct.unpack_from('<I',data,12)[0]
    return json.loads(data[20:20+length])


class StepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=step_fixture()
        cls.preview=convert_step(cls.source)
    def test_structure_names_placement_and_colors(self):
        doc=document(self.preview)
        names=[n.get('name') for n in doc['nodes']]
        for name in ['Fixture assembly','Frame','Left block','Right block']:
            self.assertIn(name,names)
        right=next(n for n in doc['nodes'] if n.get('name')=='Right block')
        self.assertEqual(right['translation'],[.15,0,0])
        frame=next(n for n in doc['nodes'] if n.get('name')=='Frame')
        self.assertEqual(len(frame['children']),2)
        self.assertTrue(doc['materials'])
        self.assertEqual(validate_model('preview.glb',self.preview),'.glb')
    def test_millimetres_and_centimetres_are_normalized(self):
        doc=document(self.preview)
        positions=[a for a in doc['accessors'] if a.get('type')=='VEC3' and 'max' in a]
        self.assertEqual(positions[0]['max'],[.1,.05,.025])
        centimetres=self.source.replace(b'SI_UNIT(.MILLI.,.METRE.)',b'SI_UNIT(.CENTI.,.METRE.)')
        doc=document(convert_step(centimetres))
        positions=[a for a in doc['accessors'] if a.get('type')=='VEC3' and 'max' in a]
        for actual,expected in zip(positions[0]['max'],[1,.5,.25]):
            self.assertAlmostEqual(actual,expected)
    def test_step_schemas_and_curved_geometry(self):
        for schema in ['AP203','AP242DIS']:
            data=convert_step(step_fixture(schema,assembly=False))
            doc=document(data)
            self.assertTrue(doc['meshes'])
            self.assertIn('Cylinder',[n.get('name') for n in doc['nodes']])
    def test_hundred_instance_assembly_keeps_all_placements(self):
        doc=document(convert_step(step_fixture(instances=100)))
        nodes=[n for n in doc['nodes'] if 'mesh' in n]
        self.assertEqual(len(nodes),100)
        last=next(n for n in nodes if n.get('name')=='Block 100')
        self.assertAlmostEqual(last['translation'][0],14.85)

    def test_source_and_preview_persist_independently(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'):
            asset=save_model(server.connect,'Assembly.STP',self.source)
            self.assertEqual(asset['preview_extension'],'.glb')
            self.assertEqual(asset['preview_units'],'m')
            self.assertEqual((Path(folder)/'models'/(asset['id']+'.stp')).read_bytes(),self.source)
            self.assertEqual(validate_model('preview.glb',(Path(folder)/'models'/(asset['id']+'.preview.glb')).read_bytes()),'.glb')
    def test_invalid_files_and_timeout(self):
        with self.assertRaisesRegex(ValueError,'标记'):
            validate_model('broken.step',b'ISO-10303-21;')
        with self.assertRaises(ValueError):
            convert_step(b'ISO-10303-21; HEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;')
        with patch('step_import.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',60)):
            with self.assertRaisesRegex(ValueError,'60 秒'):convert_step(self.source)
    def test_conversion_slot_and_missing_kernel(self):
        CONVERSION_SLOT.acquire()
        try:
            with self.assertRaises(StepUnavailable):convert_step(self.source)
        finally:CONVERSION_SLOT.release()
        with patch('step_import.importlib.util.find_spec',return_value=None):
            with self.assertRaises(StepUnavailable):convert_step(self.source)
    def test_failed_conversion_does_not_create_model(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'),patch('step_import.convert_step',side_effect=ValueError('bad')):
            with self.assertRaises(ValueError):save_model(server.connect,'broken.step',self.source)
            self.assertFalse((Path(folder)/'models').exists())
