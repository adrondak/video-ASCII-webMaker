"""Static preview server with HTTP Range support (stdlib only).

``python3 -m http.server`` ignores Range requests, which stops browsers from
seeking in audio. Real static hosts (SiteGround, Apache, Nginx, GitHub Pages)
support ranges, so use this script to preview locally with the same behaviour.

    python3 scripts/serve.py [directory] [port]
"""

from __future__ import annotations

import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".json": "application/json",
                      ".woff2": "font/woff2", ".m4a": "audio/mp4",
                      ".ascf": "application/octet-stream"}

    def send_head(self):
        self._range = None
        header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not header or not os.path.isfile(path):
            return super().send_head()
        m = RANGE.match(header.strip())
        size = os.path.getsize(path)
        if not m or (not m.group(1) and not m.group(2)):
            return super().send_head()
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:  # suffix range: last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        end = min(end, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self._range = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._range))
        self.end_headers()
        return f

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_range", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


class Server(ThreadingHTTPServer):
    request_queue_size = 128  # the stdlib default of 5 drops parallel browser connections
    daemon_threads = True


def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "www"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    if not os.path.isdir(directory):
        sys.exit(f"no such directory: {directory}")
    server = Server(("127.0.0.1", port), partial(RangeHandler, directory=directory))
    print(f"Serving {directory} at http://localhost:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
