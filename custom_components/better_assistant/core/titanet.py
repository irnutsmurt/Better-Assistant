"""The TitaNet speaker model (NVIDIA NeMo, CC BY 4.0) run with numpy only: Home Assistant's container
can't install onnxruntime, but it always has numpy. Log-mel features match sherpa-onnx's settings for
NeMo models; the graph runner covers the ~35 ONNX operators this one model uses. Checked against
onnxruntime: identical embeddings (cosine 0.99999)."""
from __future__ import annotations

import json

import numpy as np

# ------------------------------------------------------------------ features

SR, N_MELS, FRAME, SHIFT, NFFT = 16000, 80, 400, 160, 512
LOW, HIGH = 0.0, SR / 2 - 400.0


def _hz_to_mel(f):                                   # slaney
    f = np.asarray(f, dtype=np.float64)
    mel = f / (200.0 / 3)
    log_t = f >= 1000.0
    return np.where(log_t, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), mel)


def _mel_to_hz(m):
    m = np.asarray(m, dtype=np.float64)
    f = m * (200.0 / 3)
    log_t = m >= 15.0
    return np.where(log_t, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), f)


def _mel_bank():
    fft_freqs = np.linspace(0, SR / 2, NFFT // 2 + 1)
    pts = _mel_to_hz(np.linspace(_hz_to_mel(LOW), _hz_to_mel(HIGH), N_MELS + 2))
    fdiff, ramps = np.diff(pts), pts[:, None] - fft_freqs[None, :]
    lower, upper = -ramps[:-2] / fdiff[:-1, None], ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lower, upper))
    w *= (2.0 / (pts[2:N_MELS + 2] - pts[:N_MELS]))[:, None]          # slaney norm
    return w.astype(np.float32)


MEL = _mel_bank()
WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FRAME) / FRAME)).astype(np.float32)   # hann (symmetric)


