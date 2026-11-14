"""PLACEHOLDER do back-end: responde {"status": "ok"} em GET /health. Substitua pelo real."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        corpo = json.dumps({"status": "ok", "origem": "placeholder do backend"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")  # só no placeholder
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


porta = int(os.getenv("PORT", "8028"))
print(f"placeholder no ar na porta {porta}", flush=True)
ThreadingHTTPServer(("0.0.0.0", porta), Handler).serve_forever()
