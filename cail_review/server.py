"""Stateless inference endpoint. Does not log or persist sealed contracts."""
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cli import make_client
from .pipeline import review_llm, review_rules, to_submission
from .schema import Contract, FormatError


def make_server(args):
    token = os.getenv("CAIL_SERVICE_TOKEN", "")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ValueError("对外监听须设置 CAIL_SERVICE_TOKEN，并通过 HTTPS 反向代理发布")
    # Validate configuration before accepting traffic. Each request gets its own client.
    if args.backend == "llm":
        make_client(args)
    concurrency = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(200 if self.path == "/health" else 404, {"status": "ok"} if self.path == "/health" else {"error": "not found"})

        def do_POST(self):
            if self.path != "/review":
                return self.reply(404, {"error": "not found"})
            if token and not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"), ("Bearer " + token).encode("utf-8")):
                return self.reply(401, {"error": "unauthorized"})
            if not concurrency.acquire(blocking=False):
                return self.reply(429, {"error": "busy"})
            try:
                self.connection.settimeout(30)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self.reply(400, {"error": "invalid request size"})
                if not 0 < size <= 2_000_000:
                    return self.reply(400, {"error": "invalid request size"})
                try:
                    contract = Contract.parse(json.loads(self.rfile.read(size)))
                except (ValueError, UnicodeDecodeError):
                    return self.reply(400, {"error": "invalid input"})
                result = review_rules(contract) if args.backend == "rules" else review_llm(contract, make_client(args), not args.no_verify)
                loc, rev = to_submission(contract, result)
                if not result["issues"]:
                    loc = []
                self.reply(200, {"contract_id": contract.contract_id, "localization": loc, "revisions": rev})
            except FormatError:
                self.reply(503, {"error": "invalid model output"})
            except Exception:
                self.reply(503, {"error": "inference unavailable"})
            finally:
                concurrency.release()

    return ThreadingHTTPServer((args.host, args.port), Handler)


def serve(args):
    server = make_server(args)
    print(f"Listening on {args.host}:{server.server_port}; POST /review; GET /health", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
