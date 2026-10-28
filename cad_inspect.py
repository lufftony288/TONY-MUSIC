"""Read-only STEP B-rep inspection, isolated from the web process."""
import os
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from step_import import CONVERSION_SLOT,StepUnavailable


def inspect_step(data, request=None):
    request={} if request is None else request
    if not isinstance(request,dict) or set(request)-{'a','b'}:
        raise ValueError('CAD 检查参数无效')
    if bool('a' in request)!=bool('b' in request):
        raise ValueError('请选择两个 STEP 实体')
    if request:
        if any(not isinstance(request[k],str) or not re.fullmatch(r'solid-[0-9]{4}',request[k]) for k in ('a','b')):
            raise ValueError('STEP 实体编号无效')
        if request['a']==request['b']:
            raise ValueError('请选择两个不同的 STEP 实体')
    if importlib.util.find_spec('OCP') is None:
        raise StepUnavailable('CAD 内核未安装，请使用项目虚拟环境')
    if not CONVERSION_SLOT.acquire(blocking=False):
        raise StepUnavailable('CAD 内核正在处理另一个请求，请稍后重试')
    try:
        with tempfile.TemporaryDirectory(prefix='form-cad-inspect-') as folder:
            folder=Path(folder);source=folder/'source.step';params=folder/'request.json';result=folder/'result.json'
            source.write_bytes(data);params.write_text(json.dumps(request))
            try:
                process=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(source),str(params),str(result)],
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
            except subprocess.TimeoutExpired:
                raise ValueError('B-rep 检查超过 60 秒，请缩小装配规模后重试') from None
            if not result.is_file() or result.stat().st_size>2_000_000:
                raise ValueError('B-rep 检查未完成，可能超出资源限制')
            report=json.loads(result.read_text())
            if process.returncode or report.get('error'):
                raise ValueError(report.get('error','B-rep 检查失败'))
            report['source_sha256']=hashlib.sha256(data).hexdigest()
            return report
    finally:
        CONVERSION_SLOT.release()


def worker(source,request):
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_LabelSequence,TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    doc=TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    reader=STEPCAFControl_Reader();reader.SetNameMode(True)
    if reader.ReadFile(str(source))!=IFSelect_RetDone:raise ValueError('无法读取原始 STEP')
    reader.ChangeReader().SetSystemLengthUnit(1.0)
    if not reader.Transfer(doc):raise ValueError('STEP B-rep 转入失败')
    tool=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());roots=TDF_LabelSequence();tool.GetFreeShapes(roots)
    solids=[]
    def name(label):
        attr=TDataStd_Name()
        return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(),attr) else '未命名实体'
    def visit(label,location,path,depth=0):
        if depth>128:raise ValueError('STEP 层级超过 128 层检查上限')
        current_name=name(label);definition=label
        if tool.IsReference_s(label):
            definition=TDF_Label()
            if not tool.GetReferredShape_s(label,definition):raise ValueError('STEP 引用实体缺失')
            location=location.Multiplied(tool.GetLocation_s(label))
        path=path+[current_name]
        if tool.IsAssembly_s(definition):
            children=TDF_LabelSequence();tool.GetComponents_s(definition,children)
            for i in range(1,children.Length()+1):visit(children.Value(i),location,path,depth+1)
        else:
            shape=tool.GetShape_s(definition).Moved(location)
            explorer=TopExp_Explorer(shape,TopAbs_SOLID);index=0
            while explorer.More():
                index+=1
                if len(solids)>=1000:raise ValueError('B-rep 检查最多支持 1000 个实体')
                solids.append((TopoDS.Solid_s(explorer.Current()),'/'.join(path),index));explorer.Next()
    for i in range(1,roots.Length()+1):visit(roots.Value(i),TopLoc_Location(),[])
    if not solids:raise ValueError('STEP 没有可检查的封闭实体；曲面/线框预览不等于实体')
    bodies=[]
    for i,(shape,path,index) in enumerate(solids):
        props=GProp_GProps();BRepGProp.VolumeProperties_s(shape,props)
        area=GProp_GProps();BRepGProp.SurfaceProperties_s(shape,area)
        box=Bnd_Box();BRepBndLib.AddOptimal_s(shape,box,False,False);bounds=box.Get()
        bodies.append({'id':f'solid-{i+1:04}','name':path+f' · 实体 {index}',
                       'valid':bool(BRepCheck_Analyzer(shape).IsValid()),'volume_mm3':abs(props.Mass()),
                       'area_mm2':area.Mass(),'bounds_min_mm':list(bounds[:3]),'bounds_max_mm':list(bounds[3:]),'bounds_mm':[bounds[j+3]-bounds[j] for j in range(3)]})
    report={'method':'Open Cascade B-rep','length_unit':'mm','volume_unit':'mm3',
            'bodies':bodies,'valid_bodies':sum(b['valid'] for b in bodies),
            'sum_body_volume_mm3':sum(b['volume_mm3'] for b in bodies),
            'note':'基于原始 STEP，受模型几何公差与内核算法影响；体积之和不扣除重叠，不是制造认证。'}
    if request:
        ids={b['id']:i for i,b in enumerate(bodies)}
        if request['a'] not in ids or request['b'] not in ids:raise ValueError('选择的 STEP 实体不存在')
        ia,ib=ids[request['a']],ids[request['b']]
        if not bodies[ia]['valid'] or not bodies[ib]['valid']:raise ValueError('所选实体未通过几何有效性检查，不能可靠执行干涉计算')
        a,b=solids[ia][0],solids[ib][0]
        distance=BRepExtrema_DistShapeShape(a,b);distance.Perform()
        if not distance.IsDone():raise ValueError('实体最短距离计算失败')
        common=BRepAlgoAPI_Common(a,b)
        if not common.IsDone():raise ValueError('实体相交运算失败；不能据此认定没有干涉')
        props=GProp_GProps();BRepGProp.VolumeProperties_s(common.Shape(),props)
        overlap=abs(props.Mass());gap=max(0,distance.Value())
        state='overlap' if overlap>1e-6 else 'separate' if gap>1e-6 else 'touching_or_within_tolerance'
        report['pair']={'a':request['a'],'b':request['b'],'minimum_distance_mm':gap,
                        'intersection_volume_mm3':overlap,'state':state,
                        'distance_threshold_mm':1e-6,'volume_threshold_mm3':1e-6}
    return report


if __name__=='__main__':
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(50,55));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_FSIZE,(2_000_000,2_000_000))
    source,params,target=map(Path,sys.argv[1:])
    try:
        result=worker(source,json.loads(params.read_text()))
        target.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        error=str(exc) if isinstance(exc,ValueError) else 'B-rep 内核检查失败，请检查模型有效性'
        target.write_text(json.dumps({'error':error},ensure_ascii=False));sys.exit(1)
