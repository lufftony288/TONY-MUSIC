"""Real B-rep API/UI regression; isolated library, no provider calls."""
import os
os.environ['MESHY_API_KEY']='';os.environ['MODEL_GENERATOR_PROVIDER']='meshy'
from pathlib import Path
import hashlib,json,sys,tempfile,threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server
from step_fixtures import step_fixture
from model_fixtures import STL
class Quiet(server.Handler):
    def log_message(self,*args):pass
source=step_fixture()
with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'):
    http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet);threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1600,'height':1100});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{http.server_port}';page.goto(base);page.click('#open-models')
            assert page.locator('#cad-scan').is_disabled()
            page.locator('#model-file').set_input_files({'name':'precision.step','mimeType':'application/step','buffer':source})
            page.wait_for_function("document.querySelector('#model-title').textContent==='precision.step'")
            page.click('#cad-scan')
            page.wait_for_function("document.querySelector('#cad-summary').textContent.includes('2 个封闭实体')")
            assert '250,000' in page.locator('#cad-summary').inner_text()
            assert 'Left block' in page.locator('#cad-body-a').inner_text()
            assert 'Right block' in page.locator('#cad-body-b').inner_text()
            page.click('#cad-compare')
            page.wait_for_function("document.querySelector('#cad-result').dataset.gapMm==='50'")
            assert page.locator('#cad-result').get_attribute('data-overlap-mm3')=='0'
            page.locator('#model-explosion').fill('70');page.locator('#model-explosion').dispatch_event('input')
            page.click('#cad-compare')
            page.wait_for_function("document.querySelector('#cad-result').dataset.gapMm==='50'")
            with page.expect_download() as download:page.click('#cad-export')
            target=Path(folder)/'cad.json';download.value.save_as(target);report=json.loads(target.read_text())
            assert report['source_sha256']==hashlib.sha256(source).hexdigest()
            assert report['pair']['minimum_distance_mm']==50
            # Changing selection must invalidate displayed pair values and export results.
            page.select_option('#cad-body-b','solid-0001')
            assert page.locator('#cad-compare').is_disabled()
            assert page.locator('#cad-result').get_attribute('data-gap-mm') is None
            with page.expect_download() as download:page.click('#cad-export')
            download.value.save_as(target);assert 'pair' not in json.loads(target.read_text())
            assets=page.request.get(base+'/api/models').json();key=assets[0]['id']
            assert page.request.post(base+f'/api/models/{key}/cad-inspect',data={'a':'solid-0001'}).status==400
            assert page.request.get(base+f'/api/models/{key}/download').body()==source
            assert page.request.post(base+'/api/models/'+'0'*32+'/cad-inspect',data={}).status==404
            page.select_option('#cad-body-b','solid-0002');page.click('#cad-compare')
            page.wait_for_function("document.querySelector('#cad-result').dataset.gapMm==='50'")
            page.screenshot(path='/tmp/form-brep-inspection.png',full_page=True)
            page.locator('#model-file').set_input_files({'name':'triangle.stl','mimeType':'model/stl','buffer':STL})
            page.wait_for_function("document.querySelector('#model-title').textContent==='triangle.stl'")
            assert page.locator('#cad-scan').is_disabled()
            assert not page.locator('#cad-pair-controls').is_visible()
            key=next(a['id'] for a in page.request.get(base+'/api/models').json() if a['extension']=='.stl')
            assert page.request.post(base+f'/api/models/{key}/cad-inspect',data={}).status==415
            assert not errors,errors
            browser.close()
        print('PASS: STEP B-rep scan, volumes/validity, 50mm exact gap, zero interference, explosion invariance, JSON/hash, selection invalidation, original preservation and non-STEP rejection; no JS errors')
    finally:http.shutdown();http.server_close()
