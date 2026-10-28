"""Mocked provider verifies strategy UI/payloads/history; no paid inference."""
import os,base64,json,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server,ai_provider
from playwright.sync_api import sync_playwright
from model_fixtures import glb
class Quiet(server.Handler):
    def log_message(self,*args):pass
with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'),patch.dict(os.environ,{'MODEL_GENERATOR_PROVIDER':'meshy','MESHY_API_KEY':'test-only-not-real'}):
    submissions=[]
    def provider(path,payload=None):
        if payload is not None:submissions.append((path,payload));return {'result':'remote-'+str(len(submissions))}
        return {'status':'SUCCEEDED','progress':100,'model_urls':{'glb':'https://assets.meshy.ai/mock.glb'}}
    with patch.object(ai_provider,'request_json',side_effect=provider),patch.object(ai_provider,'download_glb',return_value=glb()),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No real upstream in browser test')):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet);threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
                page=browser.new_page(viewport={'width':1600,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                base=f'http://127.0.0.1:{http.server_port}';page.goto(base);page.click('#open-models')
                page.wait_for_function("!document.querySelector('#generation-options').hidden")
                assert page.locator('#model-prompt').get_attribute('maxlength')=='800'
                page.select_option('#generation-mesh-mode','parts')
                assert page.locator('#generation-polycount').get_attribute('max')=='15000'
                page.fill('#model-prompt','A mechanical bracket with separate base and cover')
                page.fill('#generation-polycount','15001');page.click('#ai-model-submit')
                assert not page.locator('#generation-polycount').evaluate('el=>el.checkValidity()')
                assert not submissions
                page.fill('#generation-polycount','6000');page.click('#ai-model-submit')
                page.wait_for_function("document.querySelector('#generation-model-summary').textContent.includes('6,000')||document.querySelector('#generation-model-summary').textContent.includes('6000')")
                assert len(submissions)==1
                assert submissions[0][1]['ai_model']=='meshy-t2'
                assert submissions[0][1]['target_polycount']==6000
                assert '2 个网格节点' in page.locator('#generation-model-summary').inner_text()
                assert '不等于机械零件' in page.locator('#generation-model-summary').inner_text()
                page.reload();page.click('#tab-models')
                page.locator('#generation-jobs').evaluate("el=>el.closest('details').open=true")
                page.locator('#generation-jobs button').click()
                page.wait_for_function("document.querySelector('#generation-model-summary').textContent.includes('T2 分件优先')")
                assert page.locator('#generation-mesh-mode').input_value()=='standard'
                assert len(submissions)==1,'History reopens must not create jobs'
                # Image mode uses T2.5 options but does not send the local label as a prompt.
                image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE2sAAAAASUVORK5CYII=')
                page.locator('#model-image').set_input_files({'name':'reference.png','mimeType':'image/png','buffer':image})
                assert page.locator('#model-prompt').get_attribute('maxlength')=='4000'
                page.select_option('#generation-mesh-mode','detail');page.fill('#generation-polycount','25000')
                page.fill('#model-prompt','Image task label');page.click('#ai-model-submit')
                page.wait_for_function("document.querySelector('#generation-model-summary').textContent.includes('T2.5')")
                assert len(submissions)==2
                assert submissions[1][0]=='/openapi/v1/image-to-3d'
                assert submissions[1][1]['ai_model']=='meshy-t2.5' and 'prompt' not in submissions[1][1]
                jobs=page.request.get(base+'/api/generation-jobs').json()
                assert jobs[0]['generation_options']=={'mesh_mode':'detail','target_polycount':25000}
                # Standard with blank count keeps provider defaults, preserving old integration semantics.
                page.locator('#model-image').set_input_files([]);page.select_option('#generation-mesh-mode','standard');page.fill('#generation-polycount','')
                page.fill('#model-prompt','Simple object');page.click('#ai-model-submit')
                page.wait_for_function("document.querySelector('#generation-model-summary').textContent.includes('标准几何')")
                assert len(submissions)==3
                assert submissions[2][1]=={'mode':'preview','prompt':'Simple object'}
                assert not errors,errors
                browser.close()
            print('PASS: target bounds, T2 text payload, T2.5 image payload, history snapshot, actual-node summary, default compatibility; all provider calls mocked')
        finally:http.shutdown();http.server_close()
