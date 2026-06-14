import http.server
import socketserver
import json
import hashlib
import threading
import os

PORT = 8000

class RequestHandler(http.server.BaseHTTPRequestHandler):
    store = {}
    next_code = 0

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            with open('index.html', 'rb') as f:
                self.wfile.write(f.read())
        elif self.path.startswith('/'):
            code = self.path[1:]
            if code in self.store:
                self.send_response(302)
                self.send_header('Location', self.store[code])
                self.end_headers()
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def do_POST(self):
        if self.path == '/api/shorten':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                url = data['url']
                if not (url.startswith('http://') or url.startswith('https://')):
                    self.send_response(400)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'Invalid URL')
                    return
                code = self.generate_code()
                self.store[code] = url
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'short_url': f'http://localhost:{PORT}/{code}', 'code': code}).encode())
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid JSON')
            except KeyError:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid URL')
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def generate_code(self):
        code = hashlib.sha256(str(self.next_code).encode()).hexdigest()[:6]
        self.next_code += 1
        return code

def make_server(port=0):
    return http.server.HTTPServer(('', port), RequestHandler)

if __name__ == '__main__':
    server = make_server(PORT)
    print(f'Server started on port {PORT}')
    server.serve_forever()
