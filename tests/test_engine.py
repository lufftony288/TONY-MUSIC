import copy
import unittest
from engine import analyze, demo, radiator, stl

class EngineTests(unittest.TestCase):
    def test_demo_order(self):
        report = analyze(demo())
        self.assertEqual(report['order'][-1], 'top')
        self.assertEqual(report['collisions'], [])

    def test_parallel_layers_and_impact(self):
        report = analyze(demo())
        self.assertEqual(len(report['layers']), 2)
        self.assertEqual(len(report['layers'][0]), 4)
        self.assertEqual(report['layers'][1], ['top'])
        self.assertEqual(report['dependents']['leg-a'], ['top'])
        self.assertEqual(report['dependents']['top'], [])

    def test_cycle_rejected(self):
        p = demo()
        p['parts'][0]['depends_on'] = ['top']
        with self.assertRaisesRegex(ValueError, '循环'):
            analyze(p)

    def test_missing_dependency(self):
        p = demo()
        p['parts'][0]['depends_on'] = ['missing']
        with self.assertRaisesRegex(ValueError, '未找到'):
            analyze(p)

    def test_collision(self):
        p = demo()
        p['parts'][1]['position'] = p['parts'][0]['position'][:]
        self.assertIn(['leg-a', 'leg-b'], analyze(p)['collisions'])

    def test_bad_dimensions(self):
        for value in [0, -1, float('nan'), float('inf'), True]:
            p = demo()
            p['parts'][0]['size'][0] = value
            with self.assertRaises(ValueError):
                analyze(p)

    def test_generation_and_mesh(self):
        p = radiator(fins=200)
        self.assertEqual(len(p['parts']), 204)
        self.assertEqual(analyze(p)['collisions'], [])
        self.assertEqual(stl(p).count('facet normal'), 204 * 12)

    def test_generation_bounds(self):
        for kwargs in [dict(fins=201), dict(fins=2.5), dict(width=0), dict(depth=float('nan'))]:
            with self.assertRaises(ValueError):
                radiator(**kwargs)

    def test_deep_chain(self):
        part = demo()['parts'][0]
        parts = [dict(copy.deepcopy(part), id=str(i), depends_on=[str(i-1)] if i else []) for i in range(1000)]
        self.assertEqual(len(analyze(dict(name='chain', parts=parts))['order']), 1000)

if __name__ == '__main__':
    unittest.main()
