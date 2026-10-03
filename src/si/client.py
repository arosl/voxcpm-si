"""The client: reach the server (starting one if none holds the lock), send
it a request, and play or write the audio it streams back."""

import collections
import contextlib
import fcntl
import os
import select
import socket
import subprocess
import sys
import threading
import time
import wave

from si import config, protocol
from si.errors import Fail, NotRunning

BUFFER = 0.4  # seconds of audio to buffer before playing (x the rate if > 1)


def server_alive():
    """Does a server hold the lock (serving, or still starting)?"""
    fd = config.lock_fd()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)  # releases it


def connect(start=True, wait=60):
    """A socket connected to the server. With none running, start one (or
    raise NotRunning); while one is starting (it holds the lock, but isn't
    listening yet), wait up to `wait` s for it."""
    config.make_cache()
    proc, deadline = None, time.time() + wait
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(config.sock_path())
            return s
        except (FileNotFoundError, ConnectionRefusedError):
            s.close()
        if not server_alive():
            if not start:
                raise NotRunning("not running")
            if proc and proc.poll() is not None:
                raise Fail("the server failed to start; see "
                           + config.log_path())
            if not proc:
                note("starting VoxCPM2")
                proc = spawn()
        if time.time() > deadline:
            raise Fail("the server is not answering; see " + config.log_path())
        time.sleep(0.1)


def note(msg):
    """A progress line for the user, while a server starts."""
    print(f"… {msg}", file=sys.stderr, flush=True)


def spawn(hold=None):
    """Start a server in its own session (so it survives its client), with
    this environment (without PYTHONPATH: cli.run saw to that)."""
    with open(config.log_path(), "a") as f:
        return subprocess.Popen(
            [sys.executable, "-m", "si.cli", "--serve",
             *(["--hold", str(hold)] if hold else [])],
            stdout=f, stderr=f,
            stdin=subprocess.DEVNULL, start_new_session=True)


class Dropped(Exception):
    """The server closed (or reset) the connection, or is exiting, before
    any reply; phase is the last phase of it this client saw (None: none)."""

    def __init__(self, phase=None):
        super().__init__(phase)
        self.phase = phase


def peer(s):
    """The pid of the server at the other end of Unix socket s (macOS's
    LOCAL_PEERPID: set by connect, before the server accepts), or None if
    that server has gone."""
    try:
        return s.getsockopt(0, 2)  # SOL_LOCAL, LOCAL_PEERPID
    except OSError:
        return None


