"""Actual STEP B-rep and assembly fixtures written with the CAD kernel."""
from pathlib import Path
import tempfile
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorSurf
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Trsf, gp_Vec


def step_fixture(schema='AP214IS', assembly=True, instances=2, spacing=150, frame_offset=0):
    document=TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    tool=XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    if assembly:
        root=tool.NewShape();TDataStd_Name.Set_s(root,TCollection_ExtendedString('Fixture assembly'))
        frame=tool.NewShape();TDataStd_Name.Set_s(frame,TCollection_ExtendedString('Frame'))
        offset=gp_Trsf();offset.SetTranslation(gp_Vec(frame_offset,0,0))
        component=tool.AddComponent(root,frame,TopLoc_Location(offset))
        TDataStd_Name.Set_s(component,TCollection_ExtendedString('Frame'))
        part=tool.AddShape(BRepPrimAPI_MakeBox(100,50,25).Shape(),False)
        TDataStd_Name.Set_s(part,TCollection_ExtendedString('Base block'))
        for i in range(instances):
            x=i*spacing;name=['Left block','Right block'][i] if i<2 else f'Block {i+1:03}'
            transform=gp_Trsf();transform.SetTranslation(gp_Vec(x,0,0))
            instance=tool.AddComponent(frame,part,TopLoc_Location(transform))
            TDataStd_Name.Set_s(instance,TCollection_ExtendedString(name))
    else:
        part=tool.AddShape(BRepPrimAPI_MakeCylinder(20,80).Shape(),False)
        TDataStd_Name.Set_s(part,TCollection_ExtendedString('Cylinder'))
    colors=XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    colors.SetColor(part,Quantity_Color(.8,.2,.1,Quantity_TOC_RGB),XCAFDoc_ColorSurf)
    tool.UpdateAssemblies()
    writer=STEPCAFControl_Writer()
    old=Interface_Static.CVal_s('write.step.schema')
    try:
        assert Interface_Static.SetCVal_s('write.step.schema',schema)
        assert writer.Transfer(document,STEPControl_AsIs)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.step'
            assert writer.Write(str(path))==IFSelect_RetDone
            return path.read_bytes()
    finally:
        Interface_Static.SetCVal_s('write.step.schema',old)
