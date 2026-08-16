"""
Local web UI for the Grafana Dashboard Customizer.

Runs a small stdlib-only HTTP server (no pip installs needed) that serves a
side-by-side editor: detected values (hosts, datasources, site name) on the
left, and a box to type the replacement value on the right - mirroring the
config.json workflow described in README.md, without hand-editing JSON.

Usage:
    python3 app.py                # serves on http://127.0.0.1:8765
    python3 app.py --port 9000
    python3 app.py --host 0.0.0.0 --port 8765   # expose to your LAN
"""

import argparse
import io
import json
import mimetypes
import os
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from grafana_customizer import build_transform_maps, scan_dashboard, transform_dashboard

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PRESETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")


def load_presets():
    if not os.path.isfile(PRESETS_FILE):
        return []
    try:
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_presets(presets):
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


def aggregate_scan(files):
    """
    files: list of {"name": str, "content": str (raw JSON text)}
    Returns (result_dict, warnings_list) in the same shape generate_config()
    writes to config.json, so it stays compatible with the CLI tool.
    """
    all_hosts = set()
    all_sites = set()
    all_datasources = {}
    all_transformations = set()  # set of (regex, renamePattern) tuples
    all_value_mappings = set()  # set of (value, text) tuples
    all_urls = set()
    all_panel_titles = set()
    all_text_content = set()
    warnings = []

    for f in files:
        try:
            dashboard_data = json.loads(f["content"])
        except json.JSONDecodeError as e:
            warnings.append(f"Skipped '{f['name']}': invalid JSON ({e})")
            continue

        result = scan_dashboard(dashboard_data)
        all_hosts.update(result["hosts"])
        all_sites.update(result["sites"])
        for ds in result["datasources"]:
            all_datasources.setdefault(ds["type"], set()).add(ds["uid"])
        for t in result["transformations"]:
            all_transformations.add((t["regex"], t["renamePattern"]))
        for vm in result["value_mappings"]:
            all_value_mappings.add((vm["value"], vm["text"]))
        all_urls.update(result["urls"])
        all_panel_titles.update(result["panel_titles"])
        all_text_content.update(result["text_content"])

    datasources = [
        {"type": ds_type, "uid": uid}
        for ds_type, uids in all_datasources.items()
        for uid in sorted(uids)
    ]

    transformations = [
        {"regex": regex, "renamePattern": rename_pattern}
        for regex, rename_pattern in sorted(all_transformations, key=lambda t: (t[0] or "", t[1] or ""))
    ]

    value_mappings = [
        {"value": value, "text": text}
        for value, text in sorted(all_value_mappings, key=lambda t: (t[0] or "", t[1] or ""))
    ]

    return {
        "hosts": sorted(all_hosts),
        "sites": sorted(all_sites),
        "datasources": datasources,
        "urls": sorted(all_urls),
        "transformations": transformations,
        "value_mappings": value_mappings,
        "panel_titles": sorted(all_panel_titles),
        "text_content": sorted(all_text_content),
    }, warnings


class Handler(BaseHTTPRequestHandler):
    server_version = "GrafanaCustomizerUI/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status, body, content_type, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw or b"{}")

    # ---- Static file serving ----

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/presets":
            self._send_json(200, load_presets())
            return

        if path == "/":
            path = "/index.html"

        safe_path = os.path.normpath(path).lstrip(os.sep)
        full_path = os.path.join(STATIC_DIR, safe_path)

        if not os.path.abspath(full_path).startswith(os.path.abspath(STATIC_DIR)):
            self._send_json(403, {"error": "Forbidden"})
            return

        if not os.path.isfile(full_path):
            self._send_json(404, {"error": "Not found"})
            return

        content_type, _ = mimetypes.guess_type(full_path)
        with open(full_path, "rb") as f:
            body = f.read()
        self._send_bytes(200, body, content_type or "application/octet-stream")

    # ---- API endpoints ----

    def do_POST(self):
        if self.path == "/api/scan":
            self._handle_scan()
        elif self.path == "/api/apply":
            self._handle_apply()
        elif self.path == "/api/presets":
            self._handle_save_presets()
        else:
            self._send_json(404, {"error": "Not found"})

    def _handle_save_presets(self):
        try:
            presets = self._read_json_body()
            if not isinstance(presets, list):
                self._send_json(400, {"error": "Expected a list of presets."})
                return
            save_presets(presets)
            self._send_json(200, {"ok": True})
        except Exception as e:
            self._send_json(400, {"error": str(e)})

    def _handle_scan(self):
        try:
            data = self._read_json_body()
            files = data.get("files", [])
            if not files:
                self._send_json(400, {"error": "No files provided."})
                return
            result, warnings = aggregate_scan(files)
            result["warnings"] = warnings
            self._send_json(200, result)
        except Exception as e:
            self._send_json(400, {"error": str(e)})

    def _handle_apply(self):
        try:
            data = self._read_json_body()
            files = data.get("files", [])
            config_data = data.get("config", {})
            if not files:
                self._send_json(400, {"error": "No files provided."})
                return

            maps = build_transform_maps(config_data)
            processed = []
            errors = []

            for f in files:
                try:
                    dashboard_data = json.loads(f["content"])
                except json.JSONDecodeError as e:
                    errors.append(f"Skipped '{f['name']}': invalid JSON ({e})")
                    continue
                transform_dashboard(dashboard_data, maps)
                processed.append((f["name"], dashboard_data))

            if not processed:
                self._send_json(400, {"error": "No valid files to process.", "details": errors})
                return

            if len(processed) == 1:
                name, dashboard_data = processed[0]
                body = json.dumps(dashboard_data, indent=2).encode("utf-8")
                self._send_bytes(
                    200, body, "application/json", filename=f"customized_{name}"
                )
            else:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for name, dashboard_data in processed:
                        zf.writestr(name, json.dumps(dashboard_data, indent=2))
                self._send_bytes(
                    200,
                    buf.getvalue(),
                    "application/zip",
                    filename="customized_dashboards.zip",
                )
        except Exception as e:
            self._send_json(400, {"error": str(e)})


def main():
    parser = argparse.ArgumentParser(description="Grafana Dashboard Customizer - Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Grafana Dashboard Customizer UI running at {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
