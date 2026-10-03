"""Settings shared by the client and the server (the environment variables
are documented in README.md)."""

import os

from si.errors import Fail

CACHE = os.path.expanduser(os.environ.get("SI_CACHE",
                                          "~/.cache/si"))
START = 1800  # seconds a starting server may take (the first run downloads)
# The default model, pinned to the revision the bundled voices were made and
# tuned with (stream.py also uses mlx-audio internals): an upstream re-upload
# can't change it.
DEFAULT_MODEL = "mlx-community/VoxCPM2-8bit"
PIN = "d52725898a0675703f7f9ddc5a4d1a3cdbb99032"
MODEL = os.environ.get("SI_MODEL") or DEFAULT_MODEL
IDLE = float(os.environ.get("SI_IDLE", "900"))
TIMEOUT = float(os.environ.get("SI_TIMEOUT", "120"))
STEPS = int(os.environ.get("SI_STEPS", "8"))
DEBUG = bool(os.environ.get("SI_DEBUG"))


def fake(spec):
    """Tests only (SI_FAKE): no model, and the client plays to a
    null output (client.NullStream). "load=S piece=S fetch=S": the
    seconds to load, per piece of silence, and to download first (0: it is
    cached; "fail": the download fails), over the defaults."""
    keys = {"load": 0.0, "piece": 0.05, "fetch": 0.0}
    for k, v in (kv.split("=", 1) for kv in spec.split()):
        if k not in keys:
            raise ValueError(f"SI_FAKE: no such key: {k}")
        keys[k] = v if v == "fail" else float(v)
    return keys


FAKE = (fake(os.environ["SI_FAKE"]) if "SI_FAKE" in os.environ
        else None)


def revision(model, given=None):
    """The model revision to load: the one given, else the pin for the
    default model, else (another model) its latest (None)."""
    return given or (PIN if model == DEFAULT_MODEL else None)


REVISION = revision(MODEL, os.environ.get("SI_REVISION"))


# The files in CACHE, derived on use (tests patch CACHE alone).
def sock_path():
    return os.path.join(CACHE, "sock")


def log_path():
    return os.path.join(CACHE, "server.log")


def lock_path():  # the server holds it (flock) for its life
    return os.path.join(CACHE, "server.lock")


def make_cache():
    """The cache directory (socket, log, lock), private to this user."""
    if len(os.fsencode(sock_path())) > 103:  # macOS sun_path limit
        raise Fail("socket path too long, use a shorter SI_CACHE: "
                   + sock_path())
    os.makedirs(CACHE, mode=0o700, exist_ok=True)
    if os.stat(CACHE).st_uid != os.getuid():
        raise Fail(f"{CACHE} belongs to another user")
    os.chmod(CACHE, 0o700)


def lock_fd():
    return os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
