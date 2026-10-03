"""The socket protocol between client and server.

Every message is one JSON line carrying the protocol version, "v": PROTOCOL.
The client sends one request (built by speak(), hold(), STATUS or STOP); a
command gets one reply line. Speech gets, per piece of audio, {"pcm": N,
"rate": HZ} and N bytes of 16-bit mono PCM, then {"done": true, "rate": HZ,
"text": "..."} (the text as spoken) or {"error": "..."}. Each side refuses
the other's other versions (a server started before an upgrade), except for
STOP, which every version obeys: it is how a skew is fixed.
"""

import contextlib
import json

from si.errors import Fail

# Bump on any incompatible change. 1: no "v" at all; 2: the status had
# "loading" and "downloading" (booleans), not "phase" and "pid".
PROTOCOL = 3
STATUS = {"cmd": "status"}
# The status's "phase": downloading (only if not cached) and loading the
# model, then ready.
DOWNLOADING, LOADING, READY = "downloading", "loading", "ready"
STARTING = (DOWNLOADING, LOADING)
STOP = {"cmd": "stop"}


def speak(text, voice=None, instruct=None):
    return {"cmd": "speak", "text": text, "voice": voice, "instruct": instruct}


def hold(pid):
    return {"cmd": "hold", "pid": pid}


def line(msg):
    return json.dumps({"v": PROTOCOL, **msg}).encode() + b"\n"


def skew(server_newer):
    return Fail(f"the server is {'newer' if server_newer else 'older'} than "
                "this client; restart it with si --stop")


def newer(v):
    """Is version v (from a message) newer than ours?"""
    return type(v) is int and v > PROTOCOL


def any_version(req):
    """Is req obeyed, and its reply read, whatever the version? (STOP.)"""
    return isinstance(req, dict) and req.get("cmd") == "stop"


# ----------------------------------------------------------------- requests

def _str(x):
    return isinstance(x, str)


def _str_or_none(x):
    return isinstance(x, (str, type(None)))


def _pid(x):
    return type(x) is int and 0 < x < 2**31


FIELDS = {  # per command: field -> (is it valid?, the error)
    "speak": {"text": (_str, "no text"),
              "voice": (_str_or_none, "voice is not a string"),
              "instruct": (_str_or_none, "instruct is not a string")},
    "hold": {"pid": (_pid, "not a process id: {!r}")},
    "status": {},
    "stop": {},
}


def check(req):
    """A client's request, validated (the server trusts no input), with
    the optional fields it left out as None."""
    if not isinstance(req, dict):
        raise Fail("bad request: not a JSON object")
    cmd = req.get("cmd")
    if not any_version(req) and req.get("v") != PROTOCOL:
        raise skew(not newer(req.get("v")))
    if not isinstance(cmd, str) or cmd not in FIELDS:
        raise Fail(f"bad request: unknown command: {cmd!r}")
    for k, (ok, err) in FIELDS[cmd].items():
        if not ok(req.get(k)):
            raise Fail("bad request: " + err.format(req.get(k)))
    return {**dict.fromkeys(FIELDS[cmd]), **req}


# ------------------------------------------------------------------ replies

@contextlib.contextmanager
def reading():
    """Reading from the server: its failures as Fail."""
    try:
        yield
    except TimeoutError:
        raise Fail("the server timed out")
    except (OSError, ValueError):
        raise Fail("the server went away")


def reply(f, req=None):
    """Read one reply line (to req; None: to speech) from file f; raises
    Fail on an error reply, a broken stream or another protocol version
    (unless any_version(req))."""
    with reading():
        r = json.loads(f.readline() or "{}")
    if not isinstance(r, dict) or not r:
        raise Fail("the server went away")
    if not any_version(req) and r.get("v") != PROTOCOL:
        raise skew(newer(r.get("v")))
    if "error" in r:
        raise Fail(str(r["error"]))
    return r


def pcm16(audio):
    """Float audio as 16-bit mono PCM (the speech framing's, and -o's)."""
    import numpy as np

    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def from_pcm16(data):
    import numpy as np

    return np.frombuffer(data, "<i2").astype(np.float32) / 32768


def frame(audio, rate):
    """A piece of float audio as a reply: header line and PCM."""
    pcm = pcm16(audio)
    return line({"pcm": len(pcm), "rate": rate}) + pcm


def done(rate, text):
    return line({"done": True, "rate": rate, "text": text})


def pieces(f):
    """Read a speech reply from file f: yields each reply, a piece's with
    its float32 "audio" added, ending with the "done" one (with the text);
    raises Fail as reply() does."""
    while True:
        r = reply(f)
        n, rate = r.get("pcm", 0), r.get("rate")
        if (not ("pcm" in r or r.get("done") and _str(r.get("text")))
                or type(n) is not int or n < 0 or n % 2
                or type(rate) is not int or rate <= 0):
            raise Fail("the server went away")
        if "pcm" not in r:
            yield r
            return
        with reading():
            pcm = f.read(n)
        if len(pcm) != n:
            raise Fail("the server went away")
        yield {**r, "audio": from_pcm16(pcm)}