def listener():
    """The pid of the server listening on the socket now, or None."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        try:
            s.connect(config.sock_path())
        except OSError:
            return None
        return peer(s)


def once_more(req, start=True, wait=60, play=False):
    """exchange(s, req, play) with s from connect(start, wait): the socket,
    once the reply has begun. A server that exits (stopped, or idle) drops
    the connections it has not taken, after it has unlinked its socket; so
    if it dropped ours before any reply (Dropped) and no longer listens, try
    once more, with whichever server listens now (or a new one). Never once
    a reply (audio or an error) has begun, nor if it was still downloading
    or loading the model: it exited (--stop, as to abort the first
    download; or it crashed), and a new one would start over."""
    for again in (True, False):
        s = connect(start, wait)
        pid = peer(s)
        try:
            return exchange(s, req, play)
        except Dropped as e:
            s.close()
            phase = e.phase
        except BaseException:
            s.close()
            raise
        # A phase seen means our server had queued this request: it accepts
        # connections in order, so it took ours before the status request
        # that told us the phase. So had the model failed to load, failed()
        # (which answers every queued client) would have said why: EOF
        # instead means the server exited.
        if phase in protocol.STARTING:
            raise Fail(f"the server exited while {phase} the model")
        if not again or (pid and listener() == pid):
            raise Fail("the server went away")


def exchange(s, req, play):
    """Send req on s; s, once its reply has begun. A command's reply comes
    at once (within 10 s); speech waits for the server (await_reply)."""
    phase, speech = None, req["cmd"] == "speak"
    if not speech:
        s.settimeout(10)
    try:
        s.sendall(protocol.line(req))
        if play and output is device:  # ~0.4 s, so while the server starts on it
            with contextlib.suppress(ImportError, OSError):
                import sounddevice  # noqa: F401
        if speech:
            phase = await_reply(s)
        if not s.recv(1, socket.MSG_PEEK):
            raise Dropped(phase)
    except ConnectionError:  # reset as it exits
        raise Dropped(phase) from None
    return s


def request(req, wait=5):
    """Send a command to a running server; its reply."""
    try:
        with once_more(req, False, wait) as s:
            return protocol.reply(s.makefile("rb"), req)
    except TimeoutError:
        raise Fail("the server is not answering")
    except OSError as e:
        raise Fail(f"the server went away ({e})")


def await_reply(s):
    """Wait for the first reply; the server's last phase seen (None: it
    wasn't asked). That can take long while the model loads (or downloads)
    or other requests go first, so it checks the server's progress rather
    than time out (unless it makes none for TIMEOUT s), and says when it
    downloads. (The status may come from a newer server, if ours exits as
    it is asked: only our server's phase counts.)"""
    deadline, poll, download = time.time() + config.START, 1, Download()
    phase, ours = None, peer(s)
    while not select.select([s], [], [], min(config.TIMEOUT, poll))[0]:
        try:
            st = request(protocol.STATUS)
        except Fail:  # none running, or it exits as we ask
            if select.select([s], [], [], 0)[0]:
                break  # but its reply came (why the model failed to load)
            raise Dropped(phase)
        if ours and st.get("pid") == ours:
            phase = st.get("phase")
        ready = st.get("phase") == protocol.READY
        poll = 5 if ready else 1
        download.update(st)
        if time.time() > deadline or (
                ready and st.get("stalled", 0) > config.TIMEOUT):
            raise Fail("the server timed out")
    return phase


class Download:
    """Tells the user while the server downloads the model: when it starts,
    every minute after, and when it is done."""

    def __init__(self):
        self.since = self.last = None

    def update(self, st):  # a status reply
        now, downloading = time.time(), st.get("phase") == protocol.DOWNLOADING
        if downloading and self.since is None:
            self.since = self.last = now
            size = (" (about 3 GB)" if st.get("model") == config.DEFAULT_MODEL
                    else "")
            note(f"downloading {st.get('model')}{size}, only the first time; "
                f"progress: tail -f {config.log_path()}")
        elif downloading and now - self.last >= 60:
            self.last = now
            note(f"still downloading ({round((now - self.since) / 60)} min)")
        elif not downloading and self.last is not None:
            self.last = None
            note("downloaded; loading the model")


def speak(text, voice, instruct=None, rate=1.0, out=None):
    """Play (or with out, write) the audio as the server streams it;
    returns the text as the server spoke it."""
    from si.stretch import Stretch

    stretch, t0, sink = Stretch(rate), time.time(), None
    try:
        with once_more(protocol.speak(text, voice, instruct),
                       play=not out) as s:
            s.settimeout(config.TIMEOUT)
            for r in protocol.pieces(s.makefile("rb")):
                sink = sink or (
                    Wav(out, r["rate"]) if out
                    else Player(r["rate"], BUFFER * max(rate, 1), t0))
                if "audio" in r:
                    sink.add(stretch.add(r["audio"]))
                else:  # done
                    sink.add(stretch.flush())
                    said = r["text"]
        sink.finish()
        return said
    except BaseException:
        if sink:
            sink.abort()  # the sound stops now
        raise


class Wav:
    """The sink for -o: the audio as a 16-bit mono .wav, written at the end."""

    def __init__(self, path, rate):
        self.path, self.rate, self.audio = path, rate, []

    def add(self, x):
        self.audio.append(x)

    def finish(self):
        import numpy as np

        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with wave.open(self.path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(protocol.pcm16(np.concatenate(self.audio)))

    def abort(self):
        pass


class Player:
    """The sink for playback: one output stream, fed from a buffer. It
    starts playing when `start` seconds are buffered (or all the audio is
    in). If it runs dry before the end (synthesis slower than real time: a
    busy GPU), it waits for twice as much each time, so it stalls a few
    times rather than stutter. t0 is when the audio was asked for (`first`
    is the delay from it)."""

    def __init__(self, rate, start, t0):
        self.finished = threading.Event()
        # end: the backend's exception class that stops the stream when
        # the callback raises it (sounddevice.CallbackStop)
        try:
            self.stream, self.end = output(
                samplerate=rate, channels=1, dtype="float32",
                callback=self.callback, finished_callback=self.finished.set)
        except Exception as e:  # noqa: BLE001 (no device, no PortAudio)
            raise Fail(f"no audio output: {e}")
        self.start = int(start * rate)
        self.queue, self.buffered = collections.deque(), 0
        self.lock = threading.Lock()
        self.waiting, self.done = True, False
        self.t0, self.first, self.dry = t0, None, 0
        self.stream.start()

    def add(self, x):
        with self.lock:
            self.queue.append(x)
            self.buffered += len(x)

    def callback(self, out, frames, t, status):
        with self.lock:
            if self.waiting and (self.buffered >= self.start or self.done):
                self.waiting = False
                self.first = self.first or time.time() - self.t0
            n = 0
            while not self.waiting and n < frames and self.queue:
                x = self.queue.popleft()
                k = min(frames - n, len(x))
                out[n:n + k, 0] = x[:k]
                if k < len(x):
                    self.queue.appendleft(x[k:])
                n += k
            self.buffered -= n
            out[n:] = 0
            if n < frames and self.done:
                raise self.end  # this block still plays
            if n < frames and not self.waiting:
                self.waiting, self.dry = True, self.dry + 1
                self.start *= 2

    def finish(self):
        """Wait until everything has played."""
        with self.lock:
            self.done = True
            left = self.buffered / self.stream.samplerate
        deadline = time.time() + left + 5
        while not self.finished.wait(0.05):
            if time.time() > deadline:
                raise Fail("the audio output stalled")
        self.stream.close()
        if config.DEBUG:
            print(f"si: first audio after {self.first:.2f} s, "
                  f"{self.dry} underruns", file=sys.stderr)

    def abort(self):
        self.stream.abort()  # drops what's queued: the sound stops now
        self.stream.close()


def device(**kw):
    """The audio output: a sounddevice OutputStream, and the exception its
    callback raises to end the stream."""
    import sounddevice as sd

    return sd.OutputStream(**kw), sd.CallbackStop


class NullStream:
    """Tests only (SI_FAKE): sounddevice's OutputStream without a
    device. It pulls the audio at the same pace and drops it, so no test
    plays sound or touches the audio output."""

    BLOCK = 1024

    class Stop(Exception):
        """sounddevice's CallbackStop, for this stream."""

    def __init__(self, samplerate, channels, dtype, callback, finished_callback):
        self.samplerate, self.callback = samplerate, callback
        self.finished_callback = finished_callback
        self.stopped = threading.Event()

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        import numpy as np

        out = np.zeros((self.BLOCK, 1), dtype="float32")
        while not self.stopped.wait(self.BLOCK / self.samplerate):
            try:
                self.callback(out, self.BLOCK, None, None)
            except self.Stop:
                break
        self.finished_callback()

    def abort(self):
        self.stopped.set()

    close = abort


def null(**kw):
    """device() for tests: a NullStream."""
    return NullStream(**kw), NullStream.Stop


output = device if config.FAKE is None else null
