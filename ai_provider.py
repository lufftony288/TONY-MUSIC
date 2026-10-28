"""Meshy asynchronous task adapter. No API credentials or signed URLs are persisted."""
import json
import hashlib
import math
import os
import re
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from models import MAX_MODEL_BYTES, save_model

API = 'https://api.meshy.ai'
LOCK = threading.Lock()


class ProviderError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def request_json(path, payload=None):
    key=os.environ.get('MESHY_API_KEY')
    if not key:
        raise ProviderError('请先在环境设置中填写 MESHY_API_KEY 并重启服务')
    data=json.dumps(payload).encode() if payload is not None else None
    request=urllib.request.Request(API+path,data=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=30) as response:
            body=response.read(2_000_001)
        if len(body)>2_000_000:raise ProviderError('生成服务响应过大')
        result=json.loads(body)
        if not isinstance(result,dict):raise ValueError()
        return result
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):raise ProviderError('Meshy 授权或网络访问被拒绝，请检查密钥和 api.meshy.ai 域名权限') from None
        if exc.code==402:raise ProviderError('Meshy 账户额度不足，请在供应商后台充值或检查 API 套餐') from None
        if exc.code==400:raise ProviderError('Meshy 未接受生成参数，请检查描述长度、图片格式和当前 API 版本') from None
        if exc.code==429:raise ProviderError('Meshy 请求额度或频率受限，请稍后重查任务；不要重复提交') from None
        raise ProviderError('Meshy 接口请求失败，请检查服务状态、账户额度和网络配置') from None
    except (urllib.error.URLError,OSError,ValueError):
        raise ProviderError('Meshy 连接或响应异常；若发生于提交阶段，请先在供应商后台核对是否已创建任务，避免重复扣费') from None


def validate_prompt(value):
    if not isinstance(value,dict) or not isinstance(value.get('prompt'),str) or not 1<=len(value['prompt'].strip())<=4000:
        raise ValueError('请输入 1–4000 字符的物体描述')
    image=value.get('image_data_url')
    if image is not None and (not isinstance(image,str) or len(image)>7_000_000 or not re.fullmatch(r'data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+',image)):
        raise ValueError('参考图必须为 PNG、JPEG、WebP 的 base64 data URL，最大约 5MB')
    return image



def mesh_options(value):
    options=value.get('generation_options',{})
    if not isinstance(options,dict) or set(options)-{'mesh_mode','target_polycount'}:
        raise ValueError('生成选项格式或字段无效')
    mode=options.get('mesh_mode','standard')
    if mode not in ('standard','parts','detail'):
        raise ValueError('生成模式无效')
    target=options.get('target_polycount')
    limits={'standard':300000,'parts':15000,'detail':30000}
    defaults={'parts':4000,'detail':15000}
    if target is None:target=defaults.get(mode)
    if target is not None and (type(target) is not int or not 100<=target<=limits[mode]):
        raise ValueError(f'此模式目标面数必须为 100–{limits[mode]} 的整数')
    payload={}
    if mode in ('parts','detail'):
        payload={'model_type':'smart-topology','ai_model':'meshy-t2' if mode=='parts' else 'meshy-t2.5',
                 'topology':'triangle','target_polycount':target}
    elif target is not None:
        payload={'model_type':'standard','should_remesh':True,'topology':'triangle','target_polycount':target}
    return payload,{'mesh_mode':mode,'target_polycount':target}


