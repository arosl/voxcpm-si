"""The server, which keeps the model loaded: one per cache directory. It
holds the lock file for its life, listens before it loads the model (requests
queue meanwhile), answers commands at once from the main thread, and
speaks in a worker thread (which makes every MLX call), one request at a
time. One bad request gets an error reply; the server keeps serving."""

import contextlib
import fcntl
import json
import os
import queue
import select
import socket
import sys
import threading
import time
import traceback
from typing import NoReturn

from si import client, config, protocol, voices
from si.errors import Fail
from si.text import chunks, whole

WARM_TEXT = {"no": "Hei.", "en": "Hello.", "es": "Hola."}  # for the warm-up


class Gone(Exception):
    """The client went away (Ctrl-C, SIGTERM)."""


class State:
    """What the two threads share; each field has one writer. The main
    thread (commands) writes holders, last (the last request) and quit
    (--stop), and puts to jobs; the worker writes phase ("downloading",
    "loading", then "ready"), rate and beat (its last sign of life while it
    speaks; None when idle), and takes from jobs. Only the worker decides
    that the server is idle, and exits it then, under `lock`, which the main
    thread holds while it handles a request: the server never exits with a
    request it took. ino (the socket file's inode) and lockfd are set once."""

    def __init__(self, hold, ino, lockfd):
        self.ino, self.lockfd = ino, lockfd
        self.jobs, self.holders = queue.Queue(), {hold} if hold else set()
        self.phase, self.quit = protocol.LOADING, False
        self.rate, self.beat = None, None
        self.last = time.time()
        self.lock = threading.Lock()


def log(msg):
    print(f"{time.strftime('%F %T')} si: [{os.getpid()}] {msg}",
          flush=True)


def take_lock(wait=1.0):
    """The server lock (an fd to keep open for life), or None if another
    server holds it. It retries for `wait` s: client.server_alive() takes
    it for an instant."""
    fd, deadline = config.lock_fd(), time.time() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.time() < deadline:
                time.sleep(0.05)
                continue
            os.close(fd)
            return None
        os.ftruncate(fd, 0)
        os.write(fd, b"%d\n" % os.getpid())
        return fd


def bind():
    """Listen on the socket (only the lock holder may); returns it and the
    socket file's inode, for unlink_ours."""
    path = config.sock_path()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)  # a dead server's
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(64)
    return srv, os.stat(path).st_ino


def unlink_ours(ino):
    """Remove the socket file if it is still the one we bound."""
    path = config.sock_path()
    with contextlib.suppress(FileNotFoundError):
        if os.stat(path).st_ino == ino:
            os.unlink(path)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def serve(hold=None):
    """Run the server until it is stopped or idle."""
    config.make_cache()
    # The download's byte progress in the log (off when not a TTY), every 5 s.
    os.environ.setdefault("TQDM_POSITION", "-1")
    os.environ.setdefault("TQDM_MININTERVAL", "5")
    lock = take_lock()
    if lock is None:  # another server won; pass the hold on to it
        log("a server is already running")
        if hold:
            with contextlib.suppress(Fail):
                client.request(protocol.hold(hold), wait=60)
        return
    srv, ino = bind()
    srv.settimeout(1)
    log(f"listening on {config.sock_path()}, loading {model_name()}")
    s = State(hold, ino, lock)
    worker = threading.Thread(target=work, args=(s,), daemon=True)
    worker.start()
    try:
        while not s.quit and serving(s, worker):
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            with s.lock:
                try:
                    command(s, conn)
                except Exception:  # noqa: BLE001 (keep serving)
                    traceback.print_exc()
                    conn.close()
    except BaseException:  # noqa: BLE001 (logged)
        traceback.print_exc()
        log("crashed, exiting")
    finish(s, 0 if s.quit else 1)


def serving(s, worker):
    """Can the server go on? Not if the worker died (no queued client would
    get a reply), or the socket or lock file was removed or replaced (no
    client could reach it, or a second server could start)."""
    if not worker.is_alive():
        log("the worker died, exiting")
        return False
    for path, want in ((config.sock_path(), s.ino),
                       (config.lock_path(), os.fstat(s.lockfd).st_ino)):
        try:
            if os.stat(path).st_ino == want:
                continue
        except FileNotFoundError:
            pass
        log(f"lost {path}, exiting")
        return False
    return True


def finish(s, code) -> NoReturn:
    """Exit the server (from either thread, without waiting for the other).
    Clients still queued, or not yet accepted, then get EOF; the lock is
    released first, so that they find no server alive (and may retry)."""
    unlink_ours(s.ino)
    with contextlib.suppress(OSError):  # the other thread's finish closed it
        os.close(s.lockfd)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


# ---------------------------------------------------------------- requests

