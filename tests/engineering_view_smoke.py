import os
os.environ["MESHY_API_KEY"]=""
os.environ["MODEL_GENERATOR_PROVIDER"]="meshy"
"""Verify geometry interactions against independently known STEP dimensions."""
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server
from step_fixtures import step_fixture
from model_fixtures import STL

class Quiet(server.Handler):
    def log_message(self,*args):pass


def points_on_screen(page,bounds,points):
    # Build an independent camera using the documented fitted-view geometry.
    # No access to application scene objects or test-only application hooks.
    return page.evaluate('''async ({bounds,points})=>{
      const T=await import('three'),rect=document.querySelector('#model-canvas canvas').getBoundingClientRect();
      const box=new T.Box3(new T.Vector3(...bounds[0]),new T.Vector3(...bounds[1]));
      const center=box.getCenter(new T.Vector3()),radius=box.getSize(new T.Vector3()).length()/2;
      const camera=new T.PerspectiveCamera(45,rect.width/rect.height,.00001,10000);
      const distance=radius/Math.sin(Math.PI/8)*Math.max(1,1/camera.aspect)*1.2;
      camera.position.copy(center).add(new T.Vector3(1,.75,1).normalize().multiplyScalar(distance));
      camera.lookAt(center);camera.updateMatrixWorld();
      return points.map(p=>{const v=new T.Vector3(...p).project(camera);return [rect.x+(v.x+1)*rect.width/2,rect.y+(1-v.y)*rect.height/2];});
    }''',{'bounds':bounds,'points':points})

source=step_fixture()
with tempfile.TemporaryDirectory() as folder,patch.object(server,'DB',Path(folder)/'db.sqlite3'):
    http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1600,'height':1200});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.click('#open-models')
            page.locator('#model-file').set_input_files({'name':'known.step','mimeType':'application/step','buffer':source})
            page.wait_for_function("document.querySelector('#model-title').textContent==='known.step'")
            canvas=page.locator('#model-canvas canvas');initial=canvas.screenshot()
            page.fill('#model-search','Right block')
            assert '匹配 1 个网格' in page.locator('#model-search-result').inner_text()
            assert not page.locator('#model-tree').get_by_role('button',name='◇ Left block',exact=True).is_visible()
            assert page.locator('#model-tree').get_by_role('button',name='◇ Right block',exact=True).is_visible()
            assert canvas.screenshot()==initial,'Search must not hide model geometry'
            page.fill('#model-search','Frame')
            assert '匹配 2 个网格' in page.locator('#model-search-result').inner_text()
            page.fill('#model-search','no-match')
            assert '匹配 0 个网格' in page.locator('#model-search-result').inner_text()
            page.fill('#model-search','')
            page.locator('#model-explosion').fill('70');page.locator('#model-explosion').dispatch_event('input')
            assert canvas.screenshot()!=initial,'Explosion must move displayed geometry'
            assert page.locator('#measure-mode').is_disabled()
            page.click('#reset-model-explosion')
            assert not page.locator('#measure-mode').is_disabled()
            assert canvas.screenshot()==initial,'Reset must restore the exact initial assembly view'
            assert page.locator('#source-unit').input_value()=='m' and page.locator('#source-unit').is_disabled()
            page.check('#measure-mode')
            canvas.screenshot()
            page.click('#fit-model')
            clicks=points_on_screen(page,[[0,0,-.05],[.25,.025,0]],[[.02,.025,-.02],[.08,.025,-.02]])
            for x,y in clicks:page.mouse.click(x,y)
            value=float(page.locator('#measurement-result').get_attribute('data-distance'))
            assert abs(value-60)<.2,(value,'expected 60mm between surface points')
            assert page.locator('#measurement-result').get_attribute('data-unit')=='mm'
            page.select_option('#measurement-unit','m')
            assert abs(float(page.locator('#measurement-result').get_attribute('data-distance'))-.06)<.0002
            page.select_option('#measurement-unit','mm')
            page.screenshot(path='/tmp/form-step-measurement.png',full_page=True)
            page.click('#clear-measurement')
            assert page.locator('#measurement-result').get_attribute('data-distance') is None
            page.uncheck('#measure-mode')
            page.select_option('#model-view','iso');page.click('#fit-model')
            overview=canvas.screenshot()
            views=[]
            for direction in ['front','back','left','right','top','bottom']:
                page.select_option('#model-view',direction)
                views.append(canvas.screenshot())
            assert len(set(views))>=3,'Standard directions must change the rendered view'
            page.select_option('#model-view','iso')
            assert canvas.screenshot()==overview,'Returning to isometric must restore framing'
            page.locator('#model-tree').get_by_role('button',name='◇ Right block',exact=True).click()
            page.click('#isolate-model');page.click('#fit-model')
            isolated=canvas.screenshot()
            page.click('#focus-model')
            assert canvas.screenshot()==isolated,'Visible fit must equal selected fit for an isolated mesh'
            page.click('#show-all-model');page.click('#fit-model')
            full=canvas.screenshot();page.click('#focus-model')
            assert canvas.screenshot()!=full,'Focusing one mesh must change full assembly framing'
            # Hidden selection should report a clear error instead of moving to an empty box.
            page.locator('#model-tree .selected input').uncheck()
            page.click('#focus-model')
            assert '没有可见几何' in page.locator('#status').inner_text()
            page.click('#show-all-model')
            page.select_option('#model-view','top')
            # A new upload must clear measurements, search and explosion state.
            page.locator('#model-file').set_input_files({'name':'triangle.stl','mimeType':'model/stl','buffer':STL})
            page.wait_for_function("document.querySelector('#model-title').textContent==='triangle.stl'")
            assert page.locator('#model-view').input_value()=='iso'
            assert page.locator('#source-unit').input_value()=='native'
            assert page.locator('#model-explosion').input_value()=='0'
            assert page.locator('#measurement-result').get_attribute('data-distance') is None
            page.check('#measure-mode')
            canvas.screenshot()
            page.click('#fit-model')
            clicks=points_on_screen(page,[[0,0,-1],[1,0,0]],[[.2,0,-.2],[.6,0,-.2]])
            for x,y in clicks:page.mouse.click(x,y)
            assert page.locator('#measurement-result').get_attribute('data-unit')=='原生单位'
            assert '源单位未知' in page.locator('#measurement-result').inner_text()
            page.select_option('#source-unit','mm');page.select_option('#measurement-unit','m')
            assert abs(float(page.locator('#measurement-result').get_attribute('data-distance'))-.0004)<.00001
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors,errors
            browser.close()
        print('PASS: standard views, isometric reset, visible-only fit, selection focus, hidden selection feedback, new-model view reset, hierarchy search, exact explosion reset, explosion-measure lockout, known 60mm STEP surface measurement, m/mm conversion, unknown STL units, measurement clearing and mobile layout; no JS errors')
    finally:http.shutdown();http.server_close()
