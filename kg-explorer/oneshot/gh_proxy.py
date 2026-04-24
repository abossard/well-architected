#!/usr/bin/env python3
"""Minimal OpenAI-compatible proxy that routes to GitHub Models API.

NOT LiteLLM. Just a tiny FastAPI-free proxy using aiohttp.
Routes /v1/chat/completions and /v1/embeddings to models.inference.ai.azure.com
using the gh CLI token for auth.

Usage:
    python3 gh_proxy.py          # starts on port 11435
    python3 gh_proxy.py 8080     # starts on custom port
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

UPSTREAM = "https://models.inference.ai.azure.com"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 11435
MAX_RETRIES = 5


def get_gh_token() -> str:
    """Get GitHub token from gh CLI."""
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Failed to get gh token. Run 'gh auth login' first.")
    return result.stdout.strip()


GH_TOKEN = get_gh_token()


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # compact logging
        sys.stderr.write(f"[proxy] {args[0]}\n")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        # Map paths
        path = self.path
        if path not in ("/v1/chat/completions", "/v1/embeddings",
                        "/chat/completions", "/embeddings"):
            self.send_error(404, f"Unknown path: {path}")
            return

        upstream_path = path.replace("/v1/", "/")
        upstream_url = f"{UPSTREAM}{upstream_path}"

        try:
            # Retry with backoff on rate limits
            for attempt in range(MAX_RETRIES):
                req = Request(
                    upstream_url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {GH_TOKEN}",
                    },
                    method="POST",
                )
                try:
                    with urlopen(req) as resp:
                        resp_body = resp.read()
                        self.send_response(resp.status)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp_body)))
                        self.end_headers()
                        self.wfile.write(resp_body)
                        return
                except HTTPError as e:
                    if e.code == 429 and attempt < MAX_RETRIES - 1:
                        retry_after = min(int(e.headers.get("Retry-After", 2 ** attempt)), 30)
                        sys.stderr.write(f"[proxy] Rate limited, waiting {retry_after}s (attempt {attempt+1})\n")
                        time.sleep(retry_after)
                        continue
                    raise
        except HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err_body)

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            upstream_url = f"{UPSTREAM}/models"
            req = Request(upstream_url, headers={"Authorization": f"Bearer {GH_TOKEN}"})
            try:
                with urlopen(req) as resp:
                    resp_body = resp.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
            except HTTPError as e:
                self.send_error(e.code, str(e))
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)


def main():
    server = HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"GitHub Models proxy running on http://127.0.0.1:{PORT}")
    print(f"  Chat:       POST /v1/chat/completions")
    print(f"  Embeddings: POST /v1/embeddings")
    print(f"  Models:     GET  /v1/models")
    print(f"  Upstream:   {UPSTREAM}")
    server.serve_forever()


if __name__ == "__main__":
    main()
