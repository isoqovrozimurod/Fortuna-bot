from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

class SimpleHTTP(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is running! Fortuna-bot active.")

def run():
    # Render 0.0.0.0 adresida va 8080 (yoki 10000) portida ishlashni kutadi
    server_address = ('0.0.0.0', 8080)
    httpd = HTTPServer(server_address, SimpleHTTP)
    print("Web server started on port 8080")
    httpd.serve_forever()

def keep_alive():
    t = Thread(target=run)
    t.start()
