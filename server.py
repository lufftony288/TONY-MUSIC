"""Local engineering workspace; STEP preview uses the optional Open Cascade runtime."""
import argparse
import json
import sqlite3
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from engine import analyze, demo, radiator, stl
from models import MAX_MODEL_BYTES, save_model, generator_config, model_info, STEP_EXTENSIONS
from step_import import StepUnavailable
import ai_provider
from cad_inspect import inspect_step

ROOT = Path(__file__).parent
DB = ROOT / '.data' / 'projects.sqlite3'


def connect():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, body TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, name TEXT NOT NULL, extension TEXT NOT NULL, bytes INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    con.execute('CREATE TABLE IF NOT EXISTS generation_jobs (id TEXT PRIMARY KEY, remote_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, asset_id TEXT, error TEXT, last_checked REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    con.execute('CREATE TABLE IF NOT EXISTS generation_submissions (id TEXT PRIMARY KEY, job_id TEXT, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    con.execute('CREATE TABLE IF NOT EXISTS generation_submission_inputs (id TEXT PRIMARY KEY, digest TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS generation_job_options (job_id TEXT PRIMARY KEY, options TEXT NOT NULL)')
    return con


class Handler(BaseHTTPRequestHandler):
    def binary(self, status, data, kind, download=None):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if download:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        self.wfile.write(data)

    def reply(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/api/generation-jobs':
            return self.reply(200,ai_provider.list_jobs(connect))
        job_match = re.fullmatch(r'/api/generation-jobs/([a-f0-9]{32})',self.path)
        if job_match:
            job=ai_provider.poll(connect,job_match[1])
            return self.reply(200,job) if job else self.reply(404,{'error':'任务不存在'})
        if self.path == '/api/model-generation':
            return self.reply(200, generator_config())
        if self.path == '/api/models':
            with connect() as con:
                rows = con.execute('SELECT id,name,extension,bytes,created_at FROM models ORDER BY created_at DESC, rowid DESC').fetchall()
            return self.reply(200, [model_info(dict(zip(('id','name','extension','bytes','created_at'),row))) for row in rows])
        match = re.fullmatch(r'/api/models/([a-f0-9]{32})/(content|download|preview-download)',self.path)
        if match:
            key, mode = match.groups()
            with connect() as con:
                row = con.execute('SELECT name,extension FROM models WHERE id=?',(key,)).fetchone()
            if not row:
                return self.reply(404, {'error':'模型不存在'})
            path = DB.parent / 'models' / (key + row[1])
            extension = row[1]
            filename = row[0]
            if mode != 'download' and extension in STEP_EXTENSIONS:
                path = DB.parent / 'models' / (key + '.preview.glb')
                extension = '.glb'
                filename = Path(row[0]).stem + '.glb'
            if not path.is_file():
                return self.reply(404, {'error':'模型文件缺失'})
            kinds = {'.glb':'model/gltf-binary','.obj':'text/plain; charset=utf-8','.stl':'model/stl', '.step':'application/step', '.stp':'application/step'}
            return self.binary(200,path.read_bytes(),kinds[extension],filename if mode != 'content' else None)
        vendor = {
            '/vendor/three.module.js':'build/three.module.js',
            '/vendor/three.core.js':'build/three.core.js',
            '/vendor/addons/controls/OrbitControls.js':'examples/jsm/controls/OrbitControls.js',
            '/vendor/addons/loaders/GLTFLoader.js':'examples/jsm/loaders/GLTFLoader.js',
            '/vendor/addons/loaders/OBJLoader.js':'examples/jsm/loaders/OBJLoader.js',
            '/vendor/addons/loaders/STLLoader.js':'examples/jsm/loaders/STLLoader.js',
            '/vendor/addons/utils/BufferGeometryUtils.js':'examples/jsm/utils/BufferGeometryUtils.js',
        }
        if self.path in vendor:
            path = ROOT / 'node_modules' / 'three' / vendor[self.path]
            if not path.is_file():
                return self.reply(503, {'error':'缺少三维依赖，请执行 npm ci --ignore-scripts'})
            return self.binary(200,path.read_bytes(),'text/javascript; charset=utf-8')
        if self.path == '/api/history':
            with connect() as con:
                rows = con.execute('SELECT id, created_at, body FROM revisions ORDER BY id DESC LIMIT 100').fetchall()
            return self.reply(200, [{'id': key, 'created_at': timestamp + 'Z',
                                     'name': json.loads(body)['name']} for key,timestamp,body in rows])
        if self.path.startswith('/api/history/'):
            try:
                key = int(self.path.rsplit('/', 1)[-1])
            except ValueError:
                return self.reply(400, {'error': '版本编号无效'})
            with connect() as con:
                row = con.execute('SELECT body FROM revisions WHERE id=?', (key,)).fetchone()
            return self.reply(200, json.loads(row[0])) if row else self.reply(404, {'error': '版本不存在'})
        if self.path == '/api/health':
            return self.reply(200, {'status': 'ok'})
        if self.path == '/api/project':
            with connect() as con:
                row = con.execute('SELECT body FROM projects WHERE id=1').fetchone()
            return self.reply(200, json.loads(row[0]) if row else demo())
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                 '/style.css': ('style.css', 'text/css'), '/viewer.js': ('viewer.js','text/javascript')}
        if self.path not in files:
            return self.reply(404, {'error': 'Not found'})
        name, kind = files[self.path]
        data = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        cad_match=re.fullmatch(r'/api/models/([a-f0-9]{32})/cad-inspect',self.path)
        if not cad_match and self.path not in ('/api/analyze', '/api/project', '/api/generate', '/api/stl', '/api/models', '/api/model-generation'):
            return self.reply(404, {'error': 'Not found'})
        # Local service: disallow browser requests from other origins.
        origin = self.headers.get('Origin')
        allowed_origins = {'http://' + self.headers.get('Host', '')}
        public_origin = os.environ.get('FORM_PUBLIC_ORIGIN', '').rstrip('/')
        if public_origin:
            allowed_origins.add(public_origin)
        if origin and origin not in allowed_origins:
            return self.reply(403, {'error': 'Origin rejected'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = MAX_MODEL_BYTES if self.path == '/api/models' else 8_000_000 if self.path == '/api/model-generation' else 2_000_000
            if not 0 < length <= limit:
                raise ValueError('请求为空或超过该接口大小上限')
            if self.path == '/api/models':
                name = urllib.parse.unquote(self.headers.get('X-Model-Name',''))
                return self.reply(201,save_model(connect,name,self.rfile.read(length)))
            project = json.loads(self.rfile.read(length))
            if cad_match:
                key=cad_match[1]
                with connect() as con:
                    row=con.execute('SELECT extension FROM models WHERE id=?',(key,)).fetchone()
                if not row:return self.reply(404,{'error':'模型不存在'})
                if row[0] not in STEP_EXTENSIONS:return self.reply(415,{'error':'B-rep 检查仅适用于原始 STEP，不适用于 GLB/STL/OBJ 网格'})
                path=DB.parent/'models'/(key+row[0])
                if not path.is_file():return self.reply(404,{'error':'原始 STEP 文件缺失'})
                return self.reply(200,inspect_step(path.read_bytes(),project))
            if self.path == '/api/model-generation':
                return self.generate_model(project)
            if self.path == '/api/generate':
                if not isinstance(project, dict):
                    raise ValueError('参数必须为对象')
                return self.reply(200, radiator(project.get('width',600), project.get('height',450),
                                                project.get('depth',60), project.get('fins',24)))
            if self.path == '/api/stl':
                return self.reply(200, {'stl': stl(project)})
            report = analyze(project)
            if self.path == '/api/project':
                with connect() as con:
                    previous = con.execute('SELECT body FROM projects WHERE id=1').fetchone()
                    body = json.dumps(project, ensure_ascii=False)
                    if previous and not con.execute('SELECT 1 FROM revisions LIMIT 1').fetchone():
                        con.execute('INSERT INTO revisions (body) VALUES (?)', (previous[0],))
                    if not previous or json.loads(previous[0]) != project:
                        con.execute('INSERT INTO revisions (body) VALUES (?)', (body,))
                    con.execute('INSERT OR REPLACE INTO projects VALUES (1, ?)',
                                (body,))
            self.reply(200, report)
        except StepUnavailable as exc:
            self.reply(503, {'error': str(exc)})
        except (ValueError, TypeError, OverflowError) as exc:
            self.reply(400, {'error': str(exc)})

    def generate_model(self, request):
        if generator_config()['adapter']=='meshy':
            if not generator_config()['configured']:
                return self.reply(503,{'error':'尚未配置 Meshy。请在环境设置中安全填写 MESHY_API_KEY 并重启服务。'})
            try:
                return self.reply(202,ai_provider.submit(connect,request))
            except ai_provider.ProviderError as exc:
                return self.reply(502,{'error':str(exc)})
        endpoint = os.environ.get('MODEL_GENERATOR_URL','')
        if not endpoint:
            return self.reply(503, {'error':'未配置生成服务。请参照 docs/MODEL_GENERATION.md 配置接口。'})
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return self.reply(503, {'error':'生成服务必须配置无嵌入凭据的 HTTPS 地址'})
        if not isinstance(request,dict) or not isinstance(request.get('prompt'),str) or not 1 <= len(request['prompt'].strip()) <= 4000:
            raise ValueError('请输入 1–4000 字符的描述')
        image = request.get('image_data_url')
        if image is not None and (not isinstance(image,str) or len(image)>7_000_000 or not re.fullmatch(r'data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+',image)):
            raise ValueError('参考图仅支持 PNG、JPEG、WebP 的 base64 data URL，最长 7MB')
        payload = {'prompt':request['prompt'],'image_data_url':image,'format':'glb'}
        headers = {'Content-Type':'application/json','Accept':'model/gltf-binary'}
        key = os.environ.get('MODEL_GENERATOR_KEY')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        upstream = urllib.request.Request(endpoint,data=json.dumps(payload).encode(),headers=headers)
        # Do not follow redirects: a provider redirect must not forward credentials elsewhere.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect()).open(upstream,timeout=55) as response:
                data = response.read(MAX_MODEL_BYTES+1)
            model = save_model(connect,'generated.glb',data)
            return self.reply(201,model)
        except (urllib.error.URLError,TimeoutError,OSError):
            return self.reply(502, {'error':'生成服务请求失败；请检查地址、授权、网络策略及服务状态。详细远端响应不会写入日志。'})
        except ValueError:
            return self.reply(502, {'error':'生成服务返回的内容不是受支持的内嵌 GLB 2.0，或超过 50MB 上限。'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
