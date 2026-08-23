#!/usr/bin/env python3
"""Tiny download server: serve files or a directory with Content-Disposition: attachment."""

import argparse
import http.server
import os
import urllib.parse

FILES: dict[str, str] = {}
DIR: str | None = None


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ServeDownloads/1.0"

    def do_HEAD(self) -> None:
        self._handle(include_body=False)

    def do_GET(self) -> None:
        self._handle(include_body=True)

    def _handle(self, include_body: bool) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path).strip("/")
        if not path or path == "":
            self._index(include_body=include_body)
            return
        if path in FILES:
            self._serve(FILES[path], display=path, include_body=include_body)
            return
        if DIR:
            safe = os.path.realpath(os.path.join(DIR, path))
            if os.path.isfile(safe) and os.path.realpath(DIR) in os.path.commonpath(
                [os.path.realpath(DIR), safe]
            ):
                self._serve(safe, display=os.path.basename(safe), include_body=include_body)
                return
            self._index(include_body=include_body)
            return
        self.send_error(404, "Not found")

    def _index(self, include_body: bool = True) -> None:
        items = list(FILES.keys())
        if DIR:
            items += sorted(
                f for f in os.listdir(DIR) if os.path.isfile(os.path.join(DIR, f))
            )
        body = "<html><body><h1>Downloads</h1><ul>"
        for name in items:
            body += f'<li><a href="/{urllib.parse.quote(name)}">{name}</a></li>'
        body += "</ul></body></html>"
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def _serve(self, real_path: str, display: str | None = None, include_body: bool = True) -> None:
        if not os.path.isfile(real_path):
            self.send_error(404, "Not found")
            return
        size = os.path.getsize(real_path)
        name = display or os.path.basename(real_path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{urllib.parse.quote(name)}"'
        )
        self.send_header("Content-Length", str(size))
        self.end_headers()
        if not include_body:
            return
        with open(real_path, "rb") as fh:
            while chunk := fh.read(65536):
                self.wfile.write(chunk)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[serve_downloads] {self.address_string()} - {fmt % args}")


def main() -> None:
    global DIR
    ap = argparse.ArgumentParser(description="Serve files as downloads over HTTP")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--files", nargs="*", default=[], help="Explicit file paths to serve")
    ap.add_argument("--dir", default=None, help="Serve all files in a directory")
    args = ap.parse_args()

    for f in args.files:
        if not os.path.isfile(f):
            print(f"warning: not a file, skipped: {f}")
            continue
        FILES[os.path.basename(f)] = os.path.abspath(f)
    DIR = os.path.abspath(args.dir) if args.dir else None
    if DIR and not os.path.isdir(DIR):
        print(f"error: not a directory: {DIR}")
        raise SystemExit(1)
    if not FILES and not DIR:
        print("error: provide at least one --files or --dir")
        raise SystemExit(1)

    srv = http.server.ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"serving on http://{args.bind}:{args.port}/")
    print("files:", sorted(FILES) if FILES else f"dir {DIR}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
