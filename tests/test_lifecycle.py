"""The server's lifecycle: one server per cache (the lock, the socket's
inode), its start, commands while it speaks, bad input, signals, idle exit,
worker death, lost files, and the clients' retries. Most tests run real
server processes with SI_FAKE (no model: silence)."""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest
from conftest import silent, wait_for

from si import client, config, protocol, server, voices

STATUS = b'{"cmd": "status"}\n'


def test_lock(cache):
    assert not client.server_alive()
    fd = server.take_lock()
    assert fd is not None and client.server_alive()
    assert server.take_lock(wait=0.1) is None  # one server only
    with open(config.lock_path()) as f:
        assert f.read() == f"{os.getpid()}\n"
    os.close(fd)
    assert not client.server_alive()


def test_unlink_only_our_socket(cache):
    srv, ino = server.bind()
    srv.close()
    srv2, ino2 = server.bind()  # another server took over the path
    server.unlink_ours(ino)
    assert os.stat(config.sock_path()).st_ino == ino2
    server.unlink_ours(ino2)
    assert not os.path.exists(config.sock_path())
    server.unlink_ours(ino2)  # already gone: fine
    srv2.close()


# ------------------------------------------------------- start, use, stop

def test_concurrent_cold_start(fake):
    results = fake.wait(*[fake.say() for _ in range(6)])
    assert all(code == 0 for code, _ in results), results
    assert fake.started() == 1 and len(fake.servers()) == 1


def test_starter_killed_while_loading(fake):
    p = fake.say(extra={"SI_FAKE": "load=3"})
    wait_for(fake.servers, what="the server to start")
    p.kill()
    t = time.time()
    assert fake.done(fake.say())[0] == 0
    assert time.time() - t > 1  # it waited for the load
    assert fake.started() == 1 and len(fake.servers()) == 1


def test_flood_and_status_while_speaking(fake):
    fake.warm(extra={"SI_FAKE": "piece=0.3"})
    long = " ".join([("Dette er en ganske lang setning om ingenting spesielt, "
                      "bare for testen.")] * 6)
    procs = [fake.say(long)] + [fake.say() for _ in range(8)]
    time.sleep(1)
    t = time.time()
    st = fake.run("--status")
    assert st.wait(5) == 0 and "running" in st.stdout.read()
    assert time.time() - t < 2
    assert procs[0].poll() is None  # still speaking
    assert all(code == 0 for code, _ in fake.wait(*procs)), procs
    assert fake.started() == 1 and len(fake.servers()) == 1


def test_warm_returns_at_once_and_holds(fake):
    t = time.time()
    w = fake.run("--warm", "--hold", str(os.getpid()))
    assert w.wait(5) == 0 and "warming" in w.stdout.read()
    assert time.time() - t < 2
    st = fake.run("--status")
    assert st.wait(5) == 0
    out = st.stdout.read()
    assert "loading" in out and str(os.getpid()) in out, out
    assert fake.done(fake.say())[0] == 0
    stop = fake.run("--stop")
    assert stop.wait(5) == 0 and stop.stdout.read() == "stopped\n"
    wait_for(lambda: not fake.servers(), 0.5, "the stopped server to exit")
    st = fake.run("--status")
    assert st.wait(5) == 0 and st.stdout.read() == "not running\n"


def test_bad_requests_keep_the_server(fake, tmp_path):
    assert fake.done(fake.say())[0] == 0
    for data in (b"[1]\n", b"3\n", b"null\n", b"\xff\xfe\n", b"{\n",
                 protocol.line({}), protocol.line({"cmd": "speak", "text": 5}),
                 protocol.line({"cmd": "hold", "pid": 1e30}),
                 protocol.line({"cmd": "hold", "pid": 99999999999}),
                 protocol.line({"cmd": "hold", "pid": "x"})):
        assert "bad request" in fake.raw(data)["error"], data
    # a request that fails while speaking: an unreadable transcript
    (tmp_path / "x.wav").write_bytes(b"")
    (tmp_path / "x.txt").write_bytes(b"\xe5\n")
    code, err = fake.done(fake.say("Hei.", "-v", str(tmp_path / "x.wav")))
    assert code == 1 and "not UTF-8" in err
    assert fake.done(fake.say())[0] == 0
    assert fake.started() == 1 and len(fake.servers()) == 1


