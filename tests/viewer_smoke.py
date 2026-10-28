import os
os.environ["MESHY_API_KEY"]=""
os.environ["MODEL_GENERATOR_PROVIDER"]="meshy"
"""WebGL/upload integration using a disposable library, no user project changes."""
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server
from model_fixtures import glb,OBJ,STL,BINARY_STL

class QuietHandler(server.Handler):
    def log_message(self,*args):pass

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'db.sqlite3'
    http=server.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{http.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1500,'height':1050})
            errors=[];external=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base) and not r.url.startswith(('data:','blob:')) else None)
            page.goto(base)
            page.wait_for_function("document.querySelector('#status').textContent.includes('已就绪')")
            page.click('#open-models')
            page.wait_for_selector('#model-canvas canvas')
            page.wait_for_function("document.querySelector('#provider-status').textContent.includes('尚未配置')")
            assert page.locator('#ai-model-submit').is_disabled()
            assert page.locator('#library-format').bounding_box()['height']<50
            assert page.locator('#empty-upload').is_visible()
            page.click('#empty-demo')
            page.wait_for_function("document.querySelector('#model-count').textContent==='5 网格'")
            assert not page.locator('#model-empty').is_visible()
            page.click('[data-inspector-target="ai-heading"]')
            assert page.locator('#ai-heading').evaluate('el=>document.activeElement===el')
            fixtures=[('assembly.glb',glb(),2),('parts.obj',OBJ,2),('triangle.stl',STL,1),('binary.stl',BINARY_STL,1)]
            for name,data,count in fixtures:
                page.locator('#model-file').set_input_files({'name':name,'mimeType':'application/octet-stream','buffer':data})
                page.wait_for_function("name=>document.querySelector('#model-title').textContent===name",arg=name)
                page.wait_for_function("document.querySelector('#status').textContent.includes('模型已上传并保存')")
                assert page.locator('#model-count').inner_text()==f'{count} 网格'
                assert page.locator('#download-model').is_visible()
                with page.expect_download() as download:page.click('#download-model')
                destination=Path(folder)/('download-'+name);download.value.save_as(destination)
                assert destination.read_bytes()==data
            assert page.locator('#model-library button').count()==4
            page.fill('#library-search','ASSEMBLY')
            assert page.locator('#model-library button').count()==1
            assert '1 / 4' in page.locator('#library-count').inner_text()
            page.select_option('#library-format','stl')
            assert page.locator('#model-library button').count()==0
            assert '没有符合条件' in page.locator('#model-library').inner_text()
            page.fill('#library-search','')
            assert page.locator('#model-library button').count()==2
            page.select_option('#library-format','all');page.select_option('#library-sort','name')
            names=page.locator('#model-library button').all_text_contents()
            assert [n.split(' · ')[0] for n in names]==['assembly.glb','binary.stl','parts.obj','triangle.stl']
            page.select_option('#library-sort','size')
            expected=sorted(fixtures,key=lambda item:len(item[1]),reverse=True)
            assert [n.split(' · ')[0] for n in page.locator('#model-library button').all_text_contents()]==[item[0] for item in expected]
            page.select_option('#library-sort','newest')
            assert page.locator('#model-library button').first.inner_text().startswith('binary.stl')
            page.reload();page.click('#tab-models')
            page.locator('#model-library button').filter(has_text='assembly.glb').click()
            page.wait_for_function("document.querySelector('#model-title').textContent==='assembly.glb'")
            assert page.locator('#model-count').inner_text()=='2 网格'
            assert page.locator('#model-library button[aria-pressed="true"]').inner_text().startswith('assembly.glb')
            tree=page.locator('#model-tree')
            assert 'Module' in tree.inner_text() and 'Base' in tree.inner_text() and 'Cap' in tree.inner_text()
            canvas=page.locator('#model-canvas canvas');before=canvas.screenshot()
            rect=canvas.bounding_box();x=rect['x']+rect['width']*.5;y=rect['y']+rect['height']*.5
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+90,y+40,steps=12);page.mouse.up()
            rotated=canvas.screenshot();assert rotated!=before,'Orbit drag did not change rendered pixels'
            page.mouse.wheel(0,-200)
            page.wait_for_timeout(150)
            assert canvas.screenshot()!=rotated,'Zoom did not change rendered pixels'
            tree.get_by_role('button',name='◇ Base',exact=True).click()
            assert 'Base' in page.locator('#model-selection').inner_text()
            page.click('#isolate-model')
            cap=tree.locator('.model-tree-row').filter(has=page.get_by_role('button',name='◇ Cap',exact=True))
            assert not cap.locator('input').is_checked()
            page.click('#show-all-model');assert cap.locator('input').is_checked()
            page.check('#model-wireframe');page.select_option('#model-up','Z');page.click('#fit-model')
            page.click('#view-current')
            page.wait_for_function("document.querySelector('#model-title').textContent.includes('参数模型')")
            assert page.locator('#model-count').inner_text()=='5 网格'
            # Reject malformed uploads without adding library entries.
            page.locator('#model-file').set_input_files({'name':'bad.glb','mimeType':'application/octet-stream','buffer':b'broken'})
            page.wait_for_function("document.querySelector('#status').textContent.includes('失败')")
            assert page.locator('#model-library button').count()==4
            page.locator('#model-file').set_input_files({'name':'external.glb','mimeType':'application/octet-stream','buffer':glb(external=True)})
            page.wait_for_function("document.querySelector('#status').textContent.includes('外部资源')")
            assert not external,external
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.set_viewport_size({'width':1500,'height':1050})
            page.screenshot(path='/tmp/form-3d-viewer.png',full_page=True)
            assert not errors,errors
            browser.close()
        print('PASS: GLB, OBJ, ASCII/binary STL upload, persisted library, filename search, format filtering, empty matches, name/size/newest sorting, active model indication, original downloads, object tree, isolation/visibility, rendered orbit/zoom, wireframe/up-axis, parameter mesh bridge, malformed/external-resource rejection, mobile layout; no JS errors')
    finally:
        http.shutdown();http.server_close()
