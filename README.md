# Better Assistant voice model

Files downloaded by Better Assistant when **voice match** is turned on. Not an integration release.

- `titanet.npz` / `titanet.json`: the TitaNet-S speaker model by NVIDIA (NeMo Toolkit, Apache 2.0
  licence), converted from ONNX to plain numpy weights (float16) and a step list, so it runs inside
  Home Assistant without onnxruntime. Checked against onnxruntime: identical embeddings (cosine >= 0.99999).
- Better Assistant verifies both files against SHA-256 checksums before using them.
