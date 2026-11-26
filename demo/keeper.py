#!/usr/bin/env python3
"""keeper: holds words in memory and nowhere else.

Visitors to the Cryo site leave a word here, kill the Sprite, and get it back.
This program never writes a word to a file. If a word survives a restart, it's
because cryo froze this whole process and thawed it again.

Listens on 127.0.0.1 only; cryo-api passes requests through.
"""
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("KEEPER_PORT", "8091"))
MAX_WORDS = 2000
MAX_LEN = 40

born = time.time()
words = {}  # id -> {"text", "t"}, oldest first


def clean(text):
    text = "".join(ch for ch in str(text) if ch.isprintable()).strip()
    return text[:MAX_LEN]


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def about(self):
        return {"pid": os.getpid(), "alive_since": born, "words_held": len(words)}

    def do_GET(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == ["words"]:
            return self.send(200, self.about())
        if len(parts) == 2 and parts[0] == "words":
            w = words.get(parts[1])
            if not w:
                return self.send(404, dict(self.about(), error="not in memory"))
            return self.send(200, dict(self.about(), text=w["text"], t=w["t"]))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0].strip("/") != "words":
            return self.send(404, {"error": "not found"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 2048)
            text = clean(json.loads(self.rfile.read(n) or b"{}").get("text", ""))
        except (ValueError, AttributeError):
            text = ""
        if not text:
            return self.send(400, {"error": "say something (up to 40 characters)"})
        while len(words) >= MAX_WORDS:
            words.pop(next(iter(words)))
        wid = secrets.token_urlsafe(9)
        words[wid] = {"text": text, "t": time.time()}
        self.send(200, dict(self.about(), id=wid, text=text))


if __name__ == "__main__":
    print(f"keeper: holding words in pid {os.getpid()} on 127.0.0.1:{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
