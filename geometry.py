"""Shared polygon geometry, local Z cylinders, centre-pivot XYZ Euler rotation."""
import math


def mesh(part):
    w, d, h = part['size']
    if part.get('shape', 'box') == 'cylinder':
        count = 48
        ring = [(w/2 + w/2*math.cos(i*2*math.pi/count),
                 d/2 + d/2*math.sin(i*2*math.pi/count)) for i in range(count)]
        vertices = [(x,y,z) for z in (0,h) for x,y in ring]
        faces = [list(reversed(range(count))), list(range(count,2*count))]
        faces += [[i,(i+1)%count,(i+1)%count+count,i+count] for i in range(count)]
    else:
        vertices = [(0,0,0),(w,0,0),(w,d,0),(0,d,0),(0,0,h),(w,0,h),(w,d,h),(0,d,h)]
        faces = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    angles = [math.radians(v) for v in part.get('rotation', [0,0,0])]
    sx,sy,sz = map(math.sin, angles)
    cx,cy,cz = map(math.cos, angles)
    transformed = []
    for x,y,z in vertices:
        x,y,z = x-w/2,y-d/2,z-h/2
        y,z = y*cx-z*sx,y*sx+z*cx
        x,z = x*cy+z*sy,-x*sy+z*cy
        x,y = x*cz-y*sz,x*sz+y*cz
        transformed.append([x+w/2+part['position'][0],y+d/2+part['position'][1],z+h/2+part['position'][2]])
    return {'vertices': transformed, 'faces': faces}


def bounds(geometry):
    v = geometry['vertices']
    return ([min(p[i] for p in v) for i in range(3)],
            [max(p[i] for p in v) for i in range(3)])


def normal(a,b,c):
    u = [b[i]-a[i] for i in range(3)]
    v = [c[i]-a[i] for i in range(3)]
    n = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    length = math.sqrt(sum(x*x for x in n))
    return [x/length for x in n] if length else [0,0,0]
