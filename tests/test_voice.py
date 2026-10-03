"""Voices: names (yours, then bundled), the default per language, and the
generate() arguments for one."""

import pytest

from si import voices as V
from si.errors import Fail
from si.lang import language


def test_my_voices(voices, defaults):
    mine = voices / "mine"
    mine.mkdir()
    (mine / "kari.wav").write_bytes(b"")
    (mine / "ola.wav").write_bytes(b"")  # yours win over bundled ones
    assert V.voice_names() == ["anna", "kari", "ola"]
    assert V.resolve_voice("kari") == str(mine / "kari.wav")
    assert V.resolve_voice("ola") == str(mine / "ola.wav")
    assert V.resolve_voice("anna") == str(voices / "anna.wav")
    assert list(V.listing()) == ["anna (default for no, unknown)",
                                 "kari (yours)", "ola (yours)"]


def test_voice_names(voices, monkeypatch):
    assert V.voice_names() == ["anna", "ola"]
    monkeypatch.setattr(V, "BUNDLED", str(voices / "none"))
    assert V.voice_names() == []


def test_resolve_name_and_path(voices, tmp_path):
    assert V.resolve_voice("anna") == str(voices / "anna.wav")
    assert V.resolve_voice(str(voices / "ola.wav")) == str(voices / "ola.wav")
    assert V.resolve_voice("") is None
    with pytest.raises(Fail, match="no such voice: nope"):
        V.resolve_voice("nope")


def test_voice_args(voices):
    anna, ola = str(voices / "anna.wav"), str(voices / "ola.wav")
    assert V.voice_args(None) == {}
    assert V.voice_args(ola) == {"ref_audio": ola}
    assert V.voice_args(anna) == {"ref_audio": anna, "prompt_audio": anna,
                                    "prompt_text": "Hei, dette er Anna."}
    assert V.voice_args(anna, "a calm voice") == {"instruct": "a calm voice"}
    # The Norwegian transcript is a prompt for Norwegian (or unknown) text
    # only: it would give English a Norwegian accent.
    assert "prompt_text" in V.voice_args(anna, text="Takk for svaret.")
    assert "prompt_text" in V.voice_args(anna, text="OK.")
    assert V.voice_args(anna, text="Thanks for the reply.") == {
        "ref_audio": anna}



def test_default_voice_per_language(defaults):
    assert V.default_voice("no") == "anna"
    assert V.default_voice("en") == "john"
    assert V.default_voice(None) == "anna"  # unknown: the fallback's
    assert V.default_voice(language("Thanks for the reply.")) == "john"
    assert V.default_voice(language("Takk for svaret.")) == "anna"


def test_default_voice_fallback(defaults):
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": ""})
    assert V.default_voice("en") == "anna"
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "", "en": ""})
    assert V.default_voice("en") is None  # zero-shot


def test_default_voice_spanish(defaults):
    # No Spanish voice: the fallback's, a stable voice (never zero-shot).
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": "john",
                                             "es": ""})
    defaults.setattr(V, "FALLBACK", "en")
    assert V.default_voice(language("Gracias por tu mensaje.")) == "john"
    defaults.setenv("SI_VOICE_ES", "/x/es.wav")
    assert V.default_voice("es") == "/x/es.wav"
    defaults.delenv("SI_VOICE_ES")
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": "john",
                                             "es": "maria"})
    assert V.default_voice("es") == "maria"


def test_spanish_text_with_english_transcript(voices):
    (voices / "john.wav").write_bytes(b"")
    (voices / "john.txt").write_text("Hello, this is John.\n")
    john = str(voices / "john.wav")
    # an English prompt would give Spanish an English accent: reference only
    assert V.voice_args(john, text="Hola, gracias por tu mensaje.") == {
        "ref_audio": john}


def test_default_voice_env(defaults):
    defaults.setenv("SI_VOICE_EN", "/x/en.wav")
    assert V.default_voice("en") == "/x/en.wav"
    assert V.default_voice("no") == "anna"
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": ""})
    defaults.delenv("SI_VOICE_EN")
    defaults.setenv("SI_VOICE_NO", "/x/no.wav")
    assert V.default_voice("en") == "/x/no.wav"
    assert V.default_voice(None) == "/x/no.wav"


def test_non_utf8_transcript(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"")
    (tmp_path / "x.txt").write_bytes(b"Hei p\xe5 deg\n")
    with pytest.raises(Fail, match="not UTF-8"):
        V.voice_args(str(tmp_path / "x.wav"), text="Hei.")


def wav(path, seconds, rate=16000, lead=0.5):
    """A 16-bit mono .wav: lead s of silence, a tone, lead s of silence."""
    import wave

    import numpy as np

    t = np.arange(int(seconds * rate)) / rate
    tone = (np.sin(2 * np.pi * 200 * t) * 10000).astype("<i2")
    pad = np.zeros(int(lead * rate), "<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate([pad, tone, pad]).tobytes())


def test_words():
    assert V.words("Hei, det er Kari-Anne's e-post: 48213.") == 6
    assert V.words("  ") == 0


def test_speech_time_skips_silence(tmp_path):
    wav(tmp_path / "a.wav", 3.0)
    assert V.speech_time(str(tmp_path / "a.wav")) == pytest.approx(3.0, abs=0.04)


def test_pace(voices, monkeypatch):
    assert V.pace(None) == V.PACE
    monkeypatch.setattr(V, "PACES", {"anna": 150})
    assert V.pace(str(voices / "anna.wav")) == 150  # bundled: measured
    # another voice: its clip's pace, pulled toward PACE
    wav(voices / "kari.wav", 4.0)
    (voices / "kari.txt").write_text(" ".join(["ord"] * 16))  # 240 wpm
    assert V.pace(str(voices / "kari.wav")) == pytest.approx(
        V.PACE * (240 / V.PACE) ** V.PULL, rel=0.02)
    assert V.pace(str(voices / "ola.wav")) == V.PACE  # no transcript
    (voices / "per.txt").write_text("Hei.")
    (voices / "per.wav").write_bytes(b"not a wav")
    assert V.pace(str(voices / "per.wav")) == V.PACE


def test_factor(monkeypatch):
    monkeypatch.setattr(V, "pace", lambda voice: 200)
    assert V.factor(None, None, 1.0) == 1.0
    assert V.factor(None, None, 1.5) == 1.5
    assert V.factor(None, 300, 1.0) == 1.5
    assert V.factor(None, 300, 2.0) == 3.0  # --speed scales -r
    assert V.factor(None, 1000, 1.0) == V.RATES[1]  # within RATES
    assert V.factor(None, 20, 1.0) == V.RATES[0]
    assert V.factor(None, 1000, 4.0) == V.SPEEDS[1]  # and SPEEDS
