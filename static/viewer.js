import * as THREE from 'three';
import { OrbitControls } from '/vendor/addons/controls/OrbitControls.js';
import { GLTFLoader } from '/vendor/addons/loaders/GLTFLoader.js';
import { OBJLoader } from '/vendor/addons/loaders/OBJLoader.js';
import { STLLoader } from '/vendor/addons/loaders/STLLoader.js';

const $=id=>document.getElementById(id);
const MAX_BYTES=50*1024*1024;
let renderer,scene,camera,controls,wrapper,root,selected,selectionBox,activeAsset;
let busy=false, loadVersion=0, pointerStart, pointerMoved=false;
const treeRows=new Map();
const restPositions=new Map();
let measurementGroup=null,measurementPoints=[];
let cadReport=null,cadToken=0;

function message(text){$('status').textContent=text;}
async function jsonAPI(path,options){const response=await fetch(path,options);const data=await response.json();if(!response.ok){const error=Error(data.error||`请求失败 (${response.status})`);error.status=response.status;throw error;}return data;}
function guarded(fn){return async(...args)=>{try{await fn(...args);}catch(error){message('三维模型操作失败：'+error.message);}};}
function tab(models){$('assembly-workspace').hidden=models;$('model-workspace').hidden=!models;$('tab-models').classList.toggle('active',models);$('tab-assembly').classList.toggle('active',!models);if(models){try{init();resize();}catch(error){message(error.message);}}}
$('open-models').onclick=()=>tab(true);$('tab-models').onclick=()=>tab(true);$('tab-assembly').onclick=()=>tab(false);
function init(){
 if(renderer)return;
 const canvas=$('model-canvas');
 let candidate;
 try{candidate=new THREE.WebGLRenderer({antialias:true,alpha:false});}catch{throw Error('无法创建 WebGL 三维视图，请启用浏览器硬件加速或使用支持 WebGL 的浏览器。');}
 renderer=candidate;renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x11171e);
 scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xddeeff,0x536046,2.6));
 const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(3,5,4);scene.add(light);
 camera=new THREE.PerspectiveCamera(45,1,.01,1e6);camera.position.set(3,2,3);
 controls=new OrbitControls(camera,renderer.domElement);controls.addEventListener('change',render);
 canvas.append(renderer.domElement);
 new ResizeObserver(resize).observe(canvas);
 renderer.domElement.addEventListener('pointerdown',e=>{pointerStart=[e.clientX,e.clientY];pointerMoved=false;});
 renderer.domElement.addEventListener('pointermove',e=>{if(pointerStart&&Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>4)pointerMoved=true;});
 renderer.domElement.addEventListener('pointerup',e=>{
  if(!pointerMoved&&pointerStart&&e.button===0&&root){
   const rect=renderer.domElement.getBoundingClientRect();const pointer=new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
   const ray=new THREE.Raycaster();ray.setFromCamera(pointer,camera);
   const hits=ray.intersectObject(root,true).filter(hit=>{for(let n=hit.object;n;n=n.parent){if(!n.visible)return false;}return true;});
   if(hits.length){if($('measure-mode').checked)addMeasurementPoint(hits[0].point);else selectObject(hits[0].object);}
  }pointerStart=null;
 });
 resize();
}
function resize(){if(!renderer||$('model-workspace').hidden)return;const holder=$('model-canvas');const w=holder.clientWidth,h=holder.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();render();}
function render(){if(renderer&&scene&&camera)renderer.render(scene,camera);}
function release(object){
 const geometries=new Set(),materials=new Set(),textures=new Set();
 object?.traverse(node=>{if(node.geometry)geometries.add(node.geometry);for(const material of (Array.isArray(node.material)?node.material:[node.material])){if(!material)continue;materials.add(material);for(const value of Object.values(material))if(value?.isTexture)textures.add(value);}});
 geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>{t.source?.data?.close?.();t.dispose();});
}
function visibleBounds(object){
 const box=new THREE.Box3();wrapper.updateMatrixWorld(true);
 object.traverse(node=>{
  if(!node.isMesh||!node.geometry)return;
  for(let parent=node;parent;parent=parent.parent)if(!parent.visible)return;
  if(!node.geometry.boundingBox)node.geometry.computeBoundingBox();
  box.union(node.geometry.boundingBox.clone().applyMatrix4(node.matrixWorld));
 });return box;
}
function fit(object=root,preset=$('model-view').value){
 if(!root||!object)return;
 const box=visibleBounds(object);if(box.isEmpty())throw Error('没有可见几何，请先显示需要查看的对象');
 const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
 const radius=Math.max(size.length()/2,1e-5);const distance=radius/Math.sin(THREE.MathUtils.degToRad(camera.fov/2))*Math.max(1,1/camera.aspect)*1.2;
 const directions={iso:[1,.75,1],front:[0,0,1],back:[0,0,-1],left:[-1,0,0],right:[1,0,0],top:[0,1,0],bottom:[0,-1,0]};
 camera.up.set(0,1,0);if(preset==='top')camera.up.set(0,0,-1);if(preset==='bottom')camera.up.set(0,0,1);
 camera.near=Math.max(radius/10000,1e-8);camera.far=Math.max(distance*100,radius*1000);camera.updateProjectionMatrix();
 camera.position.copy(center).add(new THREE.Vector3(...directions[preset]).normalize().multiplyScalar(distance));
 controls.target.copy(center);controls.minDistance=radius*.02;controls.maxDistance=radius*100;controls.update();render();
}
function visibleMeshes(object){const nodes=[];object.traverse(n=>{if(n.isMesh)nodes.push(n);});return nodes;}
function inspect(object){
 let triangles=0,vertices=0;
 object.traverse(n=>{if(n.isMesh&&n.geometry){const p=n.geometry.getAttribute('position');vertices+=p?.count||0;triangles+=(n.geometry.index?.count||p?.count||0)/3;}});
 return {triangles:Math.floor(triangles),vertices};
}
function selectObject(object){
 selected=object;
 if(selectionBox){scene.remove(selectionBox);release(selectionBox);selectionBox=null;}
 selectionBox=new THREE.BoxHelper(object,0xbce990);scene.add(selectionBox);
 $('model-selection').textContent=`${object.name||'未命名对象'} · ${object.isMesh?'网格':'分组'} · ${inspect(object).triangles.toLocaleString()} 个三角面`;
 const box=new THREE.Box3().setFromObject(object),size=box.getSize(new THREE.Vector3());
 $('model-bounds').textContent=`世界包围盒：${size.toArray().map(x=>Number(x.toPrecision(5))).join(' × ')}${activeAsset?.preview_units==='m'?' m（STEP 长度单位已转换，预览为近似网格）':'（文件原生单位）。GLB 通常以米为单位，STL/OBJ 不携带可靠单位；未自动推断工程尺寸。'}`;
 for(const [node,row] of treeRows)row.classList.toggle('selected',node===object);
 render();
}
function buildTree(){
 treeRows.clear();const tree=$('model-tree');tree.replaceChildren();
 function visit(object,depth){
  const row=document.createElement('div');row.className='model-tree-row';row.style.paddingLeft=Math.min(depth*12,72)+'px';row.dataset.objectId=object.uuid;
  const check=document.createElement('input');check.type='checkbox';check.checked=object.visible;check.setAttribute('aria-label','显示 '+(object.name||'对象'));
  check.onchange=()=>{object.visible=check.checked;clearMeasurement();if(selectionBox)selectionBox.visible=false;render();};
  const button=document.createElement('button');button.textContent=(object.isMesh?'◇ ':'▾ ')+(object.name||'未命名对象');button.onclick=()=>selectObject(object);
  row.append(check,button);tree.append(row);treeRows.set(object,row);
  object.children.forEach(child=>visit(child,depth+1));
 }
 visit(root,0);$('model-count').textContent=visibleMeshes(root).length+' 网格';filterTree();
}
function install(object,title,asset=null,up='Y'){
 init();const stats=inspect(object);
 if(!stats.triangles||stats.triangles>1_000_000||stats.vertices>3_000_000){release(object);throw Error('模型无三角面或超过显示上限（100 万面 / 300 万顶点）');}
 let nodes=0;object.traverse(n=>{nodes++;const p=n.geometry?.getAttribute('position');if(p)for(let i=0;i<p.array.length;i++)if(!Number.isFinite(p.array[i]))throw Error('模型包含无效顶点');});
 if(nodes>10000){release(object);throw Error('模型节点超过 10000 个');}
 const testBounds=new THREE.Box3().setFromObject(object);
 if(testBounds.isEmpty()||![...testBounds.min.toArray(),...testBounds.max.toArray()].every(Number.isFinite)){release(object);throw Error('模型坐标或边界无效');}
 clearMeasurement();restPositions.clear();
 if(wrapper){scene.remove(wrapper);release(wrapper);}if(selectionBox){scene.remove(selectionBox);release(selectionBox);selectionBox=null;}
 root=object;selected=null;root.name ||= title;activeAsset=asset;renderLibrary();resetCadPanel();$('generation-model-summary').textContent='';wrapper=new THREE.Group();wrapper.add(root);scene.add(wrapper);
 $('model-view').value='iso';$('model-up').value=up;wrapper.rotation.x=up==='Z'?-Math.PI/2:0;wrapper.updateMatrixWorld(true);
 root.traverse(node=>{if(node.isMesh)restPositions.set(node,node.position.clone());});
 $('model-explosion').value=0;$('model-explosion-value').textContent='0%';$('measure-mode').checked=false;$('measure-mode').disabled=false;$('model-search').value='';
 const knownUnit=asset?.preview_units||(asset?.extension==='.glb'?'m':object.userData.formUnits||'native');
 $('source-unit').value=knownUnit;$('source-unit').disabled=!!asset?.preview_units||!!object.userData.formUnits;
 $('measurement-unit').value=knownUnit==='native'?'native':'mm';updateMeasurementText();
 $('model-title').textContent=title;$('model-stats').textContent=`${visibleMeshes(root).length} 个网格 · ${stats.triangles.toLocaleString()} 个三角面 · 拖动旋转 / 滚轮缩放 / 右键平移`;
 $('model-empty').hidden=true;$('download-model').hidden=!asset;if(asset){$('download-model').href=`/api/models/${asset.id}/download`;$('download-model').download=asset.name;}
 $('download-preview').hidden=!asset?.preview_extension;if(asset?.preview_extension){$('download-preview').href=`/api/models/${asset.id}/preview-download`;$('download-preview').download=asset.name.replace(/\.[^.]+$/,'.glb');}$('model-wireframe').checked=false;buildTree();resize();fit();selectObject(root);
}
function localManager(){
 const manager=new THREE.LoadingManager();
 manager.setURLModifier(url=>{if(url.startsWith('data:')||url.startsWith('blob:'))return url;throw Error('模型包含外部资源。请将纹理和缓冲区嵌入 GLB；不会自动请求外部地址。');});
 return manager;
}
async function parseModel(buffer,extension){
 const manager=localManager();
 if(extension==='.glb'){
  const gltf=await new GLTFLoader(manager).parseAsync(buffer,'');
  // GLTFLoader sanitizes node names for animation paths; retain original CAD labels in this static viewer.
  gltf.scene.traverse(node=>{const link=gltf.parser.associations.get(node);if(Number.isInteger(link?.nodes)){const original=gltf.parser.json.nodes[link.nodes]?.name;if(original)node.name=original;}});
  return gltf.scene;
 }
 if(extension==='.obj'){
  const text=new TextDecoder('utf-8',{fatal:true}).decode(buffer);
  return new OBJLoader(manager).parse(text);
 }
 const geometry=new STLLoader(manager).parse(buffer);
 geometry.computeVertexNormals();return new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0x91aeb8,roughness:.48,metalness:.18,side:THREE.DoubleSide}));
}
let libraryAssets=[],libraryVersion=0;
function renderLibrary(){
 const query=$('library-search').value.trim().toLocaleLowerCase(),format=$('library-format').value;
 const matches=libraryAssets.filter(asset=>asset.name.toLocaleLowerCase().includes(query)&&(format==='all'||(format==='step'?['.step','.stp'].includes(asset.extension):asset.extension==='.'+format)));
 const order=$('library-sort').value;
 if(order==='name')matches.sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));
 if(order==='size')matches.sort((a,b)=>b.bytes-a.bytes);
 $('library-count').textContent=`显示 ${matches.length} / ${libraryAssets.length} 个模型`;
 $('model-library').replaceChildren(...matches.map(asset=>{
  const button=document.createElement('button');button.textContent=`${asset.name} · ${(asset.bytes/1024).toFixed(1)} KB`;button.dataset.assetId=asset.id;
  button.setAttribute('aria-pressed',String(asset.id===activeAsset?.id));
  button.onclick=guarded(()=>loadAsset(asset));return button;
 }));
 if(!matches.length)$('model-library').textContent=libraryAssets.length?'没有符合条件的模型，请调整搜索或文件类型。':'尚无上传模型。文件会保存在本地模型库。';
}
$('library-search').oninput=renderLibrary;$('library-format').onchange=renderLibrary;$('library-sort').onchange=renderLibrary;
async function library(){
 const version=++libraryVersion,models=await jsonAPI('/api/models');
 if(version!==libraryVersion)return;libraryAssets=models;renderLibrary();
}
async function loadAsset(asset,isCurrent=()=>true){
 const version=++loadVersion;message('正在加载 '+asset.name+'…');const response=await fetch(`/api/models/${asset.id}/content`);if(!response.ok)throw Error('模型文件读取失败');
 const object=await parseModel(await response.arrayBuffer(),asset.preview_extension||asset.extension);if(version!==loadVersion||!isCurrent()){release(object);return;}
 install(object,asset.name,asset,asset.up_axis||(asset.extension==='.glb'?'Y':'Z'));message(asset.preview_extension?'STEP 已转换并加载；预览单位为米，零件树尽量保留源文件结构，原始 STEP 可单独下载。':'已加载模型；零件树来自文件中的对象分组，不代表自动工程拆解。');
}
$('upload-model').onclick=()=>$('model-file').click();
$('model-file').onchange=guarded(async()=>{
 const file=$('model-file').files[0];$('model-file').value='';if(!file)return;if(busy)throw Error('请等待当前上传完成');
 const extension='.'+file.name.split('.').pop().toLowerCase();if(!['.glb','.obj','.stl','.step','.stp'].includes(extension)||!file.size||file.size>MAX_BYTES)throw Error('请选择 1 字节至 50MB 的 GLB、OBJ、STL 或 STEP/STP 文件');
 busy=true;$('upload-model').disabled=true;let object,installed=false;
 try{
  const buffer=await file.arrayBuffer();
  if(['.step','.stp'].includes(extension)){
   message('正在本地转换 STEP，请稍候（最长约 60 秒）…');
   const asset=await jsonAPI('/api/models',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Model-Name':encodeURIComponent(file.name)},body:buffer});
   await library();await loadAsset(asset);return;
  }
  message('正在解析 '+file.name+'…');object=await parseModel(buffer,extension);
  const stats=inspect(object);if(!stats.triangles||stats.triangles>1_000_000||stats.vertices>3_000_000)throw Error('模型无三角面或超过显示上限');
  const asset=await jsonAPI('/api/models',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Model-Name':encodeURIComponent(file.name)},body:buffer});
  ++loadVersion;install(object,file.name,asset,extension==='.glb'?'Y':'Z');installed=true;await library();message('模型已上传并保存，可从模型库重新加载。');
 }finally{busy=false;$('upload-model').disabled=false;if(object&&!installed)release(object);}
});
$('fit-model').onclick=guarded(()=>fit());
$('focus-model').onclick=guarded(()=>{if(!selected)throw Error('请先选择对象');fit(selected);});
$('model-view').onchange=guarded(()=>fit());
$('model-up').onchange=guarded(()=>{if(!wrapper)return;resetExplosion();clearMeasurement();wrapper.rotation.x=$('model-up').value==='Z'?-Math.PI/2:0;wrapper.updateMatrixWorld(true);fit();if(selected)selectObject(selected);});
$('model-wireframe').onchange=()=>{root?.traverse(n=>{for(const m of (Array.isArray(n.material)?n.material:[n.material]))if(m){m.wireframe=$('model-wireframe').checked;m.needsUpdate=true;}});render();};
$('show-all-model').onclick=()=>{clearMeasurement();root?.traverse(n=>n.visible=true);for(const row of treeRows.values())row.querySelector('input').checked=true;if(selected)selectObject(selected);render();};
$('isolate-model').onclick=()=>{
 if(!selected){message('请先选择对象');return;}
 clearMeasurement();const keep=new Set();selected.traverse(n=>keep.add(n));for(let n=selected;n;n=n.parent)keep.add(n);
 root.traverse(n=>n.visible=keep.has(n));for(const [node,row] of treeRows)row.querySelector('input').checked=node.visible;render();
};
$('view-current').onclick=()=>document.dispatchEvent(new Event('form:request-project'));
document.addEventListener('form:project',guarded(event=>{
 const {project,report}=event.detail;if(!project||!report?.meshes)throw Error('参数项目尚未就绪');
 ++loadVersion;const group=new THREE.Group();group.name=project.name;group.userData.formUnits='mm';
 for(const part of project.parts){const data=report.meshes[part.id],indices=[];for(const face of data.faces)for(let i=1;i<face.length-1;i++)indices.push(face[0],face[i],face[i+1]);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices.flat(),3));geometry.setIndex(indices);geometry.computeVertexNormals();
  const object=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0x91b5c0,roughness:.55,metalness:.15}));object.name=part.name;group.add(object);
 }install(group,project.name+' · 参数模型',null,'Z');message('当前参数模型已在三维视图中打开，坐标单位 mm。');
}));

