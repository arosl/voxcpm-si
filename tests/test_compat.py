"""Version skew: an older or newer client against this server, and this
client against a server from before the protocol version (a stub); either
way a short message, and --stop works across versions."""

import json
import os
import socket
import threading
import time

import pytest
from conftest import wait_for

from si.protocol import PROTOCOL as V

SKEW = "the server is {} than this client; restart it with si --stop"


def test_older_client(fake):
    """A client from before the protocol version (or before "cmd", or a
    newer one) is told to restart the server; any version can stop it."""
    assert fake.done(fake.say())[0] == 0
    for data in (b'{"cmd": "speak", "text": "Hei.", "voice": null}\n',
                 b'{"text": "Hei."}\n', b'{"cmd": "status"}\n',
                 b'{"cmd": "hold", "pid": 1}\n', b'{"v": 1, "cmd": "status"}\n',
                 b'{"v": %d, "cmd": "status"}\n' % (V - 1)):
        assert fake.raw(data) == {"v": V, "error": SKEW.format("newer")}, data
    assert fake.raw(b'{"v": %d, "cmd": "status"}\n' % (V + 1))["error"] == (
        SKEW.format("older"))
    assert fake.done(fake.say())[0] == 0  # still serving
    assert fake.raw(b'{"cmd": "stop"}\n') == {"v": V, "ok": True}
    wait_for(lambda: not fake.servers(), 0.5, "the stopped server to exit")


def old_server(cache, rate, v=None):
    """A server from before this protocol version, in a thread: v None,
    from before the version (without rate: from before "rate" too); v 2,
    one whose status had the "loading" and "downloading" booleans, which
    refuses other versions. It answers like main did (speech: only its
    first line, which a new client refuses) until a stop; returns the list of requests it got."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(os.path.join(cache, "sock"))
    srv.listen(8)
    got = []

    def line(msg):
        return json.dumps({**({"v": v} if v else {}), **msg}).encode() + b"\n"

    def reply(req):
        cmd, r = req.get("cmd", "speak"), {"rate": 48000} if rate else {}
        if v and cmd != "stop" and req.get("v") != v:
            return line({"error": SKEW.format("older")})
        if cmd == "speak":  # only reached without v: its first line is refused
            return line({"pcm": 9600, **r})
        if cmd == "stop":
            return line({"ok": True})
        return line({"model": "old", "holders": [], "loading": False,
                     "downloading": False, "queued": 0, "stalled": 0})

    def serve():
        while not got or got[-1].get("cmd") != "stop":
            conn, _ = srv.accept()
            with conn:
                got.append(json.loads(conn.makefile("rb").readline()))
                conn.sendall(reply(got[-1]))
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return got


@pytest.mark.parametrize("rate, v", [(True, None), (False, None), (True, 2)])
def test_older_server(fake, rate, v):
    """The rolling upgrade: a new client against a server from before the
    protocol version fails at once with a short message (no traceback, no
    sound, no file), and --stop works."""
    got = old_server(fake.cache, rate, v)
    out = os.path.join(fake.cache, "x.wav")
    for args in (["Hei."], ["-o", out, "Hei."], ["--status"], ["--warm"],
                 ["--warm", "--hold", str(os.getpid())]):
        t = time.time()
        code, err = fake.done(fake.run(*args))
        assert (code, err) == (1, f"si: {SKEW.format('older')}\n"), args
        assert time.time() - t < 5
    assert not os.path.exists(out)
    stop = fake.run("--stop")
    assert stop.wait(5) == 0 and stop.stdout.read() == "stopped\n"
    assert [r["cmd"] for r in got] == ["speak", "speak", "status", "status",
                                       "hold", "stop"]
    assert all(r["v"] == V for r in got)
