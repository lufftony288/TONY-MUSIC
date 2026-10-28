"""STEP-to-GLB conversion in a bounded child process; originals remain untouched."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

CONVERSION_SLOT = threading.BoundedSemaphore(1)
MAX_PREVIEW_BYTES = 50 * 1024 * 1024


class StepUnavailable(RuntimeError):
    pass


def convert_step(data):
    if importlib.util.find_spec('OCP') is None:
        raise StepUnavailable('STEP 转换依赖未安装，请使用项目虚拟环境并安装 requirements-cad.txt')
    if not CONVERSION_SLOT.acquire(blocking=False):
        raise StepUnavailable('正在转换另一个 STEP 文件，请稍后重试上传')
    try:
        with tempfile.TemporaryDirectory(prefix='form-step-') as directory:
            source = Path(directory) / 'source.step'
            target = Path(directory) / 'preview.glb'
            report = Path(directory) / 'report.json'
            source.write_bytes(data)
            try:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                         str(source), str(target), str(report)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=60, check=False)
            except subprocess.TimeoutExpired:
                raise ValueError('STEP 转换超过 60 秒，请简化装配或拆分文件后重试') from None
            if result.returncode != 0 or not target.is_file():
                message = 'STEP 转换失败：文件可能损坏、包含不支持的几何或超出资源限制'
                if report.is_file():
                    message = json.loads(report.read_text()).get('error',message)
                raise ValueError(message)
            if target.stat().st_size > MAX_PREVIEW_BYTES:
                raise ValueError('STEP 预览超过 50MB，请简化模型后重试')
            return target.read_bytes()
    finally:
        CONVERSION_SLOT.release()


def worker(source, target):
    # OCCT native readers run outside the HTTP process; bound native CPU/file usage.
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (50, 55))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PREVIEW_BYTES + 1024, MAX_PREVIEW_BYTES + 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_LabelSequence
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRep import BRep_Tool
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    from OCP.Message import Message_ProgressRange

    document = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise ValueError('无法读取 STEP：请上传完整的 ISO-10303-21 文件')
    # STEP units are transferred into millimetres; OCCT's GLB writer converts mm to m.
    reader.ChangeReader().SetSystemLengthUnit(1.0)
    if not reader.Transfer(document):
        raise ValueError('STEP 几何转入失败')
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    if not roots.Length():
        raise ValueError('STEP 中没有可显示的几何对象')
    triangles = 0
    for i in range(1, roots.Length() + 1):
        shape = tool.GetShape_s(roots.Value(i))
        mesher = BRepMesh_IncrementalMesh(shape, 0.1, False, 0.3, False)
        if not mesher.IsDone():
            raise ValueError('STEP 曲面网格化失败')
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(explorer.Current()), TopLoc_Location())
            if triangulation:
                triangles += triangulation.NbTriangles()
            if triangles > 1_000_000:
                raise ValueError('STEP 预览超过 100 万三角面，请简化模型后重试')
            explorer.Next()
    if not triangles:
        raise ValueError('STEP 不含可显示的曲面；暂不支持仅有线框的 STEP')
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(target)), True)
    writer.SetMergeFaces(True)
    writer.SetParallel(False)
    writer.SetToEmbedTexturesInGlb(True)
    if not writer.Perform(document, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()):
        raise ValueError('STEP 三维预览导出失败')


if __name__ == '__main__':
    source, target, report = map(Path, sys.argv[1:])
    try:
        worker(source, target)
        report.write_text(json.dumps({'ok': True}))
    except Exception as exc:
        # Known validation messages are concise; never return native parser traces to clients.
        message = str(exc) if isinstance(exc, ValueError) else 'STEP 内核转换失败，请检查文件完整性或安装依赖'
        report.write_text(json.dumps({'error': message}, ensure_ascii=False))
        sys.exit(1)