let providerReady=false,providerAdapter='meshy',currentJobId=null,jobTimer,generationSubmitting=false,jobWatchVersion=0;
function requestToken(){let id=sessionStorage.getItem('form-generation-request');if(!id){id=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem('form-generation-request',id);}return id;}
$('new-generation-request').onclick=()=>{if(generationSubmitting||currentJobId){message('请等待当前请求结束或从任务记录查看进度。');return;}sessionStorage.removeItem('form-generation-request');message('已准备新的生成请求。若上次提交超时，请先核对 Meshy 后台，避免重复计费。');};
function enableGeneration(){$('ai-model-submit').disabled=!providerReady||!!currentJobId||generationSubmitting;}
function generationStrategy(options){
 if(!options)return '历史任务未记录生成选项';
 const names={standard:'标准几何',parts:'T2 分件优先',detail:'T2.5 拓扑细节'};
 return `${names[options.mesh_mode]||'未知策略'} · ${options.target_polycount?'目标 '+options.target_polycount+' 面':'面数使用供应商默认'}`;
}
function jobDisplay(job){
 $('generation-progress').hidden=false;$('generation-bar').value=job.progress||0;
 const labels={PENDING:'等待生成',IN_PROGRESS:'正在生成',SUCCEEDED:'生成完成',FAILED:'生成失败',CANCELED:'任务取消'};
 $('generation-state').textContent=`${labels[job.status]||job.status} · ${Math.round(job.progress||0)}%`;
 $('generation-detail').textContent=generationStrategy(job.generation_options)+'。'+(job.error||'任务已保存；刷新页面后可继续查询，不会重新提交生成。');
}
async function jobList(){
 const jobs=await jsonAPI('/api/generation-jobs');
 $('generation-jobs').replaceChildren(...jobs.slice(0,10).map(job=>{const b=document.createElement('button');b.textContent=`${job.name} · ${job.status} · ${Math.round(job.progress)}%`;b.onclick=guarded(()=>watchJob(job.id));return b;}));
 if(!jobs.length)$('generation-jobs').textContent='尚无生成任务';return jobs;
}
async function watchJob(id,retry=0){
 clearTimeout(jobTimer);const version=++jobWatchVersion;currentJobId=id;enableGeneration();
 let job;
 try{
  job=await jsonAPI(`/api/generation-jobs/${id}`,{signal:AbortSignal.timeout(20000)});
 }catch(error){
  if(version!==jobWatchVersion)return;
  const temporary=!error.status||[408,429,500,502,503,504].includes(error.status);
  if(temporary&&retry<3){
   const delay=2000*2**retry;
   $('generation-progress').hidden=false;
   $('generation-state').textContent='进度查询暂时中断';
   $('generation-detail').textContent=`${delay/1000} 秒后自动重试查询（${retry+1}/3）。不会重新提交生成任务。`;
   jobTimer=setTimeout(()=>guarded(()=>watchJob(id,retry+1))(),delay);return;
  }
  currentJobId=null;enableGeneration();
  $('generation-state').textContent='进度查询已暂停';
  $('generation-detail').textContent='无法获取最新进度。可从任务记录重新查询；云端生成不会因此取消。';
  throw error;
 }
 if(version!==jobWatchVersion)return;
 try{
  jobDisplay(job);
  if(job.status==='SUCCEEDED'){
   currentJobId=null;enableGeneration();const modelVersion=loadVersion;await library();await jobList();
   if(version!==jobWatchVersion||modelVersion!==loadVersion)return;
   if(!job.asset)throw Error('生成任务完成，但本地模型记录缺失，请检查模型库备份');
   await loadAsset(job.asset,()=>version===jobWatchVersion);
   if(version!==jobWatchVersion)return;
   if(activeAsset?.id===job.asset.id){const stats=inspect(root),count=visibleMeshes(root).length;$('generation-model-summary').textContent=`${generationStrategy(job.generation_options)}。结果 ${count} 个网格节点、${stats.triangles.toLocaleString()} 个三角面；目标面数不是严格保证，节点数量不等于机械零件或装配关系。`;}
   message('AI 生成结果已保存并加载，请检查几何与工程适用性。');return;
  }
  if(job.error||['FAILED','CANCELED'].includes(job.status)){
   currentJobId=null;enableGeneration();await jobList();message(job.error||'生成未完成，请检查任务记录');return;
  }
  jobTimer=setTimeout(()=>guarded(()=>watchJob(id))(),5000);
 }catch(error){if(version!==jobWatchVersion)return;currentJobId=null;enableGeneration();throw error;}
}
guarded(async()=>{
 await library();const config=await jsonAPI('/api/model-generation');providerReady=config.configured;providerAdapter=config.adapter;$('generation-options').hidden=!config.supports_mesh_options;updateGenerationOptions();
 $('provider-status').textContent=providerReady?(providerAdapter==='meshy'?'Meshy 已配置：支持文字/图片生成，会消耗账户额度。':'已配置自定义生成接口；实际能力由所接服务提供。'):(providerAdapter==='meshy'?'尚未配置 Meshy。请在环境设置中填写 MESHY_API_KEY，密钥不要发到聊天里。':'尚未配置生成服务，接口配置见 docs/MODEL_GENERATION.md。');
 enableGeneration();const jobs=await jobList();const pending=jobs.find(j=>!['SUCCEEDED','FAILED','CANCELED'].includes(j.status));if(pending&&providerReady)await watchJob(pending.id);
})();
$('ai-model-form').onsubmit=guarded(async event=>{
 event.preventDefault();if(generationSubmitting)return;if(!providerReady)throw Error('请先配置生成接口');if(currentJobId)throw Error('已有任务正在查询，请等待结果');
 generationSubmitting=true;enableGeneration();
 try{
 let image_data_url=null;const file=$('model-image').files[0];if(file){if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>5*1024*1024)throw Error('参考图仅支持 5MB 以内的 PNG、JPEG、WebP');image_data_url=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('参考图读取失败'));reader.readAsDataURL(file);});}
 $('ai-model-submit').disabled=true;message('正在提交生成任务，请勿重复提交…');
  const result=await jsonAPI('/api/model-generation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:$('model-prompt').value,image_data_url,...(providerAdapter==='meshy'?{generation_options:{mesh_mode:$('generation-mesh-mode').value,target_polycount:$('generation-polycount').value===''?null:Number($('generation-polycount').value)}}:{}),client_request_id:requestToken()})});
  sessionStorage.removeItem('form-generation-request');
  if(providerAdapter==='meshy'){await jobList();await watchJob(result.id);}else{await library();await loadAsset(result);message('生成结果已保存并加载；请检查几何和工程适用性。');}
 }finally{generationSubmitting=false;enableGeneration();}
});

