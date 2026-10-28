const $=id=>document.getElementById(id);
let project,report,selected,timer;
function status(text){$('status').textContent=text;}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
function stop(){clearInterval(timer);timer=null;$('play').textContent='▶ 播放装配';}
function vecInputs(id,values){$(id).replaceChildren(...values.map(v=>{const input=document.createElement('input');input.type='number';input.step='any';input.value=v;input.required=true;return input;}));}
function editor(){showPlanning();const p=project.parts.find(p=>p.id===selected);$('editor').hidden=!p;if(!p)return;$('part-name').value=p.name;$('material').value=p.material||'';vecInputs('sizes',p.size);vecInputs('positions',p.position);vecInputs('rotations',p.rotation||[0,0,0]);$('shape').value=p.shape||'box';$('dependencies').replaceChildren(...project.parts.filter(x=>x.id!==p.id).map(x=>{const o=new Option(x.name,x.id);o.selected=(p.depends_on||[]).includes(x.id);return o;}));}
function list(){ $('name').value=project.name;$('count').textContent=project.parts.length;$('parts').replaceChildren(...project.parts.map(p=>{const b=document.createElement('button');b.className='part'+(p.id===selected?' selected':'');const icon=document.createElement('span');icon.className='cube';icon.textContent='◇';const info=document.createElement('span');info.textContent=p.name;const sub=document.createElement('small');sub.textContent=p.size.map(v=>Number(v.toFixed(3))).join(' × ')+' mm';info.append(sub);b.append(icon,info);b.onclick=()=>{selected=p.id;list();editor();draw();};return b;}));}
function draw(){
 if(!report?.meshes)return;
 const step=+$('step').value,visible=new Set(report.order.slice(0,step));
 $('step-label').textContent=step===report.order.length?'完整装配':`装配步骤 ${step} / ${report.order.length}`;
 const scene=$('scene'),ns='http://www.w3.org/2000/svg';scene.replaceChildren();
 const faces=[],projected=[];
 for(const p of project.parts.filter(p=>visible.has(p.id))){
  const m=report.meshes[p.id],dz=$('explode').checked?report.order.indexOf(p.id)*Math.min(20,400/report.order.length):0;
  const vertices=m.vertices.map(([x,y,z])=>[x,y,z+dz]);
  const points=vertices.map(([x,y,z])=>[(x-y)*.866,(x+y)*.5-z]);projected.push(...points);
  for(const face of m.faces){
   const [a,b,c]=face.map(i=>vertices[i]);
   const u=b.map((v,i)=>v-a[i]),v=c.map((x,i)=>x-a[i]);
   const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
   if(n.reduce((a,b)=>a+b,0)<=1e-8)continue;
   const light=Math.max(.35,Math.min(.95,.55+(n[2]+n[0]*.4)/Math.hypot(...n)*.3));
   faces.push({p,points:face.map(i=>points[i]),depth:face.reduce((s,i)=>s+vertices[i].reduce((a,b)=>a+b,0),0)/face.length,light});
  }
 }
 if(!projected.length)return;
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 for(const [x,y] of projected){minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
 const scale=Math.min(740/(maxX-minX||1),500/(maxY-minY||1));
 function pt([x,y]){return [(x-(minX+maxX)/2)*scale+450,(y-(minY+maxY)/2)*scale+325];}
 faces.sort((a,b)=>a.depth-b.depth).forEach(({p,points,light})=>{
  const poly=document.createElementNS(ns,'polygon');poly.setAttribute('points',points.map(v=>pt(v).join(',')).join(' '));
  const base=p.id===selected?[180,225,145]:[120,157,172];
  poly.setAttribute('fill',`rgb(${base.map(x=>Math.round(x*light)).join(',')})`);poly.setAttribute('stroke','#17222b');poly.setAttribute('stroke-width','.65');
  poly.setAttribute('tabindex','0');poly.setAttribute('aria-label',p.name);
  const title=document.createElementNS(ns,'title');title.textContent=p.name;poly.append(title);
  poly.onclick=()=>{selected=p.id;list();editor();draw();};poly.onkeydown=e=>{if(e.key==='Enter')poly.onclick();};scene.append(poly);
 });
}
async function refresh(candidate=project){const result=await api('/api/analyze',candidate);project=candidate;report=result;if(!project.parts.some(p=>p.id===selected))selected=project.parts[0].id;stop();$('step').max=report.order.length;$('step').value=report.order.length;list();editor();draw();$('report').textContent=`✓ 依赖关系无循环 · ${report.order.length} 个装配步骤\n${report.collisions.length?'⚠ '+report.collisions.length+' 对包围盒可能重叠（需复核）':'✓ 包围盒粗检未发现重叠'}\n理论实体体积 ${(report.volume_mm3/1e6).toFixed(2)} L`;$('report').style.whiteSpace='pre-line';}
function run(fn){return async(...args)=>{try{await fn(...args);}catch(e){status('操作失败：'+e.message);}};}
$('editor').onsubmit=run(async e=>{e.preventDefault();const next=structuredClone(project),p=next.parts.find(p=>p.id===selected);p.name=$('part-name').value;p.material=$('material').value;p.size=[...$('sizes').children].map(x=>Number(x.value));p.position=[...$('positions').children].map(x=>Number(x.value));p.shape=$('shape').value;p.rotation=[...$('rotations').children].map(x=>Number(x.value));p.depends_on=[...$('dependencies').selectedOptions].map(x=>x.value);await refresh(next);status('属性已应用，请保存项目。');});
$('name').onchange=()=>{project.name=$('name').value;status('项目名称已修改，请保存。');};
$('add').onclick=run(async()=>{const next=structuredClone(project);const id=crypto.randomUUID();next.parts.push({id,name:'新零件',material:'未指定',size:[100,100,100],position:[700,0,0],depends_on:[]});selected=id;await refresh(next);status('已添加零件，请编辑属性并保存。');});
$('delete').onclick=run(async()=>{if(project.parts.some(p=>(p.depends_on||[]).includes(selected)))throw Error('其他零件依赖此零件，请先移除依赖');const next=structuredClone(project);next.parts=next.parts.filter(p=>p.id!==selected);await refresh(next);status('零件已删除，请保存。');});
$('save').onclick=run(async()=>{await api('/api/project',project);status('项目已保存到本地数据库。');});
$('step').oninput=()=>{stop();draw();};$('explode').onchange=draw;
$('play').onclick=()=>{if(timer){stop();return;}$('step').value=0;draw();$('play').textContent='Ⅱ 暂停';timer=setInterval(()=>{$('step').value=+$('step').value+1;draw();if(+$('step').value>=report.order.length)stop();},900);};
$('export').onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify(project,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='assembly.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
$('import').onclick=()=>$('file').click();$('file').onchange=run(async()=>{const file=$('file').files[0];if(!file)return;if(file.size>2_000_000)throw Error('文件大小超过 2MB');await refresh(JSON.parse(await file.text()));status('项目已导入并通过检查，请保存。');$('file').value='';});
run(async()=>{await refresh(await api('/api/project'));status('工作台已就绪 · 修改后请保存项目。');})();

$('generate').onclick=()=>$('generator').showModal();
$('close-generator').onclick=()=>$('generator').close();
$('generate-form').onsubmit=run(async e=>{e.preventDefault();const params=Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)]));const start=performance.now();await refresh(await api('/api/generate',params));$('generator').close();status(`已生成 ${project.parts.length} 个零件，用时 ${Math.round(performance.now()-start)} ms（本次生成及检查）。请保存项目。`);});
$('stl').onclick=run(async()=>{const data=await api('/api/stl',project);const u=URL.createObjectURL(new Blob([data.stl],{type:'model/stl'}));const a=document.createElement('a');a.href=u;a.download='assembly.stl';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);status('已导出 STL，多壳体几何，单位 mm；不代表可直接制造。');});

