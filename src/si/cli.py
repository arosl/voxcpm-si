"""si: say(1) for VoxCPM2 TTS on Apple Silicon.

    si [-v NAME|PATH] [-r WPM] [--speed X] [-o FILE.wav] [TEXT ...]
    si --instruct DESC -o ref.wav TEXT   design a new voice
    si --warm [--hold PID]     load the model now (keep it while PID runs)
    si --stop | --status | --voices

The command line. The first call starts a background server that keeps the
model loaded (server.py); each call is a client of it (client.py) and
plays the audio as it streams in. README.md documents the behaviour and
the environment variables.
"""

import argparse
import os
import signal
import sys

from si import client, config, protocol, server, voices
from si.errors import Fail, NotRunning
from si.lang import language

HELP = """\
voices:
  Without -v the voice follows the text's language: Norwegian text gets
  no-ulf, Spanish es-juan, and English (or text whose language isn't clear)
  en-tim.
  --voices lists every voice you can name. To use another voice:
    -v NAME          a listed voice, for all text
    -v FILE.wav      any clean 5-15 s recording of one speaker; with the
                     words it says in FILE.txt next to it, it sounds closer
    --instruct DESC  invent a voice from a description; it changes every
                     call, so save it with -o and use that file with -v
  Your own voices go in ~/.config/si/voices/NAME.wav (+ NAME.txt);
  then -v NAME works, and SI_VOICE_EN=NAME (or _NO, _ES) makes NAME
  the default for that language.

examples:
  si "Hei, dette er en test."
  git log -1 --format=%B | si
  si -r 220 -o hello.wav "Hello there."
  si --speed 0.9 "A little slower than the voice's own pace."
  si -v no-ulf "Read this English text in the Norwegian voice."
  si --instruct "A calm older woman with a warm voice" \\
      -o ~/.config/si/voices/anna.wav "Hello, I'm Anna. Nice to meet you."
  si -v anna "Now speaking in Anna's voice."
  si --warm --hold $$     # preload; keep loaded while this shell runs

exit status:
  0 when playback has finished, 1 on failure (a short message on stderr),
  2 on bad usage. Ctrl-C (SIGINT) or SIGTERM stops the sound at once, and
  the process dies by that signal (-2 / -15), like say(1). To stop a
  background reading, kill its process group.

environment (meanings and defaults: README.md):
  SI_VOICE, SI_VOICE_EN/_NO/_ES, SI_RATE, SI_SPEED,
  SI_TIMEOUT, SI_CACHE, SI_DEBUG; and, read when
  the server starts (--stop to restart it), SI_IDLE, _STEPS, _MODEL,
  _REVISION; and Hugging Face's HF_HOME (where the model is downloaded).

server log: server.log in the cache directory ($SI_CACHE)"""


class Terminated(BaseException):
    """SIGTERM in the client: stop the sound, then die by SIGTERM. Like
    KeyboardInterrupt, no `except Exception` may swallow it."""


speaking = False  # the signal handlers raise (to stop the sound) or kill


def on_signal(signum, frame):
    """SIGINT or SIGTERM in the client: while it speaks, raise (the sound
    stops, then main() dies by the signal); after that, die at once (no
    traceback from the rest of run() or from the interpreter's exit)."""
    if speaking:
        raise KeyboardInterrupt if signum == signal.SIGINT else Terminated
    die(signum)


def die(signum):
    """Die by the signal, like say(1): exit -2 (SIGINT) or -15 (SIGTERM)."""
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def pid(arg):
    """A --hold PID: a positive process id (0 and -1 would mean groups)."""
    if not arg.isdigit() or not 0 < int(arg) < 2**31:
        raise argparse.ArgumentTypeError(f"not a process id: {arg}")
    return int(arg)


def wpm(arg):
    """A -r rate: words per minute, as for say(1). A small number is
    probably meant as a speed factor."""
    try:
        rate = float(arg)
    except ValueError:
        rate = 0
    if not rate > 0:
        raise argparse.ArgumentTypeError(f"not words per minute: {arg}")
    if rate < 20:
        raise argparse.ArgumentTypeError(
            f"{arg} words per minute? -r is words per minute, like say's "
            f"(e.g. -r 200); for a speed factor use --speed {arg}")
    return rate


