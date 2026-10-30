from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import hmac, sys

lines = Path(sys.argv[1] if len(sys.argv) > 1 else 'D:/DifyDemo/runtime/server.env').read_text(encoding='utf-8').splitlines()
token = next(line.split('=', 1)[1] for line in lines if line.startswith('POWERCONTEXT_SERVER_AUTH_TOKEN='))
allowed = {'/v1/scopes', '/v1/context/prepare', '/v1/memory/remember'}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(404)
    def do_POST(self):
        if self.path not in allowed:
            self.send_error(404)
            return
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
            self.send_error(401)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < size <= 65536:
            self.send_error(413)
            return
        req = Request('http://127.0.0.1:8017' + self.path, data=self.rfile.read(size), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
        try:
            result = urlopen(req, timeout=30)
        except HTTPError as error:
            result = error
        except Exception:
            self.send_error(502)
            return
        with result:
            payload = result.read()
            self.send_response(result.status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    def log_message(self, fmt, *args):
        print(self.command, self.path, flush=True)
if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8018), Handler).serve_forever()