$('close-explorer').onclick=()=>$('explorer').close();
$('explore').onclick=()=>{
 const presets=Array.from({length:9},(_,i)=>({width:[400,600,800][i%3],height:[300,450,600][Math.floor(i/3)],depth:60,fins:12+i*4}));
 $('variants').replaceChildren(...presets.map((params,i)=>{
  const b=document.createElement('button');const title=document.createElement('strong');title.textContent=`方案 ${String(i+1).padStart(2,'0')}`;b.append(title);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 220 150');svg.setAttribute('aria-label','散热器模板预览');
  const w=params.width/5,h=params.height/5,x=(220-w)/2,y=(150-h)/2;
  function rect(a,c,d,e,fill){const r=document.createElementNS(ns,'rect');for(const [k,v] of Object.entries({x:a,y:c,width:d,height:e,fill}))r.setAttribute(k,v);svg.append(r);}
  rect(x,y,w,8,'#a6c6d0');rect(x,y+h-8,w,8,'#a6c6d0');
  for(let j=0;j<params.fins;j++)rect(x+(j+.36)*w/params.fins,y+8,w/params.fins*.28,h-16,'#7796a0');
  b.append(svg);const text=document.createElement('span');text.textContent=`${params.width} × ${params.height} × ${params.depth} mm · ${params.fins} 片`;b.append(text);
  b.onclick=run(async()=>{await refresh(await api('/api/generate',params));$('explorer').close();status(`已选择方案 ${i+1}；可编辑零件、检查装配并导出。请保存项目。`);});return b;
 }));$('explorer').showModal();
};

function showPlanning(){
 if(!report?.layers)return;
 const names=new Map(project.parts.map(p=>[p.id,p.name]));
 $('layers').replaceChildren(...report.layers.map((layer,i)=>{const li=document.createElement('li');li.textContent=`层 ${i+1}：${layer.map(id=>names.get(id)).join('、')}`;return li;}));
 const affected=new Set(),queue=[selected];
 while(queue.length){for(const child of report.dependents[queue.pop()]||[]){if(!affected.has(child)){affected.add(child);queue.push(child);}}}
 $('impact').textContent=`依赖规划共 ${report.layers.length} 层；同层可并行（未考虑工具、人员及物理可达性）。当前零件变更需复核 ${affected.size} 个后续零件。`;
 if(affected.size){const preview=[...affected].slice(0,12).map(id=>names.get(id)).join('、');$('impact').textContent+=' '+preview+(affected.size>12?'…':'');}
}

$('close-history').onclick=()=>$('history-dialog').close();
$('history').onclick=run(async()=>{
 const versions=await api('/api/history');
 $('history-list').replaceChildren(...versions.map(v=>{const b=document.createElement('button');b.textContent=`#${v.id} · ${v.name} · ${new Date(v.created_at.replace(' ','T')).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}`;b.onclick=run(async()=>{await refresh(await api(`/api/history/${v.id}`));$('history-dialog').close();status(`已载入版本 #${v.id}；保存后才更新当前项目。`);});return b;}));
 if(!versions.length)$('history-list').textContent='尚无已保存版本；请先保存项目。';
 $('history-dialog').showModal();
});

document.addEventListener('form:request-project',()=>document.dispatchEvent(new CustomEvent('form:project',{detail:{project,report}})));
