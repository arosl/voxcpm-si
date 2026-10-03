"""The command line: the voice main() picks, --voices, --hold's PID, and
--instruct's transcript."""

import argparse
import os

import pytest

from si import cli, client
from si import voices as V


def run_main(monkeypatch, *argv, env=None):
    """The voice main() would speak with (None: zero-shot or --instruct)."""
    monkeypatch.delenv("SI_VOICE", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    got = {}
    monkeypatch.setattr(client, "speak",
                        lambda text, voice, *a: got.update(voice=voice))
    monkeypatch.setattr("sys.argv", ["si", *argv])
    cli.main()
    return got.get("voice")


def test_main_picks_by_language(voices, defaults):
    (voices / "john.wav").write_bytes(b"")
    anna, john, ola = (str(voices / n) for n in ("anna.wav", "john.wav",
                                                 "ola.wav"))
    assert run_main(defaults, "Thanks for the reply.") == john
    assert run_main(defaults, "Takk for svaret.") == anna
    assert run_main(defaults, "Ingrid Haugen, 48213") == anna
    # -v and SI_VOICE win for all text
    assert run_main(defaults, "-v", "ola", "Thanks for the reply.") == ola
    assert run_main(defaults, "Thanks for the reply.",
                    env={"SI_VOICE": "ola"}) == ola
    assert run_main(defaults, "--instruct", "calm", "Thanks.") is None


def test_list_voices(voices, defaults, capsys):
    run_main(defaults, "--voices")
    assert capsys.readouterr().out == (
        "anna (default for no, unknown)\nola\n")
    (voices / "john.wav").write_bytes(b"")
    run_main(defaults, "--voices")
    assert capsys.readouterr().out == (
        "anna (default for no, unknown)\njohn (default for en)\nola\n")
    defaults.setattr(V, "DEFAULT_VOICES", {"no": "anna", "en": ""})
    run_main(defaults, "--voices")
    assert capsys.readouterr().out.startswith(
        "anna (default for no, en, unknown)\n")


@pytest.mark.parametrize("arg", ["0", "-1", "abc", str(2**31)])
def test_hold_pid_must_be_a_process_id(arg):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.pid(arg)


def test_hold_pid():
    assert cli.pid("1234") == 1234


def test_instruct_writes_what_it_said(fake):
    """--instruct -o writes the .txt next to the .wav: the text as the
    server spoke it (its "done" reply says)."""
    text = "**Hei**, se https://github.com/a/b.\n\nDet\nkoster 40 kr."
    out = os.path.join(fake.cache, "anna.wav")
    code, err = fake.done(fake.run("--instruct", "calm", "-o", out, text))
    assert code == 0, err
    with open(os.path.join(fake.cache, "anna.txt")) as f:
        assert f.read() == "Hei, se github.com. Det koster førti kroner.\n"


def test_null_output(monkeypatch):
    """With SI_FAKE the Player plays to a null output (conftest
    makes the real one fail the test), at the pace of the audio."""
    import numpy as np

    monkeypatch.setattr(client, "output", client.null)
    t = client.time.time()
    p = client.Player(8000, 0.1, t)
    p.add(np.zeros(2000, dtype="float32"))
    p.finish()
    assert p.first is not None and 0.2 < client.time.time() - t < 2


def test_sound_fails_the_test(monkeypatch):
    """conftest's guard: a Player with the real output fails the test
    (rather than become a Fail, which a test could expect)."""
    pytest.importorskip("sounddevice")
    monkeypatch.setattr(client, "output", client.device)
    with pytest.raises(pytest.fail.Exception, match="real audio output"):
        client.Player(8000, 0.1, client.time.time())


def test_plays_without_sound(fake):
    """Speech without -o through the CLI: played (to the null output), exit 0."""
    fake.warm()
    assert fake.done(fake.run("Hei.")) == (0, "")


@pytest.mark.parametrize("arg", ["0", "-200", "abc", "1.2", "19"])
def test_rate_must_be_words_per_minute(arg):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.wpm(arg)


def test_rate():
    assert cli.wpm("200") == 200


def test_bad_speed_fails(voices, defaults):
    with pytest.raises(SystemExit, match="speed must be between"):
        run_main(defaults, "--speed", "5", "Hei.")
