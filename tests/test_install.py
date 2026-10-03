"""Install and first run: the pinned model revision, what the user sees while
the model downloads, and a failed download."""

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from conftest import wait_for

from si import config, protocol, server
from si.errors import Fail

ENV = {k: v for k, v in os.environ.items()
       if not k.startswith(("SI_", "HF_"))}


def python(code, **env):
    """Run code in a fresh interpreter (config and huggingface_hub read the
    environment at import); its stdout."""
    return subprocess.run([sys.executable, "-c", code], env={**ENV, **env},
                          capture_output=True, text=True, check=True).stdout


def test_revision():
    pin, default = config.PIN, config.DEFAULT_MODEL
    assert config.revision(default) == pin
    assert config.revision(default, "main") == "main"
    assert config.revision("someone/OtherModel") is None
    assert config.revision("someone/OtherModel", "v2") == "v2"
    show = "from si import config; print(config.MODEL, config.REVISION)"
    assert python(show).split() == [default, pin]
    assert python(show, SI_MODEL="").split() == [default, pin]
    assert python(show, SI_REVISION="main").split() == [default, "main"]
    assert python(show, SI_MODEL="a/b").split() == ["a/b", "None"]
    assert python(show, SI_MODEL="a/b",
                  SI_REVISION="v2").split() == ["a/b", "v2"]


FETCH = """
from types import SimpleNamespace
from si import server
from si.errors import Fail
s = SimpleNamespace(phase="loading")
try:
    server.fetch(s)
except Fail as e:
    print(s.phase, e)
"""


@pytest.mark.parametrize("env, why", [
    ({"HF_HUB_OFFLINE": "1"}, "HF_HUB_OFFLINE is set"),
    ({"HF_ENDPOINT": "http://127.0.0.1:9"},
     "no network, or Hugging Face can't be reached")])
def test_download_fails_at_once(tmp_path, env, why):
    """Not cached, and no network: a short reason, at once."""
    t = time.time()
    out = python(FETCH, HF_HOME=str(tmp_path), **env).splitlines()[-1]
    assert out == ("downloading couldn't download the model "
                   f"mlx-community/VoxCPM2-8bit ({why})")
    assert time.time() - t < 15


TOK = ["tokenizer.json", "tokenizer_config.json"]


@pytest.mark.parametrize("files, cached", [
    (["config.json", "model.safetensors", *TOK], True),
    (["config.json", *TOK], False),  # the weights not yet in
    (["config.json", "model.safetensors->gone", *TOK], False),  # a dangling link
    (["config.json", "model.safetensors.index.json", "a.safetensors", *TOK],
     False),
    (["config.json", "model.safetensors.index.json", "a.safetensors",
      "b.safetensors", *TOK], True),
    (["config.json", "model.safetensors"], False),  # no tokenizer
    (["config.json", "model.safetensors", "tokenizer.json"], False),
    (["model.safetensors", *TOK], False)])  # no config
def test_cached_without_a_tree_file(tmp_path, monkeypatch, files, cached):
    """A pinned snapshot in a cache without trees/<commit>.json (filled by
    another tool or an older huggingface_hub): if complete, it's used as it
    is, offline (mlx-audio's get_model_path would go online for that file);
    if not, it's downloaded ("downloading")."""
    import huggingface_hub.constants
    import mlx_audio.utils
    from huggingface_hub.errors import OfflineModeIsEnabled

    snap = tmp_path / "models--mlx-community--VoxCPM2-8bit" / "snapshots" / config.PIN
    snap.mkdir(parents=True)
    for name in files:
        if "->" in name:
            name, to = name.split("->")
            (snap / name).symlink_to(tmp_path / to)
        else:
            (snap / name).write_text(json.dumps({"weight_map": {
                "x": "a.safetensors", "y": "b.safetensors"}}))
    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(server.config, "MODEL", config.DEFAULT_MODEL)
    monkeypatch.setattr(server.config, "REVISION", config.PIN)
    got = []

    def online(*args, **kw):
        got.append(args)
        raise OfflineModeIsEnabled("test")

    monkeypatch.setattr(mlx_audio.utils, "get_model_path", online)
    s = SimpleNamespace(phase="loading")
    if cached:
        assert server.fetch(s) == str(snap) and not got
    else:
        with pytest.raises(Fail, match="HF_HUB_OFFLINE is set"):
            server.fetch(s)
        assert got and s.phase == "downloading"


# ------------------------------------------------------- fake server processes

def test_fake_keys():
    assert config.fake("") == {"load": 0, "piece": 0.05, "fetch": 0}
    assert config.fake("load=2 fetch=fail") == {"load": 2, "piece": 0.05,
                                                "fetch": "fail"}
    with pytest.raises(ValueError, match="no such key: lod"):
        config.fake("lod=2")


def say(fake, load=""):
    """Speak with a fake server that loads like `load` (SI_FAKE):
    (exit code, stdout, stderr)."""
    p = fake.say("Hei.", extra={"SI_FAKE": load})
    code, err = fake.done(p)
    return code, p.stdout.read(), err


def test_first_run_says_it_downloads(fake):
    log = os.path.join(fake.cache, "server.log")
    assert say(fake, "load=2 fetch=2.5") == (0, "", (
        "… starting VoxCPM2\n"
        "… downloading mlx-community/VoxCPM2-8bit (about 3 GB), only the "
        f"first time; progress: tail -f {log}\n"
        "… downloaded; loading the model\n"))
    assert say(fake) == (0, "", "")  # warm: nothing on stderr


def test_status_while_downloading(fake):
    assert fake.run("--warm", extra={"SI_FAKE": "fetch=5"}).wait(5) == 0

    def status():
        out = fake.run("--status").communicate(timeout=10)[0]
        return out if out.startswith("downloading") else None

    assert wait_for(status, what="--status to say downloading") == (
        "downloading: mlx-community/VoxCPM2-8bit (progress: tail -f "
        f"{os.path.join(fake.cache, 'server.log')})\n")


def test_failed_download(fake):
    t = time.time()
    code, out, err = say(fake, "fetch=fail")
    assert (code, out) == (1, "")
    assert err.endswith(
        "si: couldn't download the model mlx-community/VoxCPM2-8bit "
        "(no network, or Hugging Face can't be reached); see "
        f"{os.path.join(fake.cache, 'server.log')}\n"), err
    assert time.time() - t < 5


def test_phases(fake):
    """The status's phase: downloading, then loading, then ready (after
    "loading" while it starts, until it finds the model isn't cached)."""
    assert fake.run("--warm", extra={"SI_FAKE": "load=1 fetch=1.5"}).wait(5) == 0
    wait_for(lambda: os.path.exists(os.path.join(fake.cache, "sock")))
    seen = []

    def ready():
        phase = fake.raw(protocol.line(protocol.STATUS)).get("phase")
        if not seen or seen[-1] != phase:
            seen.append(phase)
        return phase == "ready"

    wait_for(ready, what="the server to be ready")
    assert seen in (["downloading", "loading", "ready"],
                    ["loading", "downloading", "loading", "ready"]), seen
