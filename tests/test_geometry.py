import collections
import math
import unittest
from engine import analyze, stl
from geometry import mesh, bounds, normal


def part(**kwargs):
    return dict(dict(id='p',name='零件',size=[20,10,30],position=[5,7,9],depends_on=[]),**kwargs)


class GeometryTests(unittest.TestCase):
    def test_rotation_about_center(self):
        low,high=bounds(mesh(part(rotation=[0,0,90])))
        for actual,expected in zip(low,[10,2,9]):
            self.assertAlmostEqual(actual,expected)
        for actual,expected in zip(high,[20,22,39]):
            self.assertAlmostEqual(actual,expected)

    def test_closed_outward_meshes(self):
        for shape in ['box','cylinder']:
            m=mesh(part(shape=shape,rotation=[23,48,91]))
            edges=collections.Counter()
            signed_volume=0
            for face in m['faces']:
                for a,b in zip(face,face[1:]+face[:1]):
                    edges[a,b]+=1
                for i in range(1,len(face)-1):
                    a,b,c=[m['vertices'][j] for j in (face[0],face[i],face[i+1])]
                    signed_volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
            for (a,b),count in edges.items():
                self.assertEqual(count,1)
                self.assertEqual(edges[b,a],1)
            expected=6000 if shape=='box' else 6000*48*math.sin(2*math.pi/48)/8
            self.assertAlmostEqual(signed_volume,expected,places=6)

    def test_cylinder_volume_and_stl(self):
        p=part(shape='cylinder')
        report=analyze(dict(name='cylinder',parts=[p]))
        self.assertAlmostEqual(report['volume_mm3'],6000*math.pi/4)
        self.assertEqual(stl(dict(name='cylinder',parts=[p])).count('facet normal'),188)

    def test_validation(self):
        for kwargs in [dict(shape='unknown'),dict(rotation=[0,0]),dict(rotation=[0,float('nan'),0])]:
            with self.assertRaises(ValueError):
                analyze(dict(name='bad',parts=[part(**kwargs)]))

    def test_rotated_collision_uses_mesh_bounds(self):
        a=part(position=[0,0,0],size=[100,10,10],rotation=[0,0,90])
        b=part(id='b',position=[45,30,0],size=[10,10,10])
        self.assertEqual(analyze(dict(name='bounds',parts=[a,b]))['collisions'],[['p','b']])