def test_bad_voice_at_warm_up(fake):
    code, err = fake.done(fake.say("Hello there, this is a test.",
                                   extra={"SI_VOICE_NO": "nope"}))
    assert code == 0, err
    assert "warm-up skipped voice 'nope'" in fake.log()
    code, err = fake.done(fake.say("Hei, dette er en test.",
                                   extra={"SI_VOICE_NO": "nope"}))
    assert code == 1 and err == ("si: no such voice: nope (voices: "
                                 f"{', '.join(voices.voice_names())}; or a "
                                 "path to a .wav)\n")
    assert len(fake.servers()) == 1


# ------------------------------------------------------------------ signals

@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_while_queued(fake, sig):
    fake.warm(extra={"SI_FAKE": "piece=0.5"})
    first = fake.say("Dette er en setning. " * 10)
    time.sleep(0.5)
    queued = fake.say(start_new_session=True)
    time.sleep(1)
    t = time.time()
    os.killpg(queued.pid, sig)
    assert queued.wait(5) == -sig and time.time() - t < 1
    assert first.wait(30) == 0 and len(fake.servers()) == 1


@pytest.mark.parametrize("delay", [0.05, 0.15, 0.25, 0.35, 0.5, 0.8])
def test_sigterm_during_startup_kills(fake, delay):
    """SIGTERM while the client starts up (importing sounddevice, opening
    the audio stream) must stop it, never be swallowed."""
    fake.warm(extra={"SI_FAKE": "piece=0.05"})
    p = fake.run("Dette er en setning. " * 20, start_new_session=True)
    time.sleep(delay)
    os.killpg(p.pid, signal.SIGTERM)
    assert p.wait(5) == -signal.SIGTERM


LATE = """
import atexit, os, signal, threading, time
from si import cli, client
from si.errors import Fail

def speak(*a):
    threading.Timer(0.3, os.kill, (os.getpid(), {sig})).start()
    if {fail}:
        raise Fail("test")
    return "Hei."

client.speak = speak
atexit.register(time.sleep, 3)  # the interpreter's exit takes 3 s
cli.main()
"""


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_after_speaking_kills(tmp_path, sig, fail):
    """A signal after speak() has returned (or failed), while the process
    exits, still kills it by that signal, at once and without a
    traceback."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["SI_FAKE"] = ""  # the defaults; speak() is replaced anyway
    argv = ["--instruct", "calm", "-o", str(tmp_path / "x.wav"), "Hei."]
    t = time.time()
    p = subprocess.run([sys.executable, "-c", LATE.format(sig=int(sig), fail=fail),
                        *argv], env=silent(env, argv), capture_output=True,
                       text=True, timeout=10)
    assert p.returncode == -sig, p.stderr
    assert "Traceback" not in p.stderr and time.time() - t < 2.5
    assert (tmp_path / "x.txt").exists() != fail


# --------------------------------------- idle exit, worker death, lost files

def raw_speak(cache, text="Hei."):
    """A speech request over a raw socket: "done", or the error."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(os.path.join(cache, "sock"))
            s.sendall(protocol.line({"cmd": "speak", "text": text}))
            list(protocol.pieces(s.makefile("rb")))
        return "done"
    except Exception as e:  # noqa: BLE001 (the result)
        return repr(e)


