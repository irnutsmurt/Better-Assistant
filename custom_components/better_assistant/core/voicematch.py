"""Voice match: voiceprints from training clips, automatic thresholds, and who-is-speaking decisions.
numpy only, no Home Assistant imports. Embeddings come from the TitaNet speaker model (core/titanet.py).

How a person's voiceprint is made and checked, so nobody has to tune anything:
1. Clean: every clip is compared with the average of the others; clips that don't sound like the rest
   (the TV, someone else, the speaker hearing itself) are dropped.
2. Print: the average of the clips that are left.
3. Threshold: between how the person's own clips score against their print and how a bundled set of
   strangers' voices score against it.
4. Grade: "ready" when the gap between the two is clear, else "weak" (train again somewhere quieter)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_CLIPS = 5                 # fewer clean clips than this: not ready
DROP_BELOW = 0.30             # a training clip scoring under this against the others isn't this person
DROP_MARGIN = 0.30            # ... or this far under the typical clip
THRESHOLD_FLOOR = 0.35        # never accept a match below this
THRESHOLD_CEILING = 0.60
READY_GAP = 0.12              # own clips (10th percentile) must clear strangers (99th) by this much
RUNNER_UP_GAP = 0.05          # two people this close: "not sure"


def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(unit(a) @ unit(b))


def leave_one_out(embs: list[np.ndarray]) -> list[float]:
    """Each clip against the average of the others."""
    if len(embs) < 2:
        return [1.0] * len(embs)
    u = [unit(e) for e in embs]
    total = np.sum(u, axis=0)
    return [cos(e, total - e) for e in u]


def clean(embs: list[np.ndarray]) -> list[int]:
    """Indices of the clips that sound like the rest. Repeats until stable (one bad clip pulls the
    average towards itself, which can hide a second one)."""
    keep = list(range(len(embs)))
    for _ in range(5):
        if len(keep) < 3:
            return keep
        scores = leave_one_out([embs[i] for i in keep])
        typical = float(np.median(scores))
        new = [i for i, s in zip(keep, scores) if s >= DROP_BELOW and s >= typical - DROP_MARGIN]
        if new == keep:
            return keep
        keep = new
    return keep


@dataclass
class Print:
    person: str
    centroid: list[float]
    threshold: float
    grade: str                 # "ready" / "weak" / "too_few"
    clips: list[str]           # clip ids used
    dropped: list[str] = field(default_factory=list)
    own: float = 0.0           # 10th percentile of own clips vs the print
    strangers: float = 0.0     # 99th percentile of strangers vs the print

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def build_print(person: str, clips: dict[str, np.ndarray], strangers: np.ndarray) -> Print:
    """clips: clip id -> embedding (training and confirmed clips). strangers: (n, d) bundled embeddings."""
    ids = list(clips)
    embs = [clips[i] for i in ids]
    keep = clean(embs)
    used, dropped = [ids[i] for i in keep], [ids[i] for i in range(len(ids)) if i not in keep]
    if not used:
        return Print(person, [], 1.0, "too_few", [], dropped)
    centroid = unit(np.mean([unit(embs[i]) for i in keep], axis=0))
    own_scores = leave_one_out([embs[i] for i in keep]) if len(keep) > 1 else [1.0]
    own = float(np.percentile(own_scores, 10))
    strange = float(np.percentile(np.asarray(strangers, np.float32) @ centroid, 99)) if len(strangers) else 0.2
    threshold = min(max((own + strange) / 2, strange + 0.05, THRESHOLD_FLOOR), THRESHOLD_CEILING)
    grade = "too_few" if len(used) < MIN_CLIPS else "ready" if own - strange >= READY_GAP else "weak"
    return Print(person, centroid.tolist(), round(threshold, 3), grade, used, dropped, round(own, 3), round(strange, 3))


@dataclass
class Match:
    person: str | None         # None: not sure / nobody trained
    score: float
    runner_up: str | None = None

    @property
    def confidence(self) -> str:
        return "strong" if self.person and self.score >= 0.5 else "weak" if self.person else "none"


def identify(emb: np.ndarray, prints: list[dict]) -> Match:
    """Who is speaking: the best print that clears its own threshold and isn't too close to another."""
    scored = sorted(((cos(emb, np.asarray(p["centroid"], np.float32)), p) for p in prints
                     if p.get("centroid") and p.get("grade") != "too_few"), key=lambda x: -x[0])
    if not scored:
        return Match(None, 0.0)
    best, p = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if best < p["threshold"]:
        return Match(None, best, p["person"])
    if second and best - second[0] < RUNNER_UP_GAP and second[0] >= second[1]["threshold"]:
        return Match(None, best, second[1]["person"])
    return Match(p["person"], best)


def trim_silence(samples: np.ndarray, rate: int = 16000) -> np.ndarray:
    """Cut leading and trailing quiet (30 ms frames under a tenth of the loud ones' level)."""
    x = np.asarray(samples, dtype=np.float32)
    hop = int(rate * 0.03)
    if len(x) < hop * 4:
        return x
    frames = x[: len(x) // hop * hop].reshape(-1, hop)
    energy = np.sqrt((frames ** 2).mean(axis=1))
    loud = np.percentile(energy, 90)
    on = np.where(energy >= max(loud * 0.1, 1e-4))[0]
    if not len(on):
        return x
    start, end = max(on[0] - 3, 0) * hop, min(on[-1] + 4, len(frames)) * hop
    return x[start:end]