def fbank(samples: np.ndarray) -> np.ndarray:
    """float32 samples in [-1, 1] -> (frames, 80) log-mel features, normalised per feature."""
    x = np.asarray(samples, dtype=np.float32)
    n = 1 + (len(x) - FRAME) // SHIFT if len(x) >= FRAME else 0
    if n <= 0:
        return np.zeros((0, N_MELS), np.float32)
    idx = np.arange(FRAME)[None, :] + SHIFT * np.arange(n)[:, None]
    fr = x[idx].astype(np.float32)
    fr = np.concatenate([fr[:, :1] - 0.97 * fr[:, :1], fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)   # preemphasis
    fr *= WINDOW
    spec = np.abs(np.fft.rfft(fr, NFFT, axis=1)) ** 2
    feats = np.log(np.maximum(spec.astype(np.float32) @ MEL.T, np.finfo(np.float32).eps))
    mean = feats.mean(0)
    std = np.sqrt(((feats - mean) ** 2).mean(0))
    return ((feats - mean) / (std + 1e-5)).astype(np.float32)


# ------------------------------------------------------------------ the graph

_CAST = {1: np.float32, 6: np.int32, 7: np.int64, 9: np.bool_, 10: np.float16, 11: np.float64}


def _conv(x, w, b, a):
    """1-D convolution (N, C, T), any groups, stride 1."""
    pads = a.get("pads", [0, 0]); dil = a.get("dilations", [1])[0]; g = a.get("group", 1)
    if a.get("strides", [1])[0] != 1:
        raise NotImplementedError("strided conv")
    x = np.pad(x, ((0, 0), (0, 0), (pads[0], pads[1])))
    n, c, t = x.shape; co, ci, k = w.shape
    tout = t - dil * (k - 1)
    if g == 1:
        cols = np.stack([x[:, :, j * dil:j * dil + tout] for j in range(k)], axis=2)     # N, C, K, T
        y = np.einsum("nckt,ock->not", cols, w, optimize=True)
    elif g == c and ci == 1:                                                               # depthwise
        mult = co // c
        xr = np.repeat(x, mult, axis=1) if mult > 1 else x
        y = sum(xr[:, :, j * dil:j * dil + tout] * w[None, :, 0, j, None] for j in range(k))
    else:
        cg, og = c // g, co // g
        y = np.concatenate([_conv(x[:, i * cg:(i + 1) * cg], w[i * og:(i + 1) * og], None,
                                  {"pads": [0, 0], "dilations": [dil]}) for i in range(g)], axis=1)
    if b is not None:
        y = y + b[None, :, None]
    return y.astype(np.float32)


def _axes(v):
    return tuple(int(i) for i in np.atleast_1d(v))


class Graph:
    """Loads titanet.json (the steps) and titanet.npz (the weights)."""
    def __init__(self, graph_json: str, weights_npz: str):
        g = json.load(open(graph_json))
        self.nodes, self.outputs, self.inputs = g["nodes"], g["outputs"], g["inputs"]
        with np.load(weights_npz) as z:
            self.w = {k: (z[k].astype(np.float32) if z[k].dtype == np.float16 else z[k]) for k in z.files}

    def run(self, feeds: dict) -> dict:
        v = dict(self.w); v.update(feeds); v[""] = None
        for n in self.nodes:
            a, op = n["attrs"], n["op"]
            i = [v.get(x) for x in n["in"]]
            if op == "Constant":
                r = v[a["value"]["tensor"]]
            elif op == "Conv":
                r = _conv(i[0], i[1], i[2] if len(i) > 2 else None, a)
            elif op == "Relu": r = np.maximum(i[0], 0)
            elif op == "Sigmoid": r = 1 / (1 + np.exp(-i[0]))
            elif op == "Tanh": r = np.tanh(i[0])
            elif op == "Abs": r = np.abs(i[0])
            elif op == "Sqrt": r = np.sqrt(i[0])
            elif op == "Not": r = np.logical_not(i[0])
            elif op == "Add": r = i[0] + i[1]
            elif op == "Sub": r = i[0] - i[1]
            elif op == "Mul": r = i[0] * i[1]
            elif op == "Div":
                r = i[0] / i[1] if np.issubdtype(np.asarray(i[0]).dtype, np.floating) else np.floor_divide(i[0], i[1])
            elif op == "Pow": r = np.power(i[0], i[1])
            elif op == "Equal": r = np.equal(i[0], i[1])
            elif op == "Less": r = np.less(i[0], i[1])
            elif op == "Where": r = np.where(i[0], i[1], i[2])
            elif op == "MatMul": r = np.matmul(i[0], i[1])
            elif op == "Transpose": r = np.transpose(i[0], a.get("perm"))
            elif op == "Shape": r = np.array(np.shape(i[0]), dtype=np.int64)
            elif op == "Cast": r = np.asarray(i[0]).astype(_CAST[a["to"]])
            elif op == "Gather": r = np.take(i[0], i[1], axis=a.get("axis", 0))
            elif op == "Unsqueeze":
                r = i[0]
                for ax in sorted(_axes(i[1])):
                    r = np.expand_dims(r, ax if ax >= 0 else ax + r.ndim + 1)
            elif op == "Squeeze": r = np.squeeze(i[0], axis=_axes(i[1]) if len(i) > 1 and i[1] is not None else None)
            elif op == "Concat": r = np.concatenate([np.atleast_1d(x) for x in i], axis=a.get("axis", 0))
            elif op == "Reshape":
                shape = [int(s) for s in i[1]]
                shape = [i[0].shape[k] if s == 0 else s for k, s in enumerate(shape)]
                r = np.reshape(i[0], shape)
            elif op == "ConstantOfShape":
                val = v[a["value"]["tensor"]] if "value" in a else np.zeros(1, np.float32)
                r = np.full(tuple(int(s) for s in i[0]), val.reshape(-1)[0], dtype=val.dtype)
            elif op == "Expand": r = np.broadcast_to(i[0], np.broadcast_shapes(i[0].shape, tuple(int(s) for s in i[1]))).copy()
            elif op == "Tile": r = np.tile(i[0], tuple(int(s) for s in i[1]))
            elif op == "Range": r = np.arange(i[0], i[1], i[2]).astype(np.asarray(i[0]).dtype)
            elif op == "Slice":
                starts, ends = _axes(i[1]), _axes(i[2])
                axes = _axes(i[3]) if len(i) > 3 and i[3] is not None else tuple(range(len(starts)))
                steps = _axes(i[4]) if len(i) > 4 and i[4] is not None else (1,) * len(starts)
                sl = [slice(None)] * i[0].ndim
                for s, e, ax, st in zip(starts, ends, axes, steps):
                    sl[ax] = slice(s, max(min(e, 2**62), -2**62), st)
                r = i[0][tuple(sl)]
            elif op == "ReduceSum":
                axes = _axes(i[1]) if len(i) > 1 and i[1] is not None else None
                r = np.sum(i[0], axis=axes, keepdims=bool(a.get("keepdims", 1)))
            elif op == "Clip":
                r = np.clip(i[0], i[1] if len(i) > 1 else None, i[2] if len(i) > 2 else None)
            elif op == "Softmax":
                e = np.exp(i[0] - i[0].max(axis=a.get("axis", -1), keepdims=True)); r = e / e.sum(axis=a.get("axis", -1), keepdims=True)
            elif op == "BatchNormalization":
                x, sc, bi, mu, var = i[:5]
                sh = (1, -1) + (1,) * (x.ndim - 2)
                r = (x - mu.reshape(sh)) / np.sqrt(var.reshape(sh) + a.get("epsilon", 1e-5)) * sc.reshape(sh) + bi.reshape(sh)
            else:
                raise NotImplementedError(op)
            if isinstance(r, np.ndarray) and r.dtype == np.float64:
                r = r.astype(np.float32)
            v[n["out"][0]] = r
        return {o: v[o] for o in self.outputs}


class Embedder:
    def __init__(self, graph_json: str, weights_npz: str):
        self.graph = Graph(graph_json, weights_npz)

    def __call__(self, samples: np.ndarray) -> np.ndarray:
        """float32 samples (16 kHz, mono, -1..1) -> 192-dim voice embedding."""
        f = fbank(samples).T[None]
        if f.shape[2] < 20:
            raise ValueError("too short")
        return self.graph.run({"audio_signal": f, "length": np.array([f.shape[2]], np.int64)})["embs"][0]
