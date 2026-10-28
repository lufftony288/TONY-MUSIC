"""Small, independently constructed fixtures for actual loader tests."""
import json
import struct

OBJ = b'''o Base
v 0 0 0
v 1 0 0
v 0 1 0
f 1 2 3
o Cap
v 0 0 1
v 1 0 1
v 0 1 1
f 4 5 6
'''
STL = b'''solid triangle
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 1 0
 endloop
endfacet
endsolid triangle
'''
BINARY_STL = b'fixture'.ljust(80,b'\0') + struct.pack('<I12fH',1,0,0,1,0,0,0,1,0,0,0,1,0,0)


def glb(external=False):
    vertices=[0,0,0, 1,0,0, 0,1,0, 0,0,1]
    indices=[0,2,1, 0,1,3, 0,3,2, 1,2,3]
    binary=struct.pack('<12f12H',*vertices,*indices)
    document={
        'asset':{'version':'2.0'},'scene':0,
        'scenes':[{'name':'Assembly','nodes':[0]}],
        'nodes':[{'name':'Module','children':[1,2]}, {'name':'Base','mesh':0}, {'name':'Cap','mesh':0,'translation':[1.5,0,0]}],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0},'indices':1}]}],
        'buffers':[dict(byteLength=len(binary),**({'uri':'https://not-allowed.invalid/model.bin'} if external else {}))],
        'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':48},{'buffer':0,'byteOffset':48,'byteLength':24}],
        'accessors':[{'bufferView':0,'componentType':5126,'count':4,'type':'VEC3','min':[0,0,0],'max':[1,1,1]},
                     {'bufferView':1,'componentType':5123,'count':12,'type':'SCALAR'}]
    }
    text=json.dumps(document,separators=(',',':')).encode()
    text+=b' '*((-len(text))%4)
    chunks=struct.pack('<2I',len(text),0x4E4F534A)+text+struct.pack('<2I',len(binary),0x004E4942)+binary
    return struct.pack('<3I',0x46546C67,2,12+len(chunks))+chunks
