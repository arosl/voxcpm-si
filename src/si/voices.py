"""Voices: a name (yours, then bundled) or a .wav path, the default voice
per language, the generate() arguments for speaking with one, and its
pace (for -r)."""

import os
import re
import wave

from si.errors import Fail
from si.lang import language

# Voices are NAME.wav (+ NAME.txt) in MINE (yours), then in BUNDLED.
MINE = os.path.join(os.path.expanduser(
    os.environ.get("XDG_CONFIG_HOME") or "~/.config"), "si", "voices")
BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
# The bundled voice per language of the text (lang.language()), used
# without -v or SI_VOICE. Empty: FALLBACK's voice; empty there too:
# zero-shot, a random speaker on every call.
DEFAULT_VOICES = {"no": "no-ulf", "en": "en-tim", "es": "es-juan"}
FALLBACK = "en"  # also the language of text that language() can't tell

# -r: the words per minute of speech made with a bundled voice, measured on
# a 50-55 word paragraph in its language (8 steps, speech from the first
# sound to the last, pauses included). Another voice's pace
# follows its clip's (transcript words / speech time) at about the power
# PULL; without a transcript, or with --instruct, it is PACE.
PACES = {"no-ulf": 178, "en-tim": 184, "es-juan": 162}
PACE = 175
PULL = 0.6
RATES = (0.5, 2.0)  # what -r may do to a voice's pace (slower, faster)
SPEEDS = (0.25, 4.0)  # --speed, and the factor of both


def names_in(d):
    try:
        return {n[:-4] for n in os.listdir(d) if n.endswith(".wav")}
    except FileNotFoundError:
        return set()


def voice_names():
    """The voice names -v accepts: yours and the bundled ones."""
    return sorted(names_in(MINE) | names_in(BUNDLED))


def resolve_voice(voice):
    """A voice NAME (yours, then bundled) or a path to a .wav -> the
    absolute .wav path."""
    if not voice:
        return None
    for d in (MINE, BUNDLED):
        named = os.path.join(d, voice + ".wav")
        if os.sep not in voice and os.path.isfile(named):
            return named
    path = os.path.abspath(os.path.expanduser(voice))
    if not os.path.isfile(path):
        names = ", ".join(voice_names()) or "none"
        raise Fail(f"no such voice: {voice} (voices: {names}; "
                   "or a path to a .wav)")
    return path


def default_voice(lang):
    """The voice for text in lang (None: unknown) without -v or
    SI_VOICE: $SI_VOICE_<LANG>, else DEFAULT_VOICES[lang],
    else the same for FALLBACK."""
    for code in (lang or FALLBACK, FALLBACK):
        voice = (os.environ.get("SI_VOICE_" + code.upper())
                 or DEFAULT_VOICES.get(code))
        if voice:
            return voice
    return None


def voice_args(voice, instruct=None, text=""):
    """generate() arguments for speaking text with a reference .wav. With a
    transcript next to it (NAME.txt), the clip is also the prompt to
    continue, which keeps the speaker and the words more reliably than the
    reference alone; but not for text in another language, which the
    prompt would give an accent."""
    if instruct:
        return {"instruct": instruct}
    if not voice:
        return {}
    txt = os.path.splitext(voice)[0] + ".txt"
    if not os.path.isfile(txt):
        return {"ref_audio": voice}
    try:
        with open(txt, encoding="utf-8") as f:
            said = " ".join(f.read().split())
    except UnicodeDecodeError:
        raise Fail(f"not UTF-8 text: {txt}")
    if language(text) not in (None, language(said)):
        return {"ref_audio": voice}
    return {"ref_audio": voice, "prompt_audio": voice, "prompt_text": said}


def words(text):
    """The number of words in text (as -r counts them)."""
    return len(re.findall(r"\w+(?:['’-]\w+)*", text))


def pace(voice):
    """The words per minute speech made with voice (a .wav path, or None)
    has, without -r and --speed."""
    if not voice:
        return PACE
    name = os.path.basename(voice)[:-4]
    if os.path.dirname(voice) == BUNDLED and name in PACES:
        return PACES[name]
    try:
        with open(os.path.splitext(voice)[0] + ".txt", encoding="utf-8") as f:
            n = words(f.read())
        seconds = speech_time(voice)
    except (OSError, UnicodeDecodeError, wave.Error, EOFError):
        return PACE
    if not n or seconds < 1:
        return PACE
    return PACE * (n / seconds * 60 / PACE) ** PULL


def speech_time(path):
    """Seconds from the first sound to the last in a PCM .wav (without
    the silence around it)."""
    import numpy as np

    with wave.open(path) as w:
        width, rate, ch = w.getsampwidth(), w.getframerate(), w.getnchannels()
        x = w.readframes(w.getnframes())
    if width not in (2, 4):
        raise wave.Error("not 16- or 32-bit PCM")
    x = np.frombuffer(x, f"<i{width}").astype(np.float64)[::ch]
    n = rate // 50  # 20 ms
    e = np.sqrt(np.mean(x[:len(x) // n * n].reshape(-1, n) ** 2, axis=1))
    on = np.nonzero(e > e.max() / 100)[0] if len(e) else []
    return (on[-1] - on[0] + 1) * n / rate if len(on) else 0.0


def factor(voice, rate, speed):
    """The speed factor for stretch.py: rate (words per minute; None: the
    voice's own pace), within RATES of the voice's pace, times speed;
    within SPEEDS."""
    f = min(max(rate / pace(voice), RATES[0]), RATES[1]) if rate else 1.0
    return min(max(f * speed, SPEEDS[0]), SPEEDS[1])


def listing():
    """--voices: one line per name, marking yours and the defaults."""
    mine = names_in(MINE)
    for name in voice_names():
        langs = [lang or "unknown" for lang in (*DEFAULT_VOICES, None)
                 if default_voice(lang) == name]
        yield (name + (" (yours)" if name in mine else "")
               + (f" (default for {', '.join(langs)})" if langs else ""))
