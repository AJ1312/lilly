"""A stand-in for the real `laya` package, so the real worker and decider can be run end to end without a model.

Behaviour is driven by the text of the question: 'ignore' or a line repeated three times reads as a yes, 'SLOW' hangs, 'CRASH' kills the worker."""
import os
import time

LOADED: dict[str, object] = {}


class Agent:
    def system_one(self, state, questions):
        if "SLOW" in state:
            time.sleep(30)
        if "CRASH" in state:
            os._exit(3)
        q = questions["q"]
        if q["type"] == "noul":
            lines = state.splitlines()
            yes = "ignore" in state.lower() or any(lines.count(line) >= 3 for line in lines)   # or a step repeated
            return {"answers": {"q": {"noul": 0.92 if yes else 0.08, "confidence": 0.9}}}
        keys = list(q["criteria"])
        pick = next((k for k in keys if q["criteria"][k].lower() in state.lower()), keys[0])
        return {"answers": {"q": {"choice": pick, "confidence": 0.88}}}


def load(path, device=None, expected_sha256=None, **kw):
    if os.environ.get("HF_HUB_OFFLINE") != "1" or not expected_sha256 or device != "cpu":
        raise RuntimeError("worker must load offline, on cpu, with a digest")
    return Agent()
