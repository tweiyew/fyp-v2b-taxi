"""Local live simulation website: pick a config and policy, press Run, watch the city hour by hour.

Run: python -m viz.server [--port 8765] [--open]
Listens on 127.0.0.1 only. Endpoints:
  GET  /                         the page (viz/web/live.html) and its files from viz/web/
  GET  /api/options              runnable configs, policies, lengths
  GET  /api/live                 the run still computing, if any (so a reloaded page can reattach)
  GET  /api/zones                viz/zones.geojson
  POST /api/runs                 {"config", "policy", "hours", "weights"} starts a run
  GET  /api/runs/<id>/stream     server-sent events: start, one frame per hour, then done/failed/stopped
  POST /api/runs/<id>/stop       ends the run; nothing is saved
  GET  /api/runs                 saved runs in results/, newest first
  GET  /api/runs/<id>            one saved run: {"trace", "meta"}
"""

import argparse
import errno
import json
import mimetypes
import os
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

from viz.live import ROOT, RunError, RunManager, options, saved_run_dir, saved_runs

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
ZONES_PATH = os.path.join(HERE, "zones.geojson")
DEFAULT_PORT = 8765
KEEPALIVE_SECONDS = 15


def render_page(web_dir: str = WEB_DIR) -> bytes:
    """live.html with the shared scene markup put in."""
    with open(os.path.join(web_dir, "live.html")) as fp:
        page = fp.read()
    with open(os.path.join(web_dir, "scene.html")) as fp:
        scene = fp.read()
    if page.count("__SCENE_HTML__") != 1:
        raise ValueError("live.html must contain __SCENE_HTML__ exactly once")
    return page.replace("__SCENE_HTML__", scene).encode()


def static_files(web_dir: str = WEB_DIR) -> Dict[str, str]:
    """URL path to file for everything under viz/web/ except the page templates."""
    files = {}
    for folder, _, names in os.walk(web_dir):
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, web_dir).replace(os.sep, "/")
            if not rel.endswith(".html"):
                files["/" + rel] = path
    return files


class Handler(BaseHTTPRequestHandler):
    server_version = "FleetLive/1"
    manager: RunManager  # set by make_server

    def log_message(self, fmt, *args) -> None:
        if "/stream" not in self.path:
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # ---- responses
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _parts(self):
        return [p for p in self.path.split("?", 1)[0].split("/") if p]

    # ---- routes
    def do_GET(self) -> None:
        parts = self._parts()
        if not parts:
            return self._send(HTTPStatus.OK, render_page(), "text/html; charset=utf-8")
        if parts[0] != "api":
            path = static_files().get("/" + "/".join(parts))
            if path is None:
                return self._error(HTTPStatus.NOT_FOUND, "Not found")
            with open(path, "rb") as fp:
                body = fp.read()
            kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind.endswith("javascript"):
                kind += "; charset=utf-8"
            return self._send(HTTPStatus.OK, body, kind)
        if parts == ["api", "options"]:
            return self._json(HTTPStatus.OK, options())
        if parts == ["api", "live"]:
            run = self.manager.current
            if run is None or run.finished:
                return self._error(HTTPStatus.NOT_FOUND, "No run is computing")
            return self._json(HTTPStatus.OK, run.settings)
        if parts == ["api", "zones"]:
            with open(ZONES_PATH, "rb") as fp:
                return self._send(HTTPStatus.OK, fp.read(), "application/json")
        if parts == ["api", "runs"]:
            return self._json(HTTPStatus.OK, saved_runs(self.manager.results_dir))
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "stream":
            return self._stream(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "runs"]:
            return self._saved(parts[2])
        return self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parts = self._parts()
        if parts == ["api", "runs"]:
            return self._start()
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "stop":
            run = self.manager.get(parts[2])
            if run is None:
                return self._error(HTTPStatus.NOT_FOUND, "No such live run")
            run.stop()
            return self._json(HTTPStatus.OK, {"run_id": run.run_id, "stopped": True})
        return self._error(HTTPStatus.NOT_FOUND, "Not found")

    def _start(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "Send a JSON object")
        try:
            run = self.manager.start(body.get("config"), body.get("policy", "EIGHTYTWENTY"), body.get("hours"), body.get("weights"))
        except RunError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            return self._error(HTTPStatus.CONFLICT, str(exc))
        return self._json(HTTPStatus.CREATED, {"run_id": run.run_id, **run.settings})

    def _saved(self, run_id: str) -> None:
        try:
            folder = saved_run_dir(run_id, self.manager.results_dir)
        except KeyError:
            return self._error(HTTPStatus.NOT_FOUND, "No such saved run")
        with open(os.path.join(folder, "trace.json"), "rb") as fp:
            trace = fp.read()
        with open(os.path.join(folder, "metrics.json"), "rb") as fp:
            meta = fp.read()
        self._send(HTTPStatus.OK, b'{"trace":' + trace + b',"meta":' + meta + b"}", "application/json")

    def _stream(self, run_id: str) -> None:
        run = self.manager.get(run_id)
        if run is None:
            return self._error(HTTPStatus.NOT_FOUND, "No such live run")
        try:
            since = int(self.headers.get("Last-Event-ID", -1)) + 1
        except ValueError:
            since = 0
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                events, over = run.wait(since, KEEPALIVE_SECONDS)
                if not events:
                    if over:
                        return
                    self.wfile.write(b": keepalive\n\n")
                for kind, data in events:
                    self.wfile.write(f"id: {since}\nevent: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode())
                    since += 1
                self.wfile.flush()
                if over and len(run.events) == since:
                    return
        except (BrokenPipeError, ConnectionResetError):
            return


def make_server(port: int, manager: Optional[RunManager] = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"manager": manager or RunManager()})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args()

    os.chdir(ROOT)
    try:
        server = make_server(args.port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            sys.exit(f"Port {args.port} is already in use. Pick another: make serve PORT=<number>")
        raise
    missing = [p for p in ("vendor/deck.min.js", "vendor/fonts.css") if not os.path.isfile(os.path.join(WEB_DIR, p))]
    if missing:
        server.server_close()
        sys.exit(f"Missing viz/web/{missing[0]}: run `make vendor` once (needs internet).")
    url = f"http://localhost:{args.port}"
    print(f"Serving {url} (Ctrl+C to stop)", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping", flush=True)
    finally:
        server.RequestHandlerClass.manager.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
