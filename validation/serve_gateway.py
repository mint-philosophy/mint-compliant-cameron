#!/usr/bin/env python3
"""
Gateway reverse proxy for the v4 review system.
Routes /review/* -> :8000 and /eval/* -> :8001.
Landing page at /.

Run on port 8080. Expose via ngrok for remote access.
"""
from __future__ import annotations

import http.server
import urllib.request
import urllib.error

PORT = 8080
ROUTES = {
    "/review": "http://localhost:8000",
    "/eval": "http://localhost:8001",
}

FORWARDED_HEADERS = (
    "Content-Type",
    "Content-Length",
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
)

LANDING_HTML = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>v4 Review System</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f8f9fa;
    color: #1a1a1a;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 2rem;
  }
  .container {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    padding: 3rem;
    max-width: 480px;
    width: 100%;
    text-align: center;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
  }
  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }
  p { font-size: 0.875rem; color: #6b7280; margin-bottom: 2rem; }
  .links { display: flex; flex-direction: column; gap: 1rem; }
  a {
    display: block;
    padding: 1rem 1.5rem;
    border: 2px solid #e5e7eb;
    border-radius: 12px;
    text-decoration: none;
    color: #1a1a1a;
    font-weight: 600;
    font-size: 1rem;
    transition: all 0.15s;
  }
  a:hover { border-color: #2563eb; background: #dbeafe; color: #2563eb; }
  .desc { font-size: 0.75rem; color: #6b7280; font-weight: 400; margin-top: 0.25rem; }
</style>
</head>
<body>
<div class="container">
  <h1>v4 Review System</h1>
  <p>Compliance Overspill &mdash; Multi-Reviewer Review</p>
  <div class="links">
    <a href="/review/">
      Case Review
      <div class="desc">Review generated cases against gate results (pass/fail)</div>
    </a>
    <a href="/eval/">
      Evaluation Review
      <div class="desc">Review LLM judge evaluations of model responses (category coding)</div>
    </a>
  </div>
</div>
</body>
</html>
"""


class GatewayHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_OPTIONS(self):
        self._proxy("OPTIONS")

    def _proxy(self, method: str):
        # Landing page
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(LANDING_HTML)))
            self.end_headers()
            self.wfile.write(LANDING_HTML)
            return

        # Route matching
        for prefix, upstream in ROUTES.items():
            if self.path.startswith(prefix):
                # Build upstream URL: strip prefix, forward the rest
                remainder = self.path[len(prefix):]
                if not remainder:
                    remainder = "/"
                upstream_url = upstream + remainder

                # Read request body if present
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length) if content_length > 0 else None

                try:
                    req = urllib.request.Request(
                        upstream_url,
                        data=body,
                        method=method,
                    )
                    # Forward Content-Type
                    ct = self.headers.get("Content-Type")
                    if ct:
                        req.add_header("Content-Type", ct)

                    with urllib.request.urlopen(req, timeout=30) as resp:
                        resp_body = resp.read()
                        self.send_response(resp.status)
                        for header in FORWARDED_HEADERS:
                            val = resp.getheader(header)
                            if val:
                                self.send_header(header, val)
                        if not resp.getheader("Access-Control-Allow-Origin"):
                            self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(resp_body)
                except urllib.error.HTTPError as e:
                    resp_body = e.read()
                    self.send_response(e.code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(resp_body)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    msg = b"Gateway error"
                    self.send_response(502)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(msg)
                return

        self.send_error(404, "Not found")

    def log_message(self, format, *args):
        msg = args[0] if args else ""
        if "/api/" in str(msg) or self.path == "/":
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Gateway at http://localhost:{PORT}")
    print(f"  /review/* -> http://localhost:8000")
    print(f"  /eval/*   -> http://localhost:8001")
    print("Press Ctrl+C to stop.\n")
    http.server.HTTPServer.allow_reuse_address = True
    with http.server.HTTPServer(("", PORT), GatewayHandler) as srv:
        srv.serve_forever()