def test_idle_exit_never_kills_a_request(fake):
    """With IDLE 0 the idle time has always run out, so every moment the
    server looks idle between two queued requests is one where it may exit
    (it did: the worker had taken the next job but not yet set beat). A
    flood of statuses keeps the main thread checking meanwhile; none may
    report a stall."""
    sock = os.path.join(fake.cache, "sock")
    for _ in range(3):
        assert fake.run("--warm", extra={"SI_FAKE": "load=1 piece=0.002",
                                         "SI_IDLE": "0"}).wait(5) == 0
        wait_for(lambda: os.path.exists(sock), what="the socket", every=0.01)
        results, stalls = [], []
        jobs = [threading.Thread(target=lambda: results.append(raw_speak(fake.cache)))
                for _ in range(30)]
        for t in jobs:
            t.start()

        def flood():  # no pause: as many statuses as it can
            if not any(t.is_alive() for t in jobs):
                return True
            with contextlib.suppress(OSError, ValueError):
                stalls.append(fake.raw(STATUS).get("stalled"))

        wait_for(flood, 60, "the 30 requests", every=0)
        assert results == ["done"] * 30, results
        assert max(x or 0 for x in stalls) < 0.5, max(stalls)
        wait_for(lambda: not fake.servers(), 5, "the server to go idle")
    assert fake.log().count("idle, exiting") == 3


def test_worker_dies(fake):
    """If the worker dies, the server exits: no queued client waits. A
    client that got no reply and finds no server tries once more (with a
    new server), so the request that kills the worker may kill a second
    one; it fails, and the others are spoken or fail."""
    fake.warm(extra={"SI_FAKE": "piece=0.3"})
    t = time.time()
    procs = [fake.say("Dette er en setning. " * 12)]  # busy for 1.2 s
    time.sleep(0.5)
    procs += [fake.say("die-worker")]
    time.sleep(0.3)
    procs += [fake.say() for _ in range(3)]  # queued behind it
    (code, err), (dcode, derr), *rest = fake.wait(*procs)
    assert code == 0, err
    assert dcode == 1 and derr.endswith("si: the server went away\n")
    for code, err in rest:
        assert code == 0 or err.endswith("the server went away\n"), err
    assert time.time() - t < 10
    assert fake.log().count("the worker died") in (1, 2)


@pytest.mark.parametrize("what", ["sock", "server.lock"])
@pytest.mark.parametrize("how", ["deleted", "replaced"])
def test_lost_socket_or_lock(fake, what, how):
    """A held server whose socket or lock file is deleted or replaced
    exits (no client could reach it, or a second server could start); it
    leaves another's file alone."""
    fake.warm("--hold", str(os.getpid()))
    path = os.path.join(fake.cache, what)
    os.unlink(path)
    if how == "replaced":
        open(path + ".new", "w").close()
        os.rename(path + ".new", path)
    wait_for(lambda: not fake.servers(), 3, "the server to exit")
    assert f"lost {path}, exiting" in fake.log()
    assert os.path.exists(path) == (how == "replaced")


# ------------------------------------------------------------------ retries

def connected(pid):
    """Has process pid a connected Unix socket?"""
    out = subprocess.run(["lsof", "-a", "-U", "-p", str(pid)],
                         capture_output=True, text=True).stdout
    return "->0x" in out


@pytest.mark.parametrize("who", ["say", "warm"])
@pytest.mark.parametrize("how", ["stop", "idle"])
def test_retry_when_the_server_exits_as_we_connect(fake, how, who):
    """A server that exits (on --stop, or idle) drops the connections it
    has not taken. Such a client gets no reply and finds no server, so it
    starts one and asks again. Here a raw client keeps the server's main
    thread waiting for its request while the client connects, then sends
    STOP (the client is dropped for certain) or, for "idle", STATUS while
    the worker waits to see that the holder has died and IDLE (0) is up
    (so it is most likely dropped; else it is simply taken). --warm --hold
    (its hold request) is asked again the same way."""
    holder = subprocess.Popen(["sleep", "60"])
    fake.warm("--hold", str(holder.pid), extra={"SI_IDLE": "0"})
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as r:
        r.connect(config.sock_path())
        time.sleep(0.2)  # taken: the main thread reads its request
        holder.kill()
        holder.wait()
        if how == "idle":
            time.sleep(1.2)  # the worker's next check waits for the lock
        p = fake.say() if who == "say" else fake.run("--warm", "--hold",
                                                     str(os.getpid()))
        wait_for(lambda: connected(p.pid), 3, "the client to connect")
        r.sendall(protocol.line(protocol.STOP if how == "stop"
                                else protocol.STATUS))
        code, err = fake.done(p)
    assert code == 0, err
    if how == "stop" or "warming" in p.stdout.read():
        # for the new server (the fixture kills it once it listens)
        wait_for(lambda: fake.started() >= 2, 3, "the new server")


