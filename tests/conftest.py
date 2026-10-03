"""Shared fixtures: a short cache directory, fake servers (SI_FAKE:
no model, silence, a null audio output) driven through the CLI, test
voices, and wait_for."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from si import config, server
from si import voices as V


def wait_for(pred, timeout=10, what="it", every=0.05):
    """pred()'s first true value, polled every `every` s; fails the test
    (rather than hang the suite) after `timeout` s."""
    deadline = time.time() + timeout
    while not (r := pred()):
        if time.time() > deadline:
            pytest.fail(f"timed out after {timeout} s waiting for {what}")
        time.sleep(every)
    return r


@pytest.fixture(autouse=True)
def no_sound(monkeypatch):
    """Opening sounddevice's OutputStream in the test process fails the
    test (pytest.fail: a BaseException, which the Player doesn't turn into
    a Fail). Child processes that run the CLI must have SI_FAKE
    (a null output), checked by silent()."""
    try:
        import sounddevice as sd
    except (ImportError, OSError):  # no PortAudio: nothing to open
        return

    def output(*args, **kw):
        pytest.fail("a test opened a real audio output")

    monkeypatch.setattr(sd, "OutputStream", output)


def silent(env, argv):
    """env, for a child process that runs the CLI with argv; fails the test
    unless env has SI_FAKE (whatever the child does, it can only
    play to a null output)."""
    if "SI_FAKE" not in env:
        pytest.fail(f"a test ran the CLI without the null output: {argv}")
    return env


@pytest.fixture
def cache(monkeypatch):
    """A cache directory with a short path (sockets allow ~100 bytes): in
    $TMPDIR if that is short (macOS's isn't), else in /tmp."""
    tmp = os.environ.get("TMPDIR", "")
    d = tempfile.mkdtemp(prefix="si", dir=tmp if 0 < len(tmp) < 50 else "/tmp")
    monkeypatch.setattr(config, "CACHE", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class Fake:
    """The CLI against fake servers in `cache`."""

    TEXT = "Hei, dette er en test."

    def __init__(self, cache):
        self.cache, self.n = cache, 0
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("SI_")}
        self.env.update(SI_CACHE=cache, SI_FAKE="load=1",
                        SI_IDLE="60")

    def run(self, *args, extra=None, **kw):
        return subprocess.Popen(
            [sys.executable, "-m", "si.cli", *args],
            env=silent({**self.env, **(extra or {})}, args), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, **kw)

    def say(self, text=TEXT, *args, **kw):
        """Speak text to a new .wav in the cache."""
        self.n += 1
        return self.run("-o", os.path.join(self.cache, f"{self.n}.wav"), *args,
                        text, **kw)

    @staticmethod
    def wait(*procs, timeout=30):
        """[(exit code, stderr)] of procs."""
        return [(p.wait(timeout), p.stderr.read()) for p in procs]

    def done(self, p, timeout=30):
        return self.wait(p, timeout=timeout)[0]

    def warm(self, *args, extra=None):
        """--warm (args), and wait until the server it starts is ready."""
        n = self.log().count("] ready")
        assert self.run("--warm", *args, extra=extra).wait(5) == 0
        wait_for(lambda: self.log().count("] ready") > n, what="the server to be ready")

    def log(self):
        try:
            with open(os.path.join(self.cache, "server.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def started(self):
        return self.log().count("listening on")

    def servers(self):
        """The pids of the servers that took the lock, still alive."""
        pids = {int(line.split("[")[1].split("]")[0])
                for line in self.log().splitlines() if "listening on" in line}
        return {p for p in pids if server.pid_alive(p)}

    def raw(self, data):
        """Send raw bytes to the server; its reply line, parsed."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(os.path.join(self.cache, "sock"))
            s.sendall(data)
            return json.loads(s.makefile("rb").readline() or "{}")


@pytest.fixture
def fake(cache):
    """A Fake; every server it started is killed afterwards."""
    f = Fake(cache)
    yield f
    for p in f.servers():
        os.kill(p, signal.SIGKILL)


@pytest.fixture
def voices(tmp_path, monkeypatch):
    """Bundled voices anna (with a transcript) and ola, in tmp_path."""
    (tmp_path / "anna.wav").write_bytes(b"")
    (tmp_path / "anna.txt").write_text("Hei,\n  dette er Anna.\n")
    (tmp_path / "ola.wav").write_bytes(b"")
    monkeypatch.setattr(V, "MINE", str(tmp_path / "mine"))
    monkeypatch.setattr(V, "BUNDLED", str(tmp_path))
    return tmp_path


@pytest.fixture
def defaults(monkeypatch):
    """Default voices anna (no, the fallback) and john (en), no env."""
    for lang in ("NO", "EN", "ES"):
        monkeypatch.delenv("SI_VOICE_" + lang, raising=False)
    monkeypatch.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": "john"})
    monkeypatch.setattr(V, "FALLBACK", "no")
    return monkeypatch
