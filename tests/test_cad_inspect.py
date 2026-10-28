import hashlib
import math
import subprocess
import unittest
from unittest.mock import patch
from cad_inspect import inspect_step
from step_import import CONVERSION_SLOT,StepUnavailable
from step_fixtures import step_fixture

class CadInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=step_fixture()
    def test_analytic_boxes_and_hash(self):
        result=inspect_step(self.source,{'a':'solid-0001','b':'solid-0002'})
        self.assertEqual(result['valid_bodies'],2)
        self.assertAlmostEqual(result['sum_body_volume_mm3'],250000,places=5)
        self.assertEqual(result['pair']['minimum_distance_mm'],50)
        self.assertEqual(result['pair']['intersection_volume_mm3'],0)
        self.assertEqual(result['pair']['state'],'separate')
        self.assertEqual(result['source_sha256'],hashlib.sha256(self.source).hexdigest())
        self.assertIn('Right block',result['bodies'][1]['name'])
    def test_touch_and_interference_are_distinguished(self):
        for spacing,state,volume in [(100,'touching_or_within_tolerance',0),(90,'overlap',12500),(0,'overlap',125000)]:
            result=inspect_step(step_fixture(spacing=spacing),{'a':'solid-0001','b':'solid-0002'})
            self.assertEqual(result['pair']['state'],state)
            self.assertAlmostEqual(result['pair']['intersection_volume_mm3'],volume,places=5)
            self.assertEqual(result['pair']['minimum_distance_mm'],0)
    def test_nested_translation_and_source_units(self):
        source=step_fixture(frame_offset=400).replace(b'SI_UNIT(.MILLI.,.METRE.)',b'SI_UNIT(.CENTI.,.METRE.)')
        result=inspect_step(source,{'a':'solid-0001','b':'solid-0002'})
        self.assertAlmostEqual(result['pair']['minimum_distance_mm'],500)
        self.assertAlmostEqual(result['bodies'][0]['bounds_min_mm'][0],4000)
        self.assertAlmostEqual(result['bodies'][1]['bounds_min_mm'][0],5500)
        self.assertAlmostEqual(result['sum_body_volume_mm3'],250000000,places=2)
    def test_curved_volume_is_not_tessellated(self):
        result=inspect_step(step_fixture(assembly=False))
        self.assertEqual(len(result['bodies']),1)
        self.assertAlmostEqual(result['bodies'][0]['volume_mm3'],math.pi*20**2*80,places=5)
    def test_bad_selection_never_starts_native_worker(self):
        with patch('cad_inspect.subprocess.run') as run:
            for request in [[],{'a':'solid-0001'},{'a':'../escape','b':'solid-0002'},{'a':'solid-0001','b':'solid-0001'},{'path':'/etc/passwd'}]:
                with self.assertRaises(ValueError):inspect_step(self.source,request)
            run.assert_not_called()
    def test_unknown_selection_and_malformed_source(self):
        with self.assertRaisesRegex(ValueError,'不存在'):inspect_step(self.source,{'a':'solid-0001','b':'solid-0999'})
        with self.assertRaises(ValueError):inspect_step(b'not a step')
    def test_timeout_and_busy_release_resources(self):
        with patch('cad_inspect.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',60)):
            with self.assertRaisesRegex(ValueError,'60 秒'):inspect_step(self.source)
        self.assertTrue(CONVERSION_SLOT.acquire(blocking=False));CONVERSION_SLOT.release()
        CONVERSION_SLOT.acquire()
        try:
            with self.assertRaises(StepUnavailable):inspect_step(self.source)
        finally:CONVERSION_SLOT.release()
