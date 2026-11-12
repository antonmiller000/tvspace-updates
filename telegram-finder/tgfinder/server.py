"""Local web server: UI + JSON API. Binds to 127.0.0.1 only."""
from __future__ import annotations

import csv
import io
import json
import os
import pkgutil
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import PRESETS, Job
from .store import Store
from .tgapi import Tg, TgError


class App:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.store = Store(os.path.join(data_dir, "finder.sqlite"))
        self.tg = Tg(data_dir)
        self.jobs: dict[int, Job] = {}

    def job_view(self, row: dict) -> dict:
        live = self.jobs.get(row["id"])
        if live:
            row.update(status=live.status, stats=live.snapshot(), log=live.log[-80:])
        return row


class Handler(BaseHTTPRequestHandler):
    app: App = None
    server_version = "TelegramFinder/1.0"

    def log_message(self, *a):
        pass

    # ---- helpers
    def _send(self, code: int, body, ctype="application/json", headers: dict | None = None):
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "charset" not in ctype else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _local(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _body(self) -> dict:
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("JSON body required")
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _route(self, method: str):
        if not self._local():
            return self._send(403, {"error": "local access only"})
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            self._dispatch(method, url.path.rstrip("/") or "/", q)
        except (ValueError, KeyError, TgError) as e:
            self._send(400, {"error": str(e)})
        except BrokenPipeError:
            pass
        except Exception as e:  # keep the server alive
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")

    # ---- routes
    def _dispatch(self, method: str, path: str, q: dict):
        app = self.app
        if method == "GET" and path == "/":
            return self._send(200, pkgutil.get_data("tgfinder", "static/index.html"), "text/html")
        if path == "/api/presets":
            return self._send(200, PRESETS)
        if path == "/api/jobs" and method == "GET":
            return self._send(200, [app.job_view(j) for j in app.store.jobs()])
        if path == "/api/jobs" and method == "POST":
            b = self._body()
            allowed = ("query", "extra", "seeds", "preset", "kinds", "sources", "workers",
                       "depth", "history_pages", "minutes", "max_entities")
            job = Job(app.store, app.tg, **{k: b[k] for k in allowed if k in b})
            app.jobs[job.id] = job
            job.start()
            return self._send(200, {"id": job.id})

        m = re.match(r"^/api/jobs/(\d+)(?:/(\w+)(?:\.(\w+))?)?$", path)
        if m:
            jid, action, ext = int(m.group(1)), m.group(2), m.group(3)
            row = app.store.job(jid)
            if not row:
                return self._send(404, {"error": "no such search"})
            if method == "DELETE":
                if jid in app.jobs:
                    app.jobs.pop(jid).stop()
                app.store.delete_job(jid)
                return self._send(200, {"ok": True})
            if action is None:
                return self._send(200, app.job_view(row))
            if action == "stop" and method == "POST":
                if jid in app.jobs:
                    app.jobs[jid].stop()
                return self._send(200, {"ok": True})
            flt = dict(
                kinds=[k for k in q.get("kinds", "").split(",") if k] or None,
                relevant_only=q.get("all") != "1", text=q.get("q", ""),
                min_members=int(q.get("min_members") or 0), sort=q.get("sort", "score"))
            if action == "results":
                total, rows = app.store.entities(jid, limit=min(int(q.get("limit") or 200), 1000),
                                                 offset=int(q.get("offset") or 0), **flt)
                return self._send(200, {"total": total, "rows": rows})
            if action == "posts":
                total, rows = app.store.posts(jid, text=q.get("q", ""), channel=q.get("channel", ""),
                                              sort=q.get("sort", "date"),
                                              limit=min(int(q.get("limit") or 200), 1000),
                                              offset=int(q.get("offset") or 0))
                return self._send(200, {"total": total, "rows": rows})
            if action == "export":
                what = q.get("what", "chats")
                if what == "posts":
                    _, rows = app.store.posts(jid, limit=1_000_000)
                    cols = ["url", "channel", "date", "views", "matched", "text"]
                else:
                    _, rows = app.store.entities(jid, limit=1_000_000, **flt)
                    cols = ["url", "ref", "kind", "title", "members", "score", "relevant", "post_hits",
                            "inbound", "depth", "matched", "sources", "description"]
                name = f"telegram-{what}-{jid}.{ext or 'csv'}"
                head = {"Content-Disposition": f'attachment; filename="{name}"'}
                if ext == "json":
                    return self._send(200, json.dumps(rows, ensure_ascii=False, indent=1), "application/json", head)
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(cols)
                for r in rows:
                    w.writerow(["; ".join(r[c]) if isinstance(r[c], list) else r[c] for c in cols])
                return self._send(200, "﻿" + buf.getvalue(), "text/csv", head)

        if path == "/api/tg/status":
            return self._send(200, app.tg.status())
        if method == "POST" and path.startswith("/api/tg/"):
            b = self._body()
            if path == "/api/tg/config":
                app.tg.save_config(int(b["api_id"]), str(b["api_hash"]))
            elif path == "/api/tg/send_code":
                app.tg.send_code(str(b["phone"]).strip())
            elif path == "/api/tg/sign_in":
                return self._send(200, {"result": app.tg.sign_in(str(b.get("code", "")).strip(), b.get("password", ""))})
            elif path == "/api/tg/logout":
                app.tg.logout()
            else:
                return self._send(404, {"error": "not found"})
            return self._send(200, app.tg.status())
        self._send(404, {"error": "not found"})


def serve(data_dir: str, port: int = 8765):
    Handler.app = App(data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    print(f"Telegram Finder is running: http://127.0.0.1:{port}  (Ctrl+C to quit)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye")
