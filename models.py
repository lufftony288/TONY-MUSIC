"""Local model assets and the explicit custom-generation adapter contract."""
import json
import os
from pathlib import Path
import struct
import uuid
import re

STEP_EXTENSIONS = ('.step', '.stp')

MAX_MODEL_BYTES = 50 * 1024 * 1024


def validate_model(name, data):
    if not isinstance(name, str) or len(name) > 240 or not name.strip():
        raise ValueError('模型文件名无效')
    suffix = Path(name).suffix.lower()
    if suffix not in ('.glb', '.obj', '.stl', *STEP_EXTENSIONS):
        raise ValueError('仅支持 GLB、OBJ、STL、STEP/STP')
    if not data or len(data) > MAX_MODEL_BYTES:
        raise ValueError('模型大小必须在 1 字节到 50MB 之间')
    if suffix in STEP_EXTENSIONS:
        source = data.removeprefix(b'\xef\xbb\xbf').strip()
        if not source.startswith(b'ISO-10303-21;') or not re.search(rb'END-ISO-10303-21\s*;\s*$', source):
            raise ValueError('STEP 文件头或结束标记无效，请导出完整的 ISO-10303-21 文件')
    elif suffix == '.glb':
        if len(data) < 20:
            raise ValueError('GLB 文件不完整')
        magic,version,length,chunk_length,chunk_type = struct.unpack_from('<5I', data)
        if magic != 0x46546C67 or version != 2 or length != len(data) or chunk_type != 0x4E4F534A or chunk_length % 4 or chunk_length > length-20:
            raise ValueError('无效的 GLB 2.0 文件头或 JSON 块')
        try:
            document = json.loads(data[20:20+chunk_length])
        except (ValueError, UnicodeError):
            raise ValueError('GLB JSON 块无效') from None
        if not isinstance(document, dict) or not isinstance(document.get('asset'), dict) or document['asset'].get('version') != '2.0':
            raise ValueError('GLB 资源版本必须为 2.0')
        for field in ('buffers','images'):
            items = document.get(field,[])
            if not isinstance(items,list):
                raise ValueError('GLB 资源列表无效')
            for item in items:
                if not isinstance(item,dict):
                    raise ValueError('GLB 资源记录无效')
                uri = item.get('uri')
                if uri is not None and (not isinstance(uri,str) or not uri.startswith('data:')):
                    raise ValueError('GLB 必须内嵌资源，不支持外部文件或 URL')
        accessors = document.get('accessors',[])
        nodes = document.get('nodes',[])
        if not isinstance(accessors,list) or not isinstance(nodes,list) or len(nodes)>10000:
            raise ValueError('GLB 节点或访问器列表无效')
        for accessor in accessors:
            if not isinstance(accessor,dict) or type(accessor.get('count')) is not int or not 0 <= accessor['count'] <= 3_000_000:
                raise ValueError('GLB 访问器大小无效或超过上限')
        offset = 20 + chunk_length
        while offset < length:
            if offset + 8 > length:
                raise ValueError('GLB 块不完整')
            size = struct.unpack_from('<I',data,offset)[0]
            if size % 4 or offset + 8 + size > length:
                raise ValueError('GLB 块长度无效')
            offset += 8 + size
    elif suffix == '.stl':
        binary = len(data) >= 84 and 84 + struct.unpack_from('<I',data,80)[0] * 50 == len(data)
        if not binary:
            try:
                text = data.decode('ascii').strip()
            except UnicodeError:
                raise ValueError('STL 二进制长度或文本编码无效') from None
            if not text.startswith('solid') or 'facet normal' not in text or 'endsolid' not in text:
                raise ValueError('无效的 STL 文件')
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError:
            raise ValueError('OBJ 请使用 UTF-8 文本编码') from None
        lines = text.splitlines()
        if not any(line.lstrip().startswith('v ') for line in lines) or not any(line.lstrip().startswith('f ') for line in lines):
            raise ValueError('OBJ 缺少顶点或面')
    return suffix


def save_model(connect, name, data):
    suffix = validate_model(name, data)
    preview = None
    if suffix in STEP_EXTENSIONS:
        from step_import import convert_step
        preview = convert_step(data)
        validate_model('preview.glb', preview)
    # UUID filenames prevent path traversal and never overwrite a prior model.
    key = uuid.uuid4().hex
    with connect() as con:
        db_file = Path(con.execute('PRAGMA database_list').fetchone()[2])
        folder = db_file.parent / 'models'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (key + suffix)
        path.write_bytes(data)
        preview_path = folder / (key + '.preview.glb')
        try:
            if preview is not None:
                preview_path.write_bytes(preview)
            con.execute('INSERT INTO models (id,name,extension,bytes) VALUES (?,?,?,?)',
                        (key,Path(name.replace('\\','/')).name,suffix,len(data)))
        except Exception:
            path.unlink(missing_ok=True)
            preview_path.unlink(missing_ok=True)
            raise
    return model_info({'id':key, 'name':Path(name.replace('\\','/')).name, 'extension':suffix,'bytes':len(data)})


def model_info(asset):
    if asset['extension'] in STEP_EXTENSIONS:
        return dict(asset, preview_extension='.glb', preview_units='m', up_axis='Z')
    return asset


def generator_config():
    # Expose readiness flags only; no credential or endpoint values.
    provider=os.environ.get('MODEL_GENERATOR_PROVIDER') or ('custom' if os.environ.get('MODEL_GENERATOR_URL') else 'meshy')
    if provider=='meshy':
        return {'configured':bool(os.environ.get('MESHY_API_KEY')), 'adapter':'meshy',
                'supports_image':True,'async':True,'supports_mesh_options':True,'text_prompt_limit':800,
                'note':'Meshy 文字/图片转三维；需配置 MESHY_API_KEY，实际生成消耗供应商账户额度。'}
    return {'configured':bool(os.environ.get('MODEL_GENERATOR_URL')) and provider=='custom',
            'adapter':'form-glb-v1','supports_image':True,'async':False,
            'note':'自定义接口需按文档返回 GLB 2.0。'}
