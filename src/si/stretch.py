"""Change the speed of speech, keeping its pitch (WSOLA, numpy only).

Output frames of FRAME samples (Hann windows, half overlapping) are taken
from the input every HOP * rate samples, each moved by up to TOL samples to
where it best continues the frame before, and added up. Streaming: feed
pieces to `Stretch.add`, then call `flush` for the rest.
"""

import numpy as np

FRAME = 1920  # 40 ms at 48 kHz
HOP = FRAME // 2
TOL = 480     # 10 ms each way


class Stretch:
    def __init__(self, rate):
        self.rate = rate
        self.buf = np.zeros(HOP + TOL, np.float32)  # input, from self.base
        self.base = -HOP - TOL  # input position of buf[0]
        self.acc = np.zeros(FRAME, np.float32)  # output being added up
        self.k = 0     # next output frame
        self.prev = None  # input position of the last frame taken
        self.n_in = 0
        self.n_out = 0
        self.win = np.hanning(FRAME + 1)[:FRAME].astype(np.float32)

    def add(self, x, end=False):
        """Stretch the next piece of input; returns the output ready so far."""
        if self.rate == 1:
            return x
        self.n_in += len(x)
        self.buf = np.concatenate([self.buf, x.astype(np.float32)])
        out = []
        while True:
            pos = round(self.k * HOP * self.rate) - HOP  # nominal start
            if end and self.n_out + HOP * len(out) >= round(
                    self.n_in / self.rate):
                break
            need = max(pos + TOL, -HOP if self.prev is None
                       else self.prev + HOP) + FRAME
            if need > self.base + len(self.buf):
                if not end:
                    break
                self.buf = np.concatenate([self.buf, np.zeros(
                    need - self.base - len(self.buf), np.float32)])
            at = pos if self.prev is None else self.align(pos)
            i = at - self.base
            self.acc += self.win * self.buf[i:i + FRAME]
            if self.k:  # the first half-frame is padding
                out.append(self.acc[:HOP].copy())
            self.acc = np.concatenate([self.acc[HOP:],
                                       np.zeros(HOP, np.float32)])
            self.prev, self.k = at, self.k + 1
            nxt = round(self.k * HOP * self.rate) - HOP
            drop = min(at + HOP, nxt - TOL) - self.base  # not needed again
            if drop > 0:
                self.buf, self.base = self.buf[drop:], self.base + drop
        y = np.concatenate(out) if out else np.zeros(0, np.float32)
        if end:
            y = y[:max(0, round(self.n_in / self.rate) - self.n_out)]
        self.n_out += len(y)
        return y

    def flush(self):
        return self.add(np.zeros(0, np.float32), end=True)

    def align(self, pos):
        """The start near pos that best continues the last frame."""
        nat = self.prev + HOP - self.base  # its natural continuation
        ref = self.buf[nat:nat + FRAME]
        lo = pos - TOL - self.base
        seg = self.buf[lo:lo + FRAME + 2 * TOL]
        c = np.correlate(seg[::4], ref[::4], "valid")  # coarse, then fine
        best = 4 * int(np.argmax(c))
        a, b = max(0, best - 3), min(2 * TOL, best + 3)
        fine = [np.dot(seg[j:j + FRAME], ref) for j in range(a, b + 1)]
        return pos - TOL + a + int(np.argmax(fine))
