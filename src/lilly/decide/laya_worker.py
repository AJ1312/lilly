"""The Laya worker. It runs inside the add-on's own environment, as its own process, never inside Lilly.

Lilly writes one JSON question per line to its input and reads one JSON answer per line from its output. The worker
has no network (offline mode is set before anything is imported), reads only the model folder it is given, and
answers only with a choice and a confidence: it cannot be told to do anything else.

    python laya_worker.py <model folder> <sha256 of the weights>
"""
from __future__ import annotations

import importlib
import json
import math
import os
import sys
from typing import Any

MAX_LINE = 100_000
QUESTION = "q"


def ask(agent: Any, req: dict[str, Any]) -> dict[str, Any]:
    """Run one question. Returns {"id", "choice", "confidence"}; choice is "true" or "false" for a yes/no question."""
    kind, criteria = req["type"], req.get("criteria")
    question: dict[str, Any] = {"type": kind, "instructions": req["instructions"]}
    if criteria:
        question["criteria"] = criteria
    answer = agent.system_one(req["state"], {QUESTION: question})["answers"][QUESTION]
    confidence = float(answer["confidence"])
    if not math.isfinite(confidence):
        raise ValueError("bad confidence")
    if kind == "noul":
        choice = "true" if float(answer["noul"]) >= 0.5 else "false"
    else:
        choice = str(answer["choice"])
    return {"id": req["id"], "choice": choice, "confidence": min(1.0, max(0.0, confidence))}


def serve(agent: Any, lines: Any, out: Any) -> None:
    for line in lines:
        if len(line) > MAX_LINE:
            out.write(json.dumps({"id": None, "error": "too long"}) + "\n")
        else:
            req: Any = None
            try:
                req = json.loads(line)
                reply = ask(agent, req)
            except Exception:   # a bad question must not stop the worker; the caller only needs to know it failed
                reply = {"id": req.get("id") if isinstance(req, dict) else None, "error": "failed"}
            out.write(json.dumps(reply) + "\n")
        out.flush()


def main(argv: list[str]) -> int:
    model, digest = argv[1], argv[2]
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[name] = "1"
    laya = importlib.import_module("laya")
    agent = laya.load(model, device="cpu", expected_sha256={"model.safetensors": digest})
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    serve(agent, sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
