"""The protocol: requests and their checks, replies, the speech framing,
and the version."""

import io
import json

import numpy as np
import pytest

from si import protocol
from si.errors import Fail

V = protocol.PROTOCOL


def read(data):
    return list(protocol.pieces(io.BytesIO(data)))


def ln(**kw):
    return protocol.line(kw)


def test_round_trip():
    a = np.array([0, 0.5, -0.5, 1, -1, 2], np.float32)
    got = read(protocol.frame(a, 48000) + protocol.frame(a[:2], 48000)
               + protocol.done(48000, "Hei."))
    assert [r["rate"] for r in got] == [48000] * 3
    assert got[-1] == {"v": V, "done": True, "rate": 48000, "text": "Hei."}
    x = got[0]["audio"]
    assert x.dtype == np.float32 and len(got[1]["audio"]) == 2
    assert np.allclose(x, np.clip(a, -1, 1), atol=1 / 32767)


def test_pcm16():
    """-o writes the samples it always did: x 32767, truncated (the decode
    is / 32768: a 1/32768 gain step, inaudible)."""
    a = np.array([0, 0.5, -0.5, 1, -1, 2, 1e-4], np.float32)
    assert protocol.pcm16(a) == np.array(
        [0, 16383, -16383, 32767, -32767, 32767, 3], "<i2").tobytes()
    assert list(protocol.from_pcm16(protocol.pcm16(a[:5])) * 32768) == [
        0, 16383, -16383, 32767, -32767]


def test_header():
    assert protocol.frame(np.zeros(3, np.float32), 24000).startswith(
        b'{"v": %d, "pcm": 6, "rate": 24000}\n' % V)


@pytest.mark.parametrize(("data", "msg"), [
    (ln(error="no such voice: x"), "no such voice: x"),
    (b"", "went away"),
    (b"[1]\n", "went away"),
    (b"{\n", "went away"),
    (b"\xff\n", "went away"),
    (ln(pcm=4, rate=48000) + b"\x00\x00", "went away"),  # cut short
    (ln(pcm=3, rate=48000) + b"\x00\x00\x00", "went away"),  # odd
    (ln(pcm="x", rate=48000), "went away"),
    (ln(pcm=-2, rate=48000), "went away"),
    (ln(pcm=2) + b"\x00\x00", "went away"),                 # no rate
    (ln(done=True, rate="x"), "went away"),
    (ln(ok=True), "went away"),
    (ln(done=True, rate=48000), "went away"),               # no text
    (ln(done=True, rate=48000, text=None), "went away"),
    # another version: a server from before "v" (and before "rate")
    (b'{"pcm": 2, "rate": 48000}\n\x00\x00', "server is older"),
    (b'{"done": true}\n', "server is older"),
    (b'{"error": "no such voice: x"}\n', "server is older"),
    (ln(v=V + 1, done=True, rate=48000), "server is newer"),
])
def test_errors(data, msg):
    with pytest.raises(Fail, match=msg):
        read(protocol.frame(np.zeros(2, np.float32), 48000) + data)


def test_reply():
    f = io.BytesIO(protocol.line({"model": "m"}) + b'{"ok": true}\n')
    assert protocol.reply(f) == {"v": V, "model": "m"}
    assert protocol.reply(f, protocol.STOP) == {"ok": True}  # any version's
    with pytest.raises(Fail, match="older than this client; restart it with "
                       "si --stop"):
        protocol.reply(io.BytesIO(b'{"ok": true}\n'))


def v(req):
    return json.loads(protocol.line(req))


@pytest.mark.parametrize("req", [
    [1], 3, None, "hi", {"v": V}, {"v": V, "text": 5},
    {"v": V, "cmd": "speak", "text": None},
    {"v": V, "cmd": "speak", "text": "hi", "voice": 1},
    {"v": V, "cmd": "speak", "text": "hi", "instruct": ["x"]},
    {"v": V, "cmd": "nope"}, {"v": V, "cmd": "hold"},
    *({"v": V, "cmd": "hold", "pid": p} for p in ("12", 0, -1, 2**31, 1e3, True)),
    {"v": V, "cmd": ["speak"]}, {"v": V, "cmd": None},
    {"v": V, "cmd": "speak"}])
def test_check_rejects(req):
    with pytest.raises(Fail, match="bad request"):
        protocol.check(req)


@pytest.mark.parametrize("req", [
    protocol.speak("hi"), protocol.speak("", None, None),
    protocol.speak("hi", "/x.wav", "calm"), protocol.STATUS, protocol.STOP,
    protocol.hold(1234)])
def test_check_accepts(req):
    assert protocol.check(v(req)) == v(req)


def test_check_fills_optional_fields():
    assert protocol.check({"v": V, "cmd": "speak", "text": "hi"}) == {
        "v": V, "cmd": "speak", "text": "hi", "voice": None, "instruct": None}


@pytest.mark.parametrize(("req", "msg"), [
    # a client from before "v" (and one from before "cmd")
    ({"cmd": "speak", "text": "hi"}, "newer"), ({"text": "hi"}, "newer"),
    ({"cmd": "status"}, "newer"), ({"cmd": "hold", "pid": 1}, "newer"),
    ({"v": V - 1, "cmd": "status"}, "newer"), ({"v": "2", "cmd": "status"}, "newer"),
    ({"v": V + 1, "cmd": "status"}, "older"), ({"v": V + 1, "cmd": "nope"}, "older"),
])
def test_check_version(req, msg):
    with pytest.raises(Fail, match=f"^the server is {msg} than this client; "
                       "restart it with si --stop$"):
        protocol.check(req)


def test_stop_works_across_versions():
    for req in ({"cmd": "stop"}, {"v": V + 1, "cmd": "stop"}):
        assert protocol.check(req) == req
