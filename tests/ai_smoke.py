"""Local browser flow with simulated Meshy upstream; never performs paid inference."""
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server
import ai_provider
from model_fixtures import glb

class Quiet(server.Handler):
    def log_message(self,*args):pass

with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'),patch.dict(os.environ,{'MODEL_GENERATOR_PROVIDER':'meshy','MESHY_API_KEY':'test-only-not-a-real-key'}):
    submitted=[];checks=[]
    def upstream(path,payload=None):
        if payload is not None:
            submitted.append((path,payload));return {'result':'remote-test'}
        checks.append(path)
        return {'status':'IN_PROGRESS','progress':35} if len(checks)==1 else {'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/test.glb'}}
    with patch.object(ai_provider,'request_json',side_effect=upstream),patch.object(ai_provider,'download_glb',return_value=glb()):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
                page=browser.new_page(viewport={'width':1500,'height':1050});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{http.server_port}')
                page.click('#open-models')
                page.wait_for_function("!document.querySelector('#ai-model-submit').disabled")
                page.fill('#model-prompt','A two-part engineering assembly')
                page.click('#ai-model-submit')
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('35%')")
                assert page.locator('#ai-model-submit').is_disabled()
                interrupted=[]
                def transient(route):
                    interrupted.append(route.request.url)
                    if len(interrupted)<=2:
                        route.fulfill(status=503,content_type='application/json',body='{"error":"temporary test outage"}')
                    else:route.continue_()
                page.route('**/api/generation-jobs/*',transient)
                page.reload();page.click('#tab-models')
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('暂时中断')")
                assert page.locator('#ai-model-submit').is_disabled()
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('100%')",timeout=30000)
                assert len(interrupted)>=3
                page.unroute('**/api/generation-jobs/*',transient)
                page.wait_for_function("document.querySelector('#model-count').textContent==='2 网格'")
                assert len(submitted)==1,'Reload must not submit a second paid request'
                assert page.locator('#model-library button').count()==1
                page.wait_for_function("document.querySelector('#generation-jobs').textContent.includes('SUCCEEDED')")
                page.reload();page.click('#tab-models')
                page.wait_for_function("document.querySelector('#generation-jobs').textContent.includes('SUCCEEDED')")
                page.locator('#generation-jobs').evaluate("el=>el.closest('details').open=true")
                page.locator('#generation-jobs button').click()
                page.wait_for_function("document.querySelector('#model-count').textContent==='2 网格'")
                assert len(submitted)==1
                # Permanent failures stop immediately; transient failures exhaust a bounded retry budget.
                failed=[]
                def permanent(route):
                    failed.append(1);route.fulfill(status=404,content_type='application/json',body='{"error":"not found"}')
                page.route('**/api/generation-jobs/*',permanent)
                page.locator('#generation-jobs button').click()
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('已暂停')")
                assert len(failed)==1
                assert not page.locator('#ai-model-submit').is_disabled()
                page.unroute('**/api/generation-jobs/*',permanent)
                failed.clear()
                def unavailable(route):
                    failed.append(1);route.fulfill(status=503,content_type='application/json',body='{"error":"offline"}')
                page.route('**/api/generation-jobs/*',unavailable)
                page.locator('#generation-jobs button').click()
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('暂时中断')")
                page.wait_for_function("document.querySelector('#generation-state').textContent.includes('已暂停')",timeout=25000)
                assert len(failed)==4
                assert len(submitted)==1
                assert not errors,errors
                browser.close()
            print('PASS: simulated Meshy submit, progress, transient query recovery, permanent failure, bounded retries, reload resume, GLB library/render, history reopen; one submission only; no live inference')
        finally:http.shutdown();http.server_close()
