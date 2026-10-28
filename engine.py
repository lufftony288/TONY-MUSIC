"""Explicit, deterministic assembly model; dimensions are millimetres."""
import math
from geometry import mesh, bounds, normal


def validate(project):
    if not isinstance(project, dict):
        raise ValueError('项目必须为对象')
    if not isinstance(project.get('name'), str) or not project['name'].strip():
        raise ValueError('请输入项目名称')
    parts = project.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 1000:
        raise ValueError('项目需要 1–1000 个零件')
    by_id = {}
    for p in parts:
        if not isinstance(p, dict):
            raise ValueError('零件格式错误')
        key = p.get('id')
        if not isinstance(key, str) or not key or key in by_id:
            raise ValueError('零件 ID 必须唯一且非空')
        if not isinstance(p.get('name'), str) or not p['name'].strip():
            raise ValueError('零件需要名称')
        for field in ('size', 'position'):
            vec = p.get(field)
            if not isinstance(vec, list) or len(vec) != 3:
                raise ValueError(f'{key}: {field} 必须有三个数值')
            if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in vec):
                raise ValueError(f'{key}: 尺寸或坐标无效')
        if min(p['size']) <= 0:
            raise ValueError(f'{key}: 尺寸必须大于零')
        if p.get('shape', 'box') not in ('box', 'cylinder'):
            raise ValueError('形状必须为 box 或 cylinder')
        rotation = p.get('rotation', [0,0,0])
        if not isinstance(rotation, list) or len(rotation) != 3 or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 36000 for v in rotation):
            raise ValueError('旋转角度必须为三个有限数值（绝对值不超过 36000 度）')
        deps = p.get('depends_on', [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise ValueError('依赖必须为 ID 数组')
        by_id[key] = p
    for p in parts:
        for d in p.get('depends_on', []):
            if d not in by_id:
                raise ValueError(f'{p["id"]}: 未找到依赖 {d}')
    # Kahn ordering: visit dependency edges once instead of rescanning all parts.
    index = {p['id']: i for i, p in enumerate(parts)}
    remaining = {p['id']: len(set(p.get('depends_on', []))) for p in parts}
    children = {key: [] for key in by_id}
    for p in parts:
        for dep in set(p.get('depends_on', [])):
            children[dep].append(p['id'])
    ready = [key for key in by_id if remaining[key] == 0]
    order = []
    while ready:
        order.extend(ready)
        next_ready = []
        for key in ready:
            for child in children[key]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    next_ready.append(child)
        ready = sorted(next_ready, key=index.get)
    if len(order) != len(parts):
        raise ValueError('装配依赖存在循环，无法生成步骤')
    return order


def analyze(project):
    order = validate(project)
    parts = project['parts']
    by_id = {p['id']: p for p in parts}
    depths, layers = {}, []
    dependents = {key: [] for key in order}
    for key in order:
        deps = set(by_id[key].get('depends_on', []))
        depth = max((depths[d] + 1 for d in deps), default=0)
        depths[key] = depth
        if len(layers) <= depth:
            layers.append([])
        layers[depth].append(key)
        for dep in deps:
            dependents[dep].append(key)
    meshes = {p['id']: mesh(p) for p in parts}
    boxes = {key: bounds(value) for key,value in meshes.items()}
    collisions = []
    for i, a in enumerate(parts):
        amin,amax = boxes[a['id']]
        for b in parts[i + 1:]:
            bmin,bmax = boxes[b['id']]
            if all(min(amax[j],bmax[j])-max(amin[j],bmin[j]) > 1e-7 for j in range(3)):
                collisions.append([a['id'], b['id']])
    return {'order': order, 'collisions': collisions, 'layers': layers, 'dependents': dependents,
            'meshes': meshes,
            'volume_mm3': sum(math.prod(p['size']) * (math.pi/4 if p.get('shape') == 'cylinder' else 1) for p in parts),
            'note': '旋转后网格的轴对齐包围盒粗检，可能误报；不代表真实相交、强度或制造认证。'}


def demo():
    parts = []
    for n, x, y in [('a', 0, 0), ('b', 560, 0), ('c', 0, 360), ('d', 560, 360)]:
        parts.append(dict(id='leg-' + n, name='桌腿 ' + n.upper(), size=[40, 40, 700],
                          position=[x, y, 0], depends_on=[], material='木材'))
    parts.append(dict(id='top', name='桌面', size=[600, 400, 30], position=[0, 0, 700],
                      depends_on=[p['id'] for p in parts], material='木材'))
    return {'name': '木桌 · 装配示例', 'parts': parts}


def radiator(width=600, height=450, depth=60, fins=24):
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (width, height, depth)):
        raise ValueError('尺寸必须为有限数值')
    if not (100 <= width <= 2000 and 100 <= height <= 2000 and 20 <= depth <= 300):
        raise ValueError('宽高范围 100–2000 mm，深度范围 20–300 mm')
    if type(fins) is not int or not 2 <= fins <= 200:
        raise ValueError('散热片数量范围 2–200')
    parts = []
    def add(key, name, size, position, deps):
        parts.append(dict(id=key, name=name, size=size, position=position,
                          depends_on=deps, material='铝合金'))
    add('bottom', '下水室', [width, depth, 20], [0, 0, 0], [])
    for i in range(fins):
        add(f'fin-{i}', f'散热片 {i+1:03}', [width / fins * .28, depth, height-40],
            [(i+.36)*width/fins, 0, 20], ['bottom'])
    add('top', '上水室', [width, depth, 20], [0, 0, height-20], [f'fin-{i}' for i in range(fins)])
    add('left', '左侧框', [8, depth, height-40], [-8, 0, 20], ['bottom'])
    add('right', '右侧框', [8, depth, height-40], [width, 0, 20], ['bottom'])
    return {'name': '参数化散热器', 'parts': parts}


def stl(project):
    validate(project)
    lines = ['solid assembly']
    for p in project['parts']:
        geometry = mesh(p)
        vertices = geometry['vertices']
        for face in geometry['faces']:
            for i in range(1, len(face)-1):
                tri = [vertices[j] for j in (face[0],face[i],face[i+1])]
                n = normal(*tri)
                lines.extend(['facet normal '+' '.join(str(v) for v in n),' outer loop'])
                lines.extend('  vertex '+' '.join(str(n) for n in point) for point in tri)
                lines.extend([' endloop','endfacet'])
    lines.append('endsolid assembly')
    return '\n'.join(lines)
