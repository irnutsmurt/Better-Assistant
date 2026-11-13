"""Voice match logic (core/voicematch.py) and the numpy model runner (core/titanet.py)."""
import numpy as np

from core import voicematch as vm
from core.titanet import _conv, fbank

rng = np.random.default_rng(7)
D = 192


def voice(center, n, spread=0.6):
    """n embeddings around one speaker's direction."""
    return [vm.unit(center + rng.normal(0, spread / np.sqrt(D), D)) for _ in range(n)]


ROB, LEILA = vm.unit(rng.normal(size=D)), vm.unit(rng.normal(size=D))
STRANGERS = np.array([vm.unit(rng.normal(size=D)) for _ in range(160)], np.float32)


def test_clean_drops_clips_that_are_someone_else():
    clips = voice(ROB, 10) + [vm.unit(rng.normal(size=D)), vm.unit(rng.normal(size=D))]   # the TV, the speaker
    keep = vm.clean(clips)
    assert sorted(keep) == list(range(10))


def test_print_threshold_and_grade():
    p = vm.build_print("person.rob", {f"c{i}": e for i, e in enumerate(voice(ROB, 12))}, STRANGERS)
    assert p.grade == "ready" and len(p.clips) == 12 and not p.dropped
    assert vm.THRESHOLD_FLOOR <= p.threshold <= vm.THRESHOLD_CEILING
    assert p.strangers < p.threshold < p.own
    few = vm.build_print("person.rob", {"a": voice(ROB, 1)[0], "b": voice(ROB, 1)[0]}, STRANGERS)
    assert few.grade == "too_few"
    noisy = vm.build_print("person.rob", {f"c{i}": e for i, e in enumerate(voice(ROB, 12, spread=6.0))}, STRANGERS)
    assert noisy.grade in ("weak", "too_few")


def test_identify_picks_the_speaker_or_says_not_sure():
    prints = [vm.build_print("person.rob", {f"r{i}": e for i, e in enumerate(voice(ROB, 10))}, STRANGERS).as_dict(),
              vm.build_print("person.leila", {f"l{i}": e for i, e in enumerate(voice(LEILA, 10))}, STRANGERS).as_dict()]
    assert vm.identify(voice(ROB, 1)[0], prints).person == "person.rob"
    assert vm.identify(voice(LEILA, 1)[0], prints).person == "person.leila"
    stranger = vm.identify(vm.unit(rng.normal(size=D)), prints)
    assert stranger.person is None and stranger.confidence == "none"
    halfway = vm.unit(ROB + LEILA)                       # sounds like both: not sure, never a guess
    assert vm.identify(halfway, prints).person is None
    assert vm.identify(voice(ROB, 1)[0], []).person is None


def test_trim_silence_keeps_the_speech():
    quiet, loud = np.zeros(16000, np.float32), (0.3 * np.sin(np.arange(16000) / 5)).astype(np.float32)
    out = vm.trim_silence(np.concatenate([quiet, loud, quiet]))
    assert 16000 <= len(out) < 20000


def test_conv_matches_a_plain_loop():
    x = rng.normal(size=(1, 4, 20)).astype(np.float32)
    w = rng.normal(size=(6, 4, 3)).astype(np.float32)
    b = rng.normal(size=6).astype(np.float32)
    ref = np.zeros((1, 6, 20), np.float32)
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1)))
    for o in range(6):
        for t in range(20):
            ref[0, o, t] = (xp[0, :, t:t + 3] * w[o]).sum() + b[o]
    assert np.allclose(_conv(x, w, b, {"pads": [1, 1]}), ref, atol=1e-4)
    dw = rng.normal(size=(4, 1, 3)).astype(np.float32)                   # depthwise
    ref = np.stack([np.convolve(xp[0, c], dw[c, 0, ::-1], "valid") for c in range(4)])[None]
    assert np.allclose(_conv(x, dw, None, {"pads": [1, 1], "group": 4}), ref, atol=1e-4)


def test_fbank_shape_and_normalised():
    f = fbank((0.1 * rng.normal(size=16000)).astype(np.float32))
    assert f.shape == (98, 80)
    assert np.allclose(f.mean(0), 0, atol=1e-3) and np.allclose(f.std(0), 1, atol=1e-2)
