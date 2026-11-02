"""Owner-only Tailscale Serve gateway. Mission Control stays on loopback.

Serve must target this gateway, never Mission Control directly. Identity headers
are trusted only on this loopback listener, behind the local Tailscale daemon.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):return None


class PhoneServer(ThreadingHTTPServer):
    daemon_threads=True

    def __init__(self, address, origin, login, upstream_port=8765):
        parsed=urlparse(origin)
        if (address[0]!='127.0.0.1' or parsed.scheme!='https' or not parsed.hostname
                or not parsed.hostname.endswith('.ts.net') or parsed.username or parsed.password
                or parsed.path not in ('','/') or parsed.query or parsed.fragment
                or not login or '@' not in login or not 1<=upstream_port<=65535):
            raise ValueError('Use a loopback gateway, exact HTTPS Tailscale origin and owner login.')
        self.origin='https://'+parsed.netloc.lower()
        self.owner=login.casefold()
        self.upstream='http://127.0.0.1:'+str(upstream_port)
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
        super().__init__(address,PhoneHandler)


class PhoneHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def reject(self,status,message):
        body=json.dumps({'error':message}).encode()
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def forward(self):
        if (self.client_address[0]!='127.0.0.1'
                or self.headers.get('Tailscale-User-Login','').casefold()!=self.server.owner
                or self.headers.get('Host') not in {urlparse(self.server.origin).netloc, f'127.0.0.1:{self.server.server_port}'}):
            return self.reject(403,'Open the private Lima link through your own Tailscale account.')
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return self.reject(403,'Open Lima directly.')
        if not self.path.startswith('/') or self.path.startswith('//') or '\\' in self.path or '\r' in self.path or '\n' in self.path:
            return self.reject(400,'Invalid local path.')
        if urlparse(self.path).path in {'/api/google-client','/api/google-connect','/google/callback'}:
            return self.reject(403,'Set up Google on the Lima computer. Existing connections work on your phone.')
        data=None
        if self.command=='POST':
            if self.headers.get('Origin')!=self.server.origin:return self.reject(403,'Use this private Lima window.')
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.reject(400,'Invalid request length.')
            if not 0<length<=1_000_000 or self.headers.get('Transfer-Encoding'):return self.reject(413,'Request is too large.')
            data=self.rfile.read(length)
        headers={key:self.headers[key] for key in ('X-Lima-Token','Content-Type','Sec-Fetch-Site') if key in self.headers}
        if self.command=='POST':headers['Origin']=self.server.upstream
        request=Request(self.server.upstream+self.path,data=data,headers=headers,method=self.command)
        try:response=self.server.opener.open(request,timeout=90)
        except HTTPError as error:response=error
        except (URLError,TimeoutError,OSError):return self.reject(502,'Lima is unavailable. Keep its computer awake and running.')
        with response:
            body=response.read(40_000_001)
            if len(body)>40_000_000:return self.reject(502,'Response is too large for phone access.')
            self.send_response(response.code)
            for key in ('Content-Type','Content-Disposition','Cache-Control','Content-Security-Policy','X-Content-Type-Options','Referrer-Policy'):
                if key in response.headers:self.send_header(key,response.headers[key])
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

    do_GET=forward
    do_POST=forward


def main():
    parser=argparse.ArgumentParser(description='Private owner-only Lima phone gateway')
    parser.add_argument('--origin',required=True);parser.add_argument('--login',required=True)
    parser.add_argument('--port',type=int,default=8768);parser.add_argument('--upstream-port',type=int,default=8765)
    args=parser.parse_args()
    server=PhoneServer(('127.0.0.1',args.port),args.origin,args.login,args.upstream_port)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