def submit(connect, value):
    import uuid
    image=validate_prompt(value)
    if not image and len(value['prompt'].strip())>800:
        raise ValueError('Meshy 文字生成描述最多 800 字符；图片模式描述只用于任务命名')
    extra,options=mesh_options(value)
    kind='image' if image else 'text'
    path='/openapi/v1/image-to-3d' if image else '/openapi/v2/text-to-3d'
    payload={'image_url':image,'should_texture':False} if image else {'mode':'preview','prompt':value['prompt'].strip()}
    payload.update(extra)
    request_id=value.get('client_request_id')
    if request_id is not None:
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id):
            raise ValueError('客户端请求编号无效')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with connect() as con:
            inserted=con.execute('INSERT OR IGNORE INTO generation_submissions (id) VALUES (?)',(request_id,)).rowcount
            previous=con.execute('SELECT job_id,error FROM generation_submissions WHERE id=?',(request_id,)).fetchone()
            if inserted:
                con.execute('INSERT INTO generation_submission_inputs VALUES (?,?)',(request_id,digest))
            else:
                prior_digest=con.execute('SELECT digest FROM generation_submission_inputs WHERE id=?',(request_id,)).fetchone()
                if prior_digest and prior_digest[0]!=digest:
                    raise ProviderError('描述、参考图或生成选项已改变，请先核对旧任务，再点击“开始新的生成请求”；不会返回或重新收费生成旧内容')
        if not inserted:
            if previous[0]:return get_job(connect,previous[0])
            raise ProviderError(previous[1] or '此请求正在提交或结果尚未确认，请先检查任务记录及 Meshy 后台；不会重复创建收费任务')
    try:
        response=request_json(path,payload)
        remote_id=response.get('result')
        if not isinstance(remote_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',remote_id):
            raise ProviderError('Meshy 未返回有效任务编号，请先核对供应商后台，避免重复提交')
        key=uuid.uuid4().hex
        # Do not persist reference images, full prompts, credentials or signed result URLs.
        with connect() as con:
            con.execute('INSERT INTO generation_jobs (id,remote_id,kind,name,status,progress) VALUES (?,?,?,?,?,?)',
                        (key,remote_id,kind,'Meshy · '+value['prompt'].strip()[:60],'PENDING',0))
            con.execute('INSERT INTO generation_job_options (job_id,options) VALUES (?,?)',(key,json.dumps(options)))
            if request_id:
                con.execute('UPDATE generation_submissions SET job_id=? WHERE id=?',(key,request_id))
        return get_job(connect,key)
    except ProviderError as exc:
        if request_id:
            with connect() as con:
                con.execute('UPDATE generation_submissions SET error=? WHERE id=?',(str(exc),request_id))
        raise


def get_job(connect,key):
    with connect() as con:
        row=con.execute('SELECT id,kind,name,status,progress,asset_id,error,created_at FROM generation_jobs WHERE id=?',(key,)).fetchone()
    if not row:return None
    with connect() as con:
        saved=con.execute('SELECT options FROM generation_job_options WHERE job_id=?',(key,)).fetchone()
    result=dict(zip(('id','kind','name','status','progress','asset_id','error','created_at'),row))
    result['generation_options']=json.loads(saved[0]) if saved else None
    if result['asset_id']:
        with connect() as con:
            asset=con.execute('SELECT id,name,extension,bytes FROM models WHERE id=?',(result['asset_id'],)).fetchone()
        if asset:result['asset']=dict(zip(('id','name','extension','bytes'),asset))
    return result


def list_jobs(connect):
    with connect() as con:
        keys=con.execute('SELECT id FROM generation_jobs ORDER BY rowid DESC LIMIT 50').fetchall()
    return [get_job(connect,key[0]) for key in keys]


def download_glb(url):
    try:
        parsed=urllib.parse.urlsplit(url) if isinstance(url,str) else None
        port=parsed.port if parsed else None
    except ValueError:
        raise ProviderError('模型下载地址格式无效') from None
    # Only accept the provider's exact asset host, and never forward the API token.
    if not parsed or parsed.scheme!='https' or parsed.hostname!='assets.meshy.ai' or parsed.username or parsed.password or port not in (None,443):
        raise ProviderError('模型下载地址不在已支持的 assets.meshy.ai 域名，请核对供应商返回地址')
    try:
        request=urllib.request.Request(url,headers={'Accept':'model/gltf-binary'})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=45) as response:
            return response.read(MAX_MODEL_BYTES+1)
    except (urllib.error.URLError,OSError):
        raise ProviderError('模型已生成，但下载失败；请检查 assets.meshy.ai 网络权限后重查任务') from None


def poll(connect,key):
    if not LOCK.acquire(blocking=False):
        return get_job(connect,key)
    try:
        with connect() as con:
            row=con.execute('SELECT remote_id,kind,status,last_checked FROM generation_jobs WHERE id=?',(key,)).fetchone()
        if not row:return None
        remote_id,kind,state,last=row
        if state in ('SUCCEEDED','FAILED','CANCELED') or time.time()-last<3:return get_job(connect,key)
        try:
            path=('/openapi/v1/image-to-3d/' if kind=='image' else '/openapi/v2/text-to-3d/')+remote_id
            response=request_json(path)
            state=response.get('status')
            if state not in ('PENDING','IN_PROGRESS','SUCCEEDED','FAILED','CANCELED'):
                raise ProviderError('Meshy 返回未知任务状态，请稍后重查')
            progress=response.get('progress',0)
            if type(progress) not in (int,float) or not math.isfinite(progress):progress=0
            progress=max(0,min(100,progress))
            asset_id=None
            error='生成任务失败或取消，请在 Meshy 后台检查原因' if state in ('FAILED','CANCELED') else None
            if state=='SUCCEEDED':
                urls=response.get('model_urls')
                if not isinstance(urls,dict) or not urls.get('glb'):raise ProviderError('任务完成但未返回 GLB 文件，请核对供应商结果')
                data=download_glb(urls['glb'])
                try:asset=save_model(connect,'meshy-'+key[:8]+'.glb',data)
                except ValueError:raise ProviderError('生成结果不是支持的内嵌 GLB，或超过 50MB；请在供应商后台导出普通 GLB') from None
                asset_id=asset['id'];progress=100
            with connect() as con:
                con.execute('UPDATE generation_jobs SET status=?,progress=?,asset_id=?,error=?,last_checked=? WHERE id=?',
                            (state,progress,asset_id,error,time.time(),key))
        except ProviderError as exc:
            with connect() as con:
                con.execute('UPDATE generation_jobs SET error=?,last_checked=? WHERE id=?',(str(exc),time.time(),key))
        return get_job(connect,key)
    finally:LOCK.release()