function filterTree(){
 if(!root)return;
 const query=$('model-search').value.trim().toLocaleLowerCase();let matched=0;
 function visit(node,inherited){
  const direct=!query||(node.name||'').toLocaleLowerCase().includes(query),branch=inherited||direct;
  let descendant=false;for(const child of node.children)descendant=visit(child,branch)||descendant;
  const show=branch||descendant;if(node.isMesh&&branch)matched++;
  const row=treeRows.get(node);if(row)row.hidden=!show;return show;
 }
 visit(root,false);$('model-search-result').textContent=query?`匹配 ${matched} 个网格；搜索只过滤列表，不隐藏模型。`:'';
}
$('model-search').oninput=filterTree;
function clearMeasurement(){
 measurementPoints=[];delete $('measurement-result').dataset.distance;delete $('measurement-result').dataset.unit;
 if(measurementGroup){scene?.remove(measurementGroup);release(measurementGroup);measurementGroup=null;}
 updateMeasurementText();render();
}
function updateMeasurementText(){
 if(measurementPoints.length<2){$('measurement-result').textContent=measurementPoints.length?'已选择第一个表面点，请点击第二个点。':'开启两点测距后，依次点击模型表面。';return;}
 const distance=measurementPoints[0].distanceTo(measurementPoints[1]),source=$('source-unit').value,output=$('measurement-unit').value;
 let factor=1,label='原生单位';
 if(source!=='native'&&output!=='native'){factor=(source==='m'?1000:1)/(output==='m'?1000:1);label=output;}
 else if(source!=='native')label=source;
 const formatted=new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:7}).format(distance*factor);
 $('measurement-result').textContent=`网格点间距离：${formatted} ${label}${source==='native'?'（源单位未知，请先确认源网格单位）':''}。近似值，不用于制造检验。`;
 $('measurement-result').dataset.distance=String(distance*factor);$('measurement-result').dataset.unit=label;
}
function addMeasurementPoint(point){
 if(!root||+$('model-explosion').value>0)return;
 if(measurementPoints.length===2)clearMeasurement();
 if(!measurementGroup){measurementGroup=new THREE.Group();scene.add(measurementGroup);}
 const radius=Math.max(new THREE.Box3().setFromObject(wrapper).getSize(new THREE.Vector3()).length()*.005,1e-8);
 const marker=new THREE.Mesh(new THREE.SphereGeometry(radius,12,8),new THREE.MeshBasicMaterial({color:0xffd277,depthTest:false}));marker.position.copy(point);marker.renderOrder=10;measurementGroup.add(marker);
 measurementPoints.push(point.clone());
 if(measurementPoints.length===2){const geometry=new THREE.BufferGeometry().setFromPoints(measurementPoints);const line=new THREE.Line(geometry,new THREE.LineBasicMaterial({color:0xffd277,depthTest:false}));line.renderOrder=10;measurementGroup.add(line);}
 updateMeasurementText();render();
}
$('measure-mode').onchange=()=>{clearMeasurement();if($('measure-mode').checked)message('测距模式：依次点击两个网格表面点，拖动仍可旋转视图；再次选择会开始新测量。');};
$('clear-measurement').onclick=clearMeasurement;$('source-unit').onchange=updateMeasurementText;$('measurement-unit').onchange=updateMeasurementText;
function applyExplosion(){
 if(!root)return;
 clearMeasurement();const amount=+$('model-explosion').value/100;
 $('model-explosion-value').textContent=`${Math.round(amount*100)}%`;
 if(amount){$('measure-mode').checked=false;$('measure-mode').disabled=true;}else $('measure-mode').disabled=false;
 for(const [object,position] of restPositions)object.position.copy(position);
 wrapper.updateMatrixWorld(true);
 if(amount){
  const box=new THREE.Box3().setFromObject(wrapper),center=box.getCenter(new THREE.Vector3()),distance=box.getSize(new THREE.Vector3()).length()*.6*amount;
  const records=[...restPositions.keys()].map((object,i)=>{
   const direction=new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3()).sub(center);
   if(direction.lengthSq()<1e-20)direction.set(Math.cos(i*2.4),Math.sin(i*2.4),.4);
   return {object,target:object.getWorldPosition(new THREE.Vector3()).add(direction.normalize().multiplyScalar(distance))};
  });
  for(const {object,target} of records){object.position.copy(object.parent.worldToLocal(target.clone()));object.updateMatrixWorld(true);}
 }
 if(selected)selectObject(selected);render();
}
function resetExplosion(){$('model-explosion').value=0;applyExplosion();}
$('model-explosion').oninput=applyExplosion;$('reset-model-explosion').onclick=resetExplosion;

