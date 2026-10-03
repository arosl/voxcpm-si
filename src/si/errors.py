"""The errors the client and the server report with."""


class Fail(Exception):
    """A failure: main() prints `si: <msg>` and exits 1; in the
    server, the error reply to one request."""


class NotRunning(Fail):
    """No server, and the caller didn't want one started."""