def command(s, conn):
    """Read one request and pass it to its handler, which returns the
    reply (or None: it keeps conn). Any request is activity."""
    s.last = time.time()
    conn.settimeout(5)
    try:
        line = conn.makefile("rb").readline(2**24)
        if not line:  # a client that connected and left
            conn.close()
            return
        req = protocol.check(json.loads(line))
    except Fail as e:
        log(f"bad request: {e}")
        reply = {"error": str(e)}
    except (OSError, ValueError) as e:
        log(f"bad request: {e}")
        reply = {"error": f"bad request: {e}"}
    else:
        reply = HANDLERS[req["cmd"]](s, req, conn)
        if reply is None:
            return
    with contextlib.suppress(OSError):
        conn.sendall(protocol.line(reply))
    conn.close()


def speak(s, req, conn):
    conn.settimeout(10)  # for sending: the client reads as it plays
    s.jobs.put((conn, req))  # for the worker, which now owns conn


def status(s, req, conn):
    s.holders -= {p for p in s.holders if not pid_alive(p)}
    beat = s.beat  # read once: the worker may clear it meanwhile
    return {"model": config.MODEL, "holders": sorted(s.holders),
            "phase": s.phase, "pid": os.getpid(), "queued": s.jobs.qsize(),
            "stalled": 0 if beat is None else round(time.time() - beat, 1)}


def hold(s, req, conn):
    s.holders.add(req["pid"])
    return status(s, req, conn)


def stop(s, req, conn):
    s.quit = True
    return {"ok": True}


HANDLERS = {"speak": speak, "status": status, "hold": hold, "stop": stop}
assert HANDLERS.keys() == protocol.FIELDS.keys()


# ------------------------------------------------------------------ worker

def work(s):
    """The worker thread: load the model, then speak the queued requests
    one at a time. One request's error goes to its client (and the log).
    It exits the server when it has been idle for IDLE s: no request, no
    job and no holder alive; or when the model fails to load."""
    try:
        synth, clear, s.rate = load(s)
    except BaseException as e:  # noqa: BLE001 (to the clients; the server exits)
        failed(s, e)  # exits the server
    s.phase = protocol.READY
    log("ready")
    active = time.time()  # the end of the last job, or a holder seen alive
    while True:
        try:
            conn, req = s.jobs.get(timeout=1)
        except queue.Empty:
            with s.lock:  # no request is being handled: holders, last are set
                if any(pid_alive(p) for p in s.holders):
                    active = time.time()
                elif (s.jobs.empty() and time.time() - max(active, s.last)
                      > config.IDLE):
                    log("idle, exiting")
                    finish(s, 0)
            continue
        s.beat = time.time()
        try:
            say(s, conn, req, synth)
        except Gone:
            pass
        except Exception as e:  # noqa: BLE001 (to the client)
            msg = why(e)
            log(f"request failed: {msg}")
            with contextlib.suppress(OSError):
                conn.sendall(protocol.line({"error": msg}))
        finally:
            conn.close()
            clear()
            s.beat, active = None, time.time()


def failed(s, e) -> NoReturn:
    """The model failed to load (another server would too): every queued
    client gets why, then the server exits. Clients it has not taken get
    EOF, and try once more: a new server, which tells them why."""
    msg = f"{why(e, trace=True)}; see {config.log_path()}"
    log(f"loading failed: {msg}")
    with s.lock:  # the main thread takes no request meanwhile
        while not s.jobs.empty():
            conn, _ = s.jobs.get()
            with contextlib.suppress(OSError):
                conn.sendall(protocol.line({"error": msg}))
            conn.close()
        finish(s, 1)


def why(e, trace=False):
    """An exception as a message; a traceback in the log if trace, or
    unless it's a Fail (an expected failure, such as a bad voice)."""
    if trace or not isinstance(e, Fail):
        traceback.print_exc()
    return str(e) if isinstance(e, Fail) else f"{type(e).__name__}: {e}"


def say(s, conn, req, synth):
    """Stream each sentence's audio as it is made; stop when the client
    goes away."""
    text = req["text"]
    parts = [whole(text)] if req.get("instruct") else chunks(text)
    voice = voices.voice_args(req.get("voice"), req.get("instruct"), text)
    for chunk in parts:
        if client_gone(conn):
            return
        for audio in synth(chunk, **voice):
            send(conn, protocol.frame(audio, s.rate))
            s.beat = time.time()
    send(conn, protocol.done(s.rate, " ".join(parts)))


def send(conn, data):
    try:
        conn.sendall(data)
    except OSError:
        raise Gone


def client_gone(conn):
    """Has the client closed its end (it never sends after the request)?"""
    if not select.select([conn], [], [], 0)[0]:
        return False
    try:
        return conn.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def model_name():
    return config.MODEL + (f"@{config.REVISION}" if config.REVISION else "")


def cached():
    """The model's directory if it is a local one, or complete in the Hugging
    Face cache (loading it then needs no network); else None."""
    from huggingface_hub import snapshot_download
    from mlx_audio.utils import DEFAULT_ALLOW_PATTERNS

    if os.path.isdir(local := os.path.expanduser(config.MODEL)):
        return local
    try:
        path = snapshot_download(config.MODEL, revision=config.REVISION,
                                 allow_patterns=DEFAULT_ALLOW_PATTERNS,
                                 local_files_only=True)
    except Exception:  # noqa: BLE001 (not there, or incomplete)
        return None
    return path if complete(path) else None


