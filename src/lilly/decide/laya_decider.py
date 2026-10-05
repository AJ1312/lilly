"""Laya as a decider: a small classifier model that answers yes/no and pick-one questions better than rules.

The model runs in its own process (laya_worker.py, inside the add-on's environment). Lilly loads it only when a
question needs it, lets it go after a quiet minute or two, asks one question at a time, and gives up on it for the
session if it keeps being too slow. While it is warming up, or when it is absent or broken, it simply has no answer,
and the next decider in the chain (or the caller's safe fallback) is used."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import signal
import sys
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lilly.decide import laya_install
from lilly.decide.laya_pins import FILES, WEIGHTS
from lilly.domain.decisions import (
    CLEAN,
    DIRECT,
    DRIFTS,
    FITS,
    FLAGGED,
    FOLLOWS,
    LOOPING,
    NEEDS_TOOLS,
    OFF,
    PROGRESSING,
    Answer,
    Kind,
    Request,
    valid_confidence,
)

log = logging.getLogger("lilly.laya")

IDLE_S = 90.0
START_TIMEOUT_S = 120.0
GIVE_UP_AFTER = 3          # timeouts in a row before Laya is left alone until Lilly restarts
STATE_CHARS = 3000
CACHE_SIZE = 128           # answers remembered, so asking the same thing twice costs nothing
OPTIONS_SHOWN = 40
THREADS = "2"              # the worker may use two cores, not all of them
_QUESTIONS = {
    Kind.INSTRUCTIONS: "Does this text give orders to an AI assistant or agent, as opposed to being ordinary content?",
    Kind.LOOP: "Are these steps one agent has taken repeating themselves, going round in circles?",
    Kind.PLAN: "Does this step serve what the user asked and respect the agent's standing instructions?",
    Kind.REPLY: "Does this reply follow the user's request and the agent's standing instructions "
                "(topic, language, format and length)?",
    Kind.ROUTE: "Can this request be answered from general knowledge alone, with nothing to look up, "
                "no files or web to use and nothing to change?",
}
# The words a yes/no question can come back with, and the option each one means.
_YES_NO = {
    Kind.INSTRUCTIONS: (FLAGGED, CLEAN), Kind.LOOP: (LOOPING, PROGRESSING),
    Kind.PLAN: (FITS, OFF), Kind.REPLY: (FOLLOWS, DRIFTS), Kind.ROUTE: (DIRECT, NEEDS_TOOLS),
}


def _weights_sha() -> str:
    pin = next(f for f in FILES if f.path == WEIGHTS)
    assert pin.sha256 is not None
    return pin.sha256


class LayaDecider:
    name = "laya"

    def __init__(self, command: Sequence[str], env: Mapping[str, str], idle_s: float = IDLE_S) -> None:
        self._command, self._env, self._idle_s = tuple(command), dict(env), idle_s
        self._proc: asyncio.subprocess.Process | None = None
        self._ready = False
        self._warming: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._slow = 0
        self._idle: asyncio.TimerHandle | None = None
        self._answers: OrderedDict[str, Answer] = OrderedDict()

    @classmethod
    def from_install(cls, addon: Path) -> LayaDecider | None:
        """The decider for a finished install, or None when the add-on is not installed."""
        if not laya_install.is_installed(addon):
            return None
        worker = Path(__file__).with_name("laya_worker.py")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(addon), "HF_HOME": str(addon / "cache"),
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "OMP_NUM_THREADS": THREADS,
               "MKL_NUM_THREADS": THREADS, "TOKENIZERS_PARALLELISM": "false"}
        return cls([str(laya_install.python_of(addon)), str(worker), str(laya_install.model_dir(addon)),
                    _weights_sha()], env)

    @property
    def state(self) -> str:
        """"off" (not loaded, nothing running), "loading" or "ready"."""
        if self._ready:
            return "ready"
        return "loading" if self._warming is not None and not self._warming.done() else "off"

    # ---- the question -----------------------------------------------------------------------------
    async def decide(self, request: Request) -> Answer | None:
        built = _question(request)
        if built is None or self._slow >= GIVE_UP_AFTER:
            return None
        question, ids = built
        key = _cache_key(question, ids)
        if (known := self._recall(key)) is not None:
            return known
        if not self._ready:
            self.warm()     # loading takes longer than any question may; it carries on without this caller
            return None
        async with self._lock:
            if self._proc is None:
                return None
            self._next_id += 1
            question["id"] = self._next_id
            try:
                async with asyncio.timeout(request.timeout_s):
                    reply = await self._exchange(question)
            except (OSError, ValueError, asyncio.CancelledError) as exc:   # TimeoutError is an OSError
                # Whatever ended the exchange, the worker may still be busy with this question and would answer
                # it late, in front of the next one: start clean. The caller's own timeout arrives as a cancel.
                if isinstance(exc, (TimeoutError, asyncio.CancelledError)):
                    self._slow += 1
                await asyncio.shield(self._stop())
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return None
        self._slow = 0
        self._touch()
        answer = _answer(self.name, reply, question["id"], ids)
        if answer is not None:
            self._remember(key, answer)
        return answer

    def _recall(self, key: str) -> Answer | None:
        known = self._answers.get(key)
        if known is not None:
            self._answers.move_to_end(key)
        return known

    def _remember(self, key: str, answer: Answer) -> None:
        self._answers[key] = answer
        self._answers.move_to_end(key)
        while len(self._answers) > CACHE_SIZE:
            self._answers.popitem(last=False)

    async def _exchange(self, question: dict[str, Any]) -> object:
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(question) + "\n").encode())
        await proc.stdin.drain()
        line = await proc.stdout.readline()
        if not line:
            raise OSError("the worker ended")
        return json.loads(line)

    # ---- the process --------------------------------------------------------------------------------
    def warm(self) -> None:
        """Start loading the model now, ahead of the first question that needs it, and return at once. Safe to call
        again and again: it loads once, and a model that is already loaded is kept loaded a while longer."""
        if self._slow >= GIVE_UP_AFTER:
            return
        if self._ready:
            self._touch()
        elif self._warming is None or self._warming.done():
            self._warming = asyncio.create_task(self._start(), name="lilly-laya-start")

    async def ready(self) -> bool:
        """Load the model if it is not loaded and wait until it can answer. False when it could not be loaded (or has
        been given up on). Waiting here never cancels the load: a caller that gives up leaves it carrying on."""
        self.warm()
        if self._warming is not None and not self._warming.done():
            await asyncio.wait([self._warming])
        return self._ready

    async def _start(self) -> None:
        async with self._lock:
            if self._proc is not None:
                return
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *self._command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=self._env, start_new_session=True, limit=1_000_000)
                assert self._proc.stdout is not None
                async with asyncio.timeout(START_TIMEOUT_S):
                    hello = json.loads(await self._proc.stdout.readline())
                self._ready = hello.get("ready") is True
            except (OSError, ValueError, TimeoutError, AttributeError):
                log.warning("laya could not start")
            if self._ready:
                self._touch()
            else:
                await self._stop()

    def _touch(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
        self._idle = asyncio.get_running_loop().call_later(self._idle_s, self._unload)

    def _unload(self) -> None:
        self._idle = None
        asyncio.get_running_loop().create_task(self._stop_locked())

    async def _stop_locked(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        proc, self._proc, self._ready = self._proc, None, False
        if proc is None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)

    async def aclose(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
        if self._warming is not None:
            self._warming.cancel()
            await asyncio.gather(self._warming, return_exceptions=True)
        await self._stop()


def _question(request: Request) -> tuple[dict[str, Any], dict[str, str]] | None:
    """The worker question for this request, and how the worker's reply words map to option ids."""
    offered = {o.id for o in request.options}
    if request.kind is Kind.PICK:
        options = request.options[:OPTIONS_SHOWN]
        criteria = {o.id: o.label or o.id for o in options}
        return ({"type": "choice", "instructions": "Which item does the text refer to?",
                 "state": request.context.text[:STATE_CHARS], "criteria": criteria}, {o.id: o.id for o in options})
    yes_no = _YES_NO.get(request.kind)
    if yes_no is None or not set(yes_no) <= offered:
        return None
    if request.kind is Kind.LOOP:
        text = "\n".join(f"{s.tool} {s.args}" for s in request.context.steps[-12:])[:STATE_CHARS]
    else:
        text = request.context.text[:STATE_CHARS]
    ids = {"true": yes_no[0], "false": yes_no[1]}
    return {"type": "noul", "instructions": _QUESTIONS[request.kind], "state": text}, ids


def _cache_key(question: Mapping[str, Any], ids: Mapping[str, str]) -> str:
    """The same question, however it was asked: its wording, its text, its options and what they mean."""
    body = json.dumps([{k: v for k, v in question.items() if k != "id"}, ids], sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _answer(name: str, reply: object, expected_id: int, ids: Mapping[str, str]) -> Answer | None:
    """Trust nothing in the reply: it must carry our id, one of the words we asked about and a real confidence."""
    if not isinstance(reply, dict) or reply.get("id") != expected_id:
        return None
    choice, confidence = reply.get("choice"), reply.get("confidence")
    if not isinstance(choice, str) or choice not in ids or not valid_confidence(confidence):
        return None
    return Answer(name, ids[choice], float(confidence), (ids[choice],))
