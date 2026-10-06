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
        state_lower = state.lower()
        pick = next((k for k in keys if q["criteria"][k].lower() in state_lower), None)
        if pick is None:
            state_words = {w.strip(",.!?\"'()") for w in state_lower.split() if len(w) > 2}
            def word_score(k: str) -> int:
                crit_words = {w.strip(",.!?\"'()") for w in q["criteria"][k].lower().split() if len(w) > 2}
                return len(crit_words & state_words)
            scored = sorted(keys, key=word_score, reverse=True)
            pick = scored[0] if scored and word_score(scored[0]) > 0 else keys[0]
        return {"answers": {"q": {"choice": pick, "confidence": 0.88}}}


def load(path, device=None, expected_sha256=None, **kw):
    if os.environ.get("HF_HUB_OFFLINE") != "1" or not expected_sha256 or device != "cpu":
        raise RuntimeError("worker must load offline, on cpu, with a digest")
    return Agent()
