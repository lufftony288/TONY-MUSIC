import os
os.environ["MESHY_API_KEY"]=""
os.environ["MODEL_GENERATOR_PROVIDER"]="meshy"
"""Actual STEP assembly upload, native conversion and WebGL preview regression."""
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import server
from step_fixtures import step_fixture
from models import validate_model

class Quiet(server.Handler):
    def log_message(self,*args):pass

source=step_fixture()
with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'):
    http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1500,'height':1050});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{http.server_port}'
            page.goto(base);page.click('#open-models')
            for name in ['assembly.step','Assembly.STP']:
                page.locator('#model-file').set_input_files({'name':name,'mimeType':'application/step','buffer':source})
                page.wait_for_function("name=>document.querySelector('#model-title').textContent===name",arg=name)
                page.wait_for_function("document.querySelector('#status').textContent.includes('STEP 已转换并加载')")
                assert page.locator('#model-count').inner_text()=='2 网格'
                assert '24 个三角面' in page.locator('#model-stats').inner_text()
                assert 'Fixture assembly' in page.locator('#model-tree').inner_text()
                assert 'Frame' in page.locator('#model-tree').inner_text()
                assert '0.25' in page.locator('#model-bounds').inner_text()
                assert ' m' in page.locator('#model-bounds').inner_text()
                with page.expect_download() as download:page.click('#download-model')
                destination=Path(folder)/name;download.value.save_as(destination)
                assert destination.read_bytes()==source,'Original STEP must be preserved byte-for-byte'
                with page.expect_download() as download:page.click('#download-preview')
                preview=Path(folder)/(name+'.glb');download.value.save_as(preview)
                assert validate_model('preview.glb',preview.read_bytes())=='.glb'
            page.locator('#model-tree').get_by_role('button',name='◇ Right block',exact=True).click()
            page.click('#isolate-model')
            left=page.locator('#model-tree .model-tree-row').filter(has=page.get_by_role('button',name='◇ Left block',exact=True))
            assert not left.locator('input').is_checked()
            page.click('#show-all-model');assert left.locator('input').is_checked()
            page.reload();page.click('#tab-models')
            page.locator('#model-library button').filter(has_text='assembly.step').click()
            page.wait_for_function("document.querySelector('#model-title').textContent==='assembly.step'")
            assert page.locator('#model-count').inner_text()=='2 网格'
            before=page.locator('#model-canvas canvas').screenshot()
            rect=page.locator('#model-canvas canvas').bounding_box();x=rect['x']+rect['width']*.5;y=rect['y']+rect['height']*.5
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+80,y+25,steps=10);page.mouse.up()
            assert page.locator('#model-canvas canvas').screenshot()!=before
            page.locator('#model-file').set_input_files({'name':'broken.step','mimeType':'application/step','buffer':b'ISO-10303-21; HEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;'})
            page.wait_for_function("document.querySelector('#status').textContent.includes('失败')")
            assert page.locator('#model-library button').count()==2
            assert page.locator('#model-title').inner_text()=='assembly.step'
            page.screenshot(path='/tmp/form-step-preview.png',full_page=True)
            assert not errors,errors
            browser.close()
        print('PASS: STEP/STP native conversion, nested names and instances, correct metre scale, original/GLB downloads, tree isolation, reload, rendered orbit and malformed-file protection; no JS errors')
    finally:http.shutdown();http.server_close()
