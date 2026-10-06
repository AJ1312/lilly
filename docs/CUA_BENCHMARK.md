# CUA Benchmark

`benchmarks/cua_benchmark.py` is the reproducible local baseline for Lilly's
computer contract. It measures an observation, semantic grounding, action,
fresh-frame receipt, and verification in one run. The end-to-end tests cover
stale observations, ambiguous targets, failed verification, and persistence.

The evaluated OSS ideas are deliberately treated as comparison inputs rather
than dependencies: Jev/browser-ultrafast and Browser Harness are browser-first;
UI-TARS and OmniParser add visual grounding/model dependencies; Agent S and
UFO2 add orchestration layers. Lilly already has native macOS AX/screenshot
grounding, persistent browser support, ModelBroker routing, and DevBox
isolation. Until an adapter demonstrates a measurable win on this benchmark
and the real-desktop smoke test, no extra framework is adopted.

Run the baseline with:

```sh
PYTHONPATH=src .venv/bin/python benchmarks/cua_benchmark.py
```