def complete(path):
    """Has the snapshot in path all that loading needs: the model's config,
    its tokenizer (AutoTokenizer, in VoxCPM2's post_load_hook) and all its
    weights (the AudioVAE's are in them)? snapshot_download checks a
    snapshot only against its cached file list (trees/<commit>.json), which
    a cache filled otherwise lacks."""
    def has(name):  # a file, or a link to a whole blob
        return os.path.isfile(os.path.join(path, name))

    index = "model.safetensors.index.json"
    if has(index):
        with open(os.path.join(path, index)) as f:
            weights = set(json.load(f).get("weight_map", {}).values())
    else:
        weights = [n for n in os.listdir(path) if n.endswith(".safetensors")]
    needs = ("config.json", "tokenizer.json", "tokenizer_config.json")
    return (all(map(has, needs)) and bool(weights)
            and all(map(has, weights)))


def fetch(s, get=None, is_cached=cached):
    """The model's local path: the cached one, or else downloaded (phase
    "downloading" meanwhile; the progress goes to the log). get (default:
    mlx-audio's get_model_path, which may go online even when the model is
    cached) and is_cached are seams for tests."""
    if get is None:
        from mlx_audio.utils import get_model_path as get

    if path := is_cached():
        return path
    s.phase = protocol.DOWNLOADING
    log(f"downloading {model_name()} into the Hugging Face cache")
    try:
        path = get(config.MODEL, revision=config.REVISION)
    except Exception as e:  # noqa: BLE001 (logged with its cause)
        raise Fail(download_failed(e)) from e
    print(file=sys.stderr, flush=True)  # after the progress bars
    log("downloaded")
    s.phase = protocol.LOADING
    return path


def download_failed(e):
    """Why the model couldn't be fetched, in a line for the user."""
    import httpx
    from huggingface_hub import errors

    reasons = (  # the first that matches
        (errors.OfflineModeIsEnabled, "HF_HUB_OFFLINE is set"),
        ((httpx.TransportError, errors.LocalEntryNotFoundError),
         "no network, or Hugging Face can't be reached"),
        (errors.RevisionNotFoundError, f"no revision {config.REVISION}"),
        (errors.RepositoryNotFoundError, "no such model on Hugging Face"))
    reason = next((r for kind, r in reasons if isinstance(e, kind)), None)
    reason = reason or (
        f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:200]}")
    return f"couldn't download the model {config.MODEL} ({reason})"


def model_load(s):
    """Fetch, load and warm up the model: (synth(text, **kwargs) -> audio
    pieces, clear the MLX cache, the sample rate)."""
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model

    from si.stream import stream

    # Each sentence has new shapes, so MLX's buffer cache would otherwise
    # keep growing (tens of GB); the model is ~3.3 GB resident, 5-7 at peak.
    mx.set_cache_limit(512 * 2**20)
    model = load_model(fetch(s))

    def synth(text, **kw):
        return stream(model, text, inference_timesteps=config.STEPS, **kw)

    warm_up(synth)
    return synth, mx.clear_cache, model.sample_rate


def fake_load(s):
    """model_load() for tests (SI_FAKE, config.FAKE): no model,
    silence; the real fetch(), with a download that sleeps (or fails as if
    offline). The text "die-worker." kills the worker."""
    import httpx
    import numpy as np

    fake = config.FAKE

    def get(model, revision):
        time.sleep(1 if fake["fetch"] == "fail" else fake["fetch"])
        if fake["fetch"] == "fail":
            raise httpx.ConnectError("test: no network")
        return "fake"

    fetch(s, get, is_cached=lambda: None if fake["fetch"] else "fake")

    def synth(text, **kw):
        if text == "die-worker.":  # not an Exception: it ends the worker
            raise BaseException("test: the worker dies")
        for _ in range(2):
            time.sleep(fake["piece"])
            yield np.zeros(7680, np.float32)

    time.sleep(fake["load"])
    warm_up(synth)
    return synth, lambda: None, 48000


load = model_load if config.FAKE is None else fake_load


def warm_up(synth):
    """The first generation is slower, and so is a voice's first (cached)
    encoding, ~20 s; so speak once with each default voice (a language that
    falls back to another's voice adds nothing). A voice that fails is
    logged and skipped."""
    done = set()
    for lang in voices.DEFAULT_VOICES:
        voice, text = voices.default_voice(lang), WARM_TEXT.get(lang, "OK.")
        if voice in done:
            continue
        done.add(voice)
        try:
            args = voices.voice_args(voices.resolve_voice(voice), text=text)
            for _ in synth(text, **args):
                pass
        except Exception as e:  # noqa: BLE001 (logged)
            log(f"warm-up skipped voice {voice!r} ({lang}): {why(e)}")
