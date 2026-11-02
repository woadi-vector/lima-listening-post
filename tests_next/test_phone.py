import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from lima_next.server import MissionServer
from lima_next.phone import PhoneServer


class PhoneTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.main=MissionServer(('127.0.0.1',0),Path(self.folder.name)/'ws.db')
        self.origin='https://lima.test.ts.net'
        self.phone=PhoneServer(('127.0.0.1',0),self.origin,'owner@example.com',self.main.server_port)
        self.threads=[]
        for server in (self.main,self.phone):
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.threads.append(thread)
        self.opener=build_opener(ProxyHandler({}))

    def tearDown(self):
        for server in (self.phone,self.main):server.shutdown();server.server_close()
        for thread in self.threads:thread.join()
        self.folder.cleanup()

    def request(self,path,payload=None,**changes):
        headers={'Host':'lima.test.ts.net','Tailscale-User-Login':'owner@example.com','Origin':self.origin,
                 'X-Lima-Token':self.main.token,'Content-Type':'application/json',**changes}
        return self.opener.open(Request('http://127.0.0.1:'+str(self.phone.server_port)+path,
            data=json.dumps(payload).encode() if payload is not None else None,headers=headers))

    def test_private_owner_can_bootstrap_and_use_same_origin_actions(self):
        with self.request('/api/session') as response:self.assertEqual(json.load(response)['token'],self.main.token)
        with self.request('/api/projects',{'name':'Phone project'}) as response:self.assertTrue(json.load(response)['id'])
        with self.request('/day.js') as response:self.assertEqual(response.code,200)

    def test_wrong_owner_missing_identity_cross_site_and_missing_token_are_denied(self):
        for changes in ({'Tailscale-User-Login':'other@example.com'},{'Tailscale-User-Login':''},
                        {'Host':'evil.example'},{'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'},
                        {'X-Lima-Token':''}):
            with self.assertRaises(HTTPError) as caught:self.request('/api/projects',{'name':'Denied'},**changes)
            self.assertEqual(caught.exception.code,403)
        # Some proxies rewrite Host. The identity check must still run in that case.
        with self.assertRaises(HTTPError) as caught:self.request('/api/session',**{'Host':f'127.0.0.1:{self.phone.server_port}','Tailscale-User-Login':'other@example.com'})
        self.assertEqual(caught.exception.code,403)

    def test_google_setup_and_external_targets_are_denied(self):
        for path in ('/api/google-connect','/api/google-client','/google/callback','//evil.example/'):
            with self.assertRaises(HTTPError):self.request(path,{})

    def test_configuration_cannot_expose_a_public_or_http_gateway(self):
        for origin in ('http://lima.test.ts.net','https://example.com','https://user@lima.test.ts.net','https://lima.test.ts.net/path'):
            with self.assertRaises(ValueError):PhoneServer(('127.0.0.1',0),origin,'owner@example.com')