def load_failed(fake):
    return ("si: couldn't download the model mlx-community/VoxCPM2-8bit "
            "(no network, or Hugging Face can't be reached); see "
            f"{os.path.join(fake.cache, 'server.log')}\n")


def test_load_failure_goes_to_the_queue(fake):
    """A server whose model fails to load tells every queued client why,
    then exits; they fail at once, and none starts another server."""
    t = time.time()
    procs = [fake.say(extra={"SI_FAKE": "fetch=fail"}) for _ in range(4)]
    for code, err in fake.wait(*procs):
        assert code == 1 and err.endswith(load_failed(fake)), err
    assert time.time() - t < 5
    assert fake.started() == 1 and "loading failed" in fake.log()


def test_load_failure_after_a_retry(fake):
    """A client the failing server has not taken gets EOF; it tries once
    more, and the new server (or the old one, if it took it after all)
    tells it why. Here a raw client keeps the main thread waiting for its
    request while the speech client connects and the load fails."""
    fail = {"SI_FAKE": "fetch=fail"}
    assert fake.run("--warm", extra=fail).wait(5) == 0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as r:
        wait_for(lambda: r.connect_ex(config.sock_path()) == 0, what="the socket")
        p = fake.say(extra=fail)
        wait_for(lambda: connected(p.pid), 3, "the client to connect")
        wait_for(lambda: "loading failed" in fake.log(), what="the failure")
        r.sendall(protocol.line(protocol.STATUS))
        code, err = fake.done(p, timeout=10)
    assert code == 1 and err.endswith(load_failed(fake)), err
    assert fake.started() in (1, 2)


@pytest.mark.parametrize("phase", ["downloading", "loading"])
def test_stop_while_downloading(fake, phase):
    """--stop while the server downloads (or loads) the model: the waiting
    client fails, saying so, rather than start a new server that starts
    over (the user may well have stopped it to abort a 3 GB download)."""
    p = fake.say(extra={"SI_FAKE": "fetch=60" if phase == "downloading"
                        else "load=60"})
    def there():
        with contextlib.suppress(OSError, ValueError):
            return fake.raw(protocol.line(protocol.STATUS))["phase"] == phase

    wait_for(there, 10, f"the server to be {phase}")
    time.sleep(1.5)  # the client has asked for the status
    stop = fake.run("--stop")
    assert stop.wait(5) == 0 and stop.stdout.read() == "stopped\n"
    t = time.time()
    code, err = fake.done(p, timeout=10)
    assert code == 1 and err.endswith(
        f"si: the server exited while {phase} the model\n"), err
    assert time.time() - t < 3
    assert fake.started() == 1


def test_retry_when_stopped_with_a_queue(fake):
    """--stop while one client speaks and 5 wait: the server drops the 5
    before any reply, and they all find it gone at the same moment. Each
    tries once more (one starts a server, the others wait for it) and is
    spoken. The old check (is the lock held? taking it for an instant) saw
    the others' checks, or the new server, as the old one alive, and failed
    in ~1 of 3 runs; so it loops."""
    for i in range(3):
        fake.warm(extra={"SI_FAKE": "piece=0.3"})
        first = fake.say("Dette er en setning. " * 40)  # busy for ~4 s
        time.sleep(0.5)
        queued = [fake.say() for _ in range(5)]
        time.sleep(1)
        assert fake.run("--stop").wait(5) == 0
        results = fake.wait(*queued)
        assert [code for code, _ in results] == [0] * 5, (i, results)
        first.wait(10)
        assert fake.run("--stop").wait(5) == 0
        wait_for(lambda: not fake.servers(), what="the servers to exit")
