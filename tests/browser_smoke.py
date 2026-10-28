import os
os.environ["MESHY_API_KEY"]=""
os.environ["MODEL_GENERATOR_PROVIDER"]="meshy"
"""Optional integration test: python3 tests/browser_smoke.py.
Requires Playwright and a system Chromium; uses a disposable database/server.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server

with tempfile.TemporaryDirectory() as temp:
    server.DB=Path(temp)/'projects.sqlite3'
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{http.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(base)
            page.wait_for_function("document.querySelector('#status').textContent.includes('已就绪')")
            assert page.locator('#parts button').count()==5
            page.click('#explore')
            assert page.locator('#variants button').count()==9
            page.locator('#variants button').nth(4).click()
            page.wait_for_function("document.querySelector('#count').textContent==='32'")
            page.click('#generate')
            page.fill('input[name=fins]','32')
            page.click('#generate-form button.primary')
            page.wait_for_function("document.querySelector('#count').textContent==='36'")
            assert page.locator('#scene polygon').count()==108
            assert page.locator('#layers li').count()==3
            assert '35 个后续零件' in page.locator('#impact').inner_text()
            page.fill('#part-name','原始水室')
            page.click('#editor button.primary')
            page.wait_for_function("document.querySelector('#parts').textContent.includes('原始水室')")
            page.click('#save')
            page.wait_for_function("document.querySelector('#status').textContent.includes('数据库')")
            page.select_option('#shape','cylinder')
            page.locator('#rotations input').nth(2).fill('45')
            page.fill('#part-name','旋转圆柱')
            page.click('#editor button.primary')
            page.wait_for_function("document.querySelector('#parts').textContent.includes('旋转圆柱')")
            assert page.locator('#scene polygon').count()>108
            page.click('#save')
            page.wait_for_function("document.querySelector('#status').textContent.includes('数据库')")
            page.reload()
            page.wait_for_function("document.querySelector('#status').textContent.includes('已就绪')")
            assert page.locator('#shape').input_value()=='cylinder'
            assert page.locator('#rotations input').nth(2).input_value()=='45'
            with page.expect_download() as download:
                page.click('#stl')
            path=Path(temp)/'assembly.stl'
            download.value.save_as(path)
            assert path.read_text().count('facet normal')==188+35*12
            page.click('#history')
            page.wait_for_function("document.querySelectorAll('#history-list button').length===2")
            assert page.locator('#history-list button').count()==2
            page.locator('#history-list button').nth(1).click()
            page.wait_for_function("document.querySelector('#status').textContent.includes('已载入版本')")
            assert page.locator('#shape').input_value()=='box'
            assert page.locator('#part-name').input_value()=='原始水室'
            # Loading a historical version must not silently overwrite the saved current project.
            page.reload()
            page.wait_for_function("document.querySelector('#status').textContent.includes('已就绪')")
            assert page.locator('#shape').input_value()=='cylinder'
            page.locator('#step').fill('1')
            page.locator('#step').dispatch_event('input')
            assert '装配步骤 1' in page.locator('#step-label').inner_text()
            page.check('#explode')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors,errors
            browser.close()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request(base+'/api/project',data=b'{"name":"bad","parts":[]}',headers={'Content-Type':'application/json'})
        try:
            opener.open(request)
            raise AssertionError('Invalid project accepted')
        except urllib.error.HTTPError as error:
            assert error.code==400
        assert json.load(opener.open(base+'/api/project'))['parts'][0]['shape']=='cylinder'
        print('PASS: nine variants, generation, rotation, cylinder mesh, STL, saving, history isolation, playback controls, responsive layout, invalid-write protection; no JS errors')
    finally:
        http.shutdown()
        http.server_close()
