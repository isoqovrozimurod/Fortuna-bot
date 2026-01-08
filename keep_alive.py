import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

class SimpleHTTP(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Fortuna-bot is running and alive.")

    # Render ba’zan HEAD so‘rov yuboradi, uni ham ushlaymiz
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run():
    # Render qaysi port bersa, o‘shani ishlatamiz
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTP)
    print(f"Keep-alive server started on port {port}")
    server.serve_forever()

def keep_alive():
    Thread(target=run, daemon=True).start()