def parser():
    ap = argparse.ArgumentParser(
        prog="si", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="say(1) for VoxCPM2 TTS: speak TEXT (or stdin) with the "
        "model kept warm in a background server.\nThe voice follows the "
        "text's language (see --voices); playback starts while the rest is "
        "still being made.", epilog=HELP)
    ap.add_argument("text", nargs="*",
                    help="the text to speak (default: read stdin)")
    ap.add_argument("-v", "--voice", metavar="NAME|PATH",
                    default=os.environ.get("SI_VOICE") or None,
                    help="a listed voice (see --voices) or a reference .wav "
                    "to clone, for text in any language (default: "
                    "$SI_VOICE, else one by the text's language: "
                    "$SI_VOICE_NO, _EN or _ES, else the bundled default)")
    ap.add_argument("--voices", action="store_true",
                    help="list the voices (yours and the bundled ones) and "
                    "the default per language")
    ap.add_argument("--instruct", metavar="DESC",
                    help="design a new voice from a description instead "
                    "(the text is spoken as one piece; with -o also writes "
                    "the .txt, so the result can be used as a voice)")
    ap.add_argument("-r", "--rate", type=wpm, metavar="WPM",
                    default=os.environ.get("SI_RATE") or None,
                    help="speak at WPM words per minute, keeping the pitch "
                    "(default: the voice's own pace, ~160-185, or $SI_RATE); "
                    "within half to twice the voice's pace")
    ap.add_argument("--speed", type=float, metavar="X",
                    default=os.environ.get("SI_SPEED", "1.0"),
                    help="speed factor, keeping the pitch, 0.25-4 (default "
                    "1.0, or $SI_SPEED); with -r, of that rate")
    ap.add_argument("-o", "--output", metavar="FILE.wav",
                    help="write the audio instead of playing it")
    ap.add_argument("--warm", action="store_true",
                    help="start the server (load the model) in the background "
                    "without speaking, and return at once")
    ap.add_argument("--hold", type=pid, metavar="PID",
                    help="implies --warm: keep the model loaded while PID "
                    "runs; the idle time starts when it exits")
    ap.add_argument("--stop", action="store_true", help="stop the server")
    ap.add_argument("--status", action="store_true",
                    help="is the server running?")
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    return ap


def main():
    try:
        run()
    except KeyboardInterrupt:
        die(signal.SIGINT)
    except Terminated:
        die(signal.SIGTERM)
    except (Fail, OSError) as e:
        sys.exit(f"si: {e}")


def run():
    global speaking
    # Without a PYTHONPATH from outside (a Nix shell's Python 3.12
    # site-packages break mlx-audio's dependencies); so the server this
    # process may start is without it too.
    if "PYTHONPATH" in os.environ:
        os.execve(sys.executable, [sys.executable, "-m", "si.cli",
                                   *sys.argv[1:]],
                  {k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    args = parser().parse_args()
    if args.serve:
        return server.serve(args.hold)
    if args.status:
        return status()
    if args.warm or args.hold:
        return warm(args.hold)
    if args.stop:
        try:
            client.request(protocol.STOP)
        except NotRunning:
            return print("not running")
        return print("stopped")
    if args.voices:
        for line in voices.listing():
            print(line)
        return
    if not voices.SPEEDS[0] <= args.speed <= voices.SPEEDS[1]:
        raise Fail("the speed must be between 0.25 and 4")
    text = " ".join(args.text) if args.text else sys.stdin.read()
    if not text.strip():
        return
    voice = None if args.instruct else voices.resolve_voice(
        args.voice if args.voice is not None
        else voices.default_voice(language(text)))
    speaking = True
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        said = client.speak(text, voice, args.instruct, voices.factor(
            voice, args.rate, args.speed), args.output)
    finally:
        speaking = False
    if args.instruct and args.output:  # so the .wav can be a voice
        with open(os.path.splitext(args.output)[0] + ".txt", "w") as f:
            f.write(said + "\n")


def status():
    try:
        reply = client.request(protocol.STATUS)
    except NotRunning:
        return print("not running")
    print(describe("running", reply))


def warm(hold):
    """--warm [--hold PID]: start a server if none runs (it loads in the
    background: this returns at once)."""
    try:
        reply = client.request(protocol.hold(hold) if hold else protocol.STATUS)
    except NotRunning:
        client.spawn(hold)
        return print(f"warming: loading {config.MODEL} in the background "
                     "(the first time, it downloads it first: see --status)")
    print(describe("warm", reply))


def describe(state, reply):
    """A status reply as a line: `state` unless it is still downloading or
    loading the model."""
    phase = reply.get("phase")
    state = phase if phase in protocol.STARTING else state
    return (f"{state}: {reply.get('model')}"
            + (f", held by {reply['holders']}" if reply.get("holders") else "")
            + (f" (progress: tail -f {config.log_path()})"
               if phase == protocol.DOWNLOADING else ""))


if __name__ == "__main__":
    main()
