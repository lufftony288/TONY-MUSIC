import os
import json
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import server

class Quiet(server.Handler):
    def log_message(self,*args):pass

class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        db=patch.object(server,'DB',Path(self.temp.name)/'db.sqlite3');db.start();self.addCleanup(db.stop)
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),Quiet)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.request(method,path,body=body,headers=headers or {});r=c.getresponse();result=(r.status,r.read());c.close();return result
    def test_cross_origin_write_does_not_mutate_project(self):
        status,_=self.request('POST','/api/project',b'{}',{'Origin':'https://unrelated.invalid','Content-Type':'application/json'})
        self.assertEqual(status,403)
        with server.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM projects').fetchone()[0],0)
    def test_declared_oversize_is_rejected_before_body_read(self):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        c.putrequest('POST','/api/models');c.putheader('Content-Length',str(50*1024*1024+1));c.endheaders()
        self.assertEqual(c.getresponse().status,400);c.close()
    def test_malformed_inputs_do_not_create_assets(self):
        for path,body,headers in [('/api/project',b'{bad',{}),('/api/models',b'broken',{'X-Model-Name':'bad.glb'}),('/api/models',b'anything',{'X-Model-Name':'bad.exe'})]:
            self.assertEqual(self.request('POST',path,body,headers)[0],400)
        self.assertEqual(self.request('GET','/api/models')[1],b'[]')
    def test_file_routes_do_not_escape_whitelisted_paths(self):
        for path in ['/vendor/../../server.py','/api/models/../../server.py/content','/static/../.data/projects.sqlite3']:
            self.assertEqual(self.request('GET',path)[0],404)

    def test_configured_https_origin_and_spoofed_proxy_header(self):
        body=json.dumps(server.demo()).encode()
        with patch.dict(os.environ,{'FORM_PUBLIC_ORIGIN':'https://form.example.test'}):
            self.assertEqual(self.request('POST','/api/analyze',body,{'Origin':'https://form.example.test'})[0],200)
            self.assertEqual(self.request('POST','/api/analyze',body,{'Origin':'https://form.example.test.evil.invalid'})[0],403)
        with patch.dict(os.environ,{'FORM_PUBLIC_ORIGIN':''}):
            self.assertEqual(self.request('POST','/api/analyze',body,{'Origin':'https://form.example.test','X-Forwarded-Host':'form.example.test','X-Forwarded-Proto':'https'})[0],403)