function resetCadPanel(){
 ++cadToken;cadReport=null;$('cad-body-a').disabled=false;$('cad-body-b').disabled=false;const supported=!!activeAsset?.preview_extension;
 $('cad-scan').disabled=!supported;$('cad-pair-controls').hidden=true;$('cad-summary').textContent='';$('cad-result').textContent='';
 delete $('cad-result').dataset.gapMm;delete $('cad-result').dataset.overlapMm3;
 $('cad-availability').textContent=supported?'从原始 STEP 读取封闭实体，单位 mm / mm³。':'B-rep 检查需要原始 STEP；网格模型请使用下方网格测量。';
}
function cadChoicesChanged(){
 if(cadReport)delete cadReport.pair;
 $('cad-result').textContent='所选实体已变化，请重新计算。';delete $('cad-result').dataset.gapMm;delete $('cad-result').dataset.overlapMm3;
 $('cad-compare').disabled=!cadReport||$('cad-body-a').value===$('cad-body-b').value;
}
$('cad-body-a').onchange=cadChoicesChanged;$('cad-body-b').onchange=cadChoicesChanged;
async function cadRequest(pair){
 if(!activeAsset?.preview_extension)throw Error('请先加载 STEP');
 const asset=activeAsset,token=++cadToken;$('cad-scan').disabled=true;$('cad-compare').disabled=true;$('cad-body-a').disabled=true;$('cad-body-b').disabled=true;
 if(pair){$('cad-result').textContent='正在计算所选实体的最短距离与相交体积…';delete $('cad-result').dataset.gapMm;delete $('cad-result').dataset.overlapMm3;}
 else $('cad-summary').textContent='正在读取原始 STEP 实体，最长约 60 秒…';
 try{
  const report=await jsonAPI(`/api/models/${asset.id}/cad-inspect`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pair||{})});
  if(token!==cadToken||activeAsset?.id!==asset.id)return;
  cadReport=report;const number=n=>new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:9}).format(n);
  $('cad-summary').textContent=`${report.bodies.length} 个封闭实体，${report.valid_bodies} 个通过几何有效性检查；各实体体积之和 ${number(report.sum_body_volume_mm3)} mm³（未扣除重叠）。`;
  $('cad-pair-controls').hidden=false;
  if(!pair){
   for(const id of ['cad-body-a','cad-body-b'])$(id).replaceChildren(...report.bodies.map(body=>new Option(`${body.name} · ${number(body.volume_mm3)} mm³${body.valid?'':' · 无效'}`,body.id)));
   if(report.bodies.length>1)$('cad-body-b').selectedIndex=1;
   $('cad-result').textContent=report.bodies.length>1?'选择两个原始实体进行检查。':'只有一个封闭实体，可查看体积；不能执行实体对比。';
  }else{
   const p=report.pair,labels={separate:'相互分离',overlap:'存在体积重叠',touching_or_within_tolerance:'接触或处于判断阈值内'};
   $('cad-result').textContent=`${labels[p.state]}。最短距离 ${number(p.minimum_distance_mm)} mm；相交体积 ${number(p.intersection_volume_mm3)} mm³。判断阈值 ${p.distance_threshold_mm} mm / ${p.volume_threshold_mm3} mm³。`;
   $('cad-result').dataset.gapMm=p.minimum_distance_mm;$('cad-result').dataset.overlapMm3=p.intersection_volume_mm3;
  }
 }catch(error){if(token===cadToken){if(pair)$('cad-result').textContent='检查失败：'+error.message;else $('cad-summary').textContent='读取失败：'+error.message;}throw error;}
 finally{if(token===cadToken){$('cad-body-a').disabled=false;$('cad-body-b').disabled=false;$('cad-scan').disabled=false;$('cad-compare').disabled=!cadReport||$('cad-body-a').value===$('cad-body-b').value;}}
}
$('cad-scan').onclick=guarded(()=>cadRequest(null));
$('cad-compare').onclick=guarded(()=>cadRequest({a:$('cad-body-a').value,b:$('cad-body-b').value}));
$('cad-export').onclick=()=>{
 if(!cadReport)return;const data={...cadReport,source_name:activeAsset?.name,asset_id:activeAsset?.id};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='cad-inspection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};

function updateGenerationOptions(){
 const mode=$('generation-mesh-mode').value,limits={standard:300000,parts:15000,detail:30000};
 $('generation-polycount').max=limits[mode];
 const hints={standard:'标准模式留空保留供应商默认；设置目标面数时启用三角网格重建，范围 100–300000。',parts:'T2 使用 Smart Topology，范围 100–15000，留空默认 4000。分件取决于供应商结果，不保证可制造 CAD 零件。',detail:'T2.5 使用 Smart Topology，范围 100–30000，留空默认 15000。拓扑细节不等于工程精度。'};
 $('generation-option-hint').textContent=hints[mode]+' 这些选项可能影响费用和耗时，以供应商账户为准；新模式尚未真实推理验证。';
 $('model-prompt').maxLength=providerAdapter==='meshy'&&!$('model-image').files[0]?800:4000;
}
$('generation-mesh-mode').onchange=updateGenerationOptions;$('model-image').onchange=updateGenerationOptions;

$('empty-upload').onclick=()=>$('upload-model').click();
$('empty-demo').onclick=()=>$('view-current').click();
document.querySelectorAll('[data-inspector-target]').forEach(button=>{
 button.onclick=()=>{const heading=$(button.dataset.inspectorTarget);heading.scrollIntoView({block:'start',behavior:'auto'});heading.focus({preventScroll:true});};
});
