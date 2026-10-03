import numpy as np
import pytest

from si.stretch import Stretch


def run(x, rate, piece=7000):
    s = Stretch(rate)
    parts = [s.add(x[i:i + piece]) for i in range(0, len(x), piece)]
    return np.concatenate(parts + [s.flush()])


@pytest.mark.parametrize("rate", [0.5, 0.8, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0])
@pytest.mark.parametrize("n", [12345, 48000])
def test_length_is_input_over_rate(rate, n):
    x = np.sin(np.arange(n) * 0.02).astype(np.float32)
    assert len(run(x, rate)) == round(n / rate)


def test_streaming_matches_all_at_once():
    x = np.sin(np.arange(48000) * 0.02).astype(np.float32)
    assert np.array_equal(run(x, 1.3), run(x, 1.3, piece=len(x)))


def test_rate_one_is_identity():
    x = np.arange(10, dtype=np.float32)
    assert run(x, 1) is not None and np.array_equal(run(x, 1), x)
