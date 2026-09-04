"""Read and write the remote's live settings service (Slinger 1.0 on port 80).

Reachable from the host over the RNDIS link; requests must be HTTP/1.0 with CRLF.
GET returns the value wrapped in an Event envelope; POST takes the bare value as the
body - posting an Event envelope stores the envelope itself as the value.
"""
import os
import re
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from afterglow.remote_shell import REMOTE_IP

HOST, PORT = REMOTE_IP, 80


def _talk(payload):
    s = socket.create_connection((HOST, PORT), 5)
    s.settimeout(5)
    try:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        got = b""
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            got += chunk
        return got
    finally:
        s.close()


def get(name):
    raw = _talk(f"GET {name} HTTP/1.0\r\n\r\n".encode()).decode("utf-8", "replace")
    inner = re.search(r"<Value>(.*)</Value>", raw, re.S)
    return inner.group(1) if inner else raw.strip()


def post(name, value):
    body = str(value)
    return _talk((f"POST {name} HTTP/1.0\r\nContent-Type: text/plain\r\n"
                  f"Content-Length: {len(body)}\r\n\r\n{body}").encode())


if __name__ == "__main__":
    if sys.argv[1:2] == ["set"]:
        post(sys.argv[2], sys.argv[3])
        print(f"{sys.argv[2]} = {get(sys.argv[2])!r}")
    else:
        for name in sys.argv[1:] or ["/system/theme"]:
            print(f"{name} = {get(name)!r}")
