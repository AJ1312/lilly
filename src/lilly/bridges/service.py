"""The Telegram bridge: polls for messages, pairs the owner, hands allowed messages to Lilly and sends back answers.

Everything from a chat is outside text: each task it starts is untrusted from its first step. Only linked accounts
(by numeric id) are answered, a message is size-capped and rate-limited, and approvals shown here carry the exact
action. Computer control and anything that is not an ordinary step stay in the app."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx

from lilly.app.runtime import Runtime
from lilly.bridges.telegram import Press, TelegramApi, TelegramError, Text, parse_update
from lilly.domain.bridges import Pairing, RateLimiter, clean_inbound
from lilly.domain.errors import ConflictError, LillyError
from lilly.domain.labels import Label
from lilly.domain.ports import Secret
from lilly.domain.settings import Settings
from lilly.engine.orchestrator import SubmitRequest
from lilly.engine.outcome import is_clipped
from lilly.store import agents, bridges, tasks

log = logging.getLogger("lilly.bridge")
PLATFORM = "telegram"
TOKEN_REF = "telegram-bot"  # nosec B105 - the key-store name of the bot token, not the token
POLL_S = 25
BACKOFF_FIRST_S, BACKOFF_MAX_S = 5.0, 120.0
EXACT_CHARS = 900                # how much of an action's arguments one approval card shows
MAX_TRACKED = 64                 # tasks started from chat that are still being followed
TERMINAL = frozenset({"DONE", "FAILED", "CANCELLED", "EXPIRED"})
HELP = ("Send me a request and Lilly will work on it. /stop cancels what is running from this chat. "
        "Anything that needs your approval is shown here with exactly what it will do.")


class BridgeService:
    def __init__(self, rt: Runtime, api_factory: Callable[[Secret], TelegramApi] | None = None,
                 poll_s: int = POLL_S, backoff_s: float = BACKOFF_FIRST_S) -> None:
        self._rt, self._poll_s, self._backoff_first = rt, poll_s, backoff_s
        self._make_api = api_factory or (lambda token: TelegramApi(rt.client, token))
        self._pairing = Pairing(rt.clock)
        self._limit = RateLimiter(rt.clock, rt.settings.bridges.per_minute)
        self._strangers = RateLimiter(rt.clock, 3)        # pairing attempts from accounts that are not linked
        self._poller: asyncio.Task[None] | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._tracked: OrderedDict[str, int] = OrderedDict()   # task id -> the linked user who asked
        self._announced: set[str] = set()                      # approvals already shown in chat
        self._bot: str | None = None
        self._error: str | None = None
        self._api: TelegramApi | None = None

    # ---- lifecycle ------------------------------------------------------------------------------
    async def start(self) -> None:
        self._rt.observe_settings(self._configure)
        await self._configure(self._rt.settings)

    async def _configure(self, settings: Settings) -> None:
        self._limit = RateLimiter(self._rt.clock, settings.bridges.per_minute)
        token = await asyncio.to_thread(self._rt.keys.get, TOKEN_REF)
        if settings.bridges.enabled and token is not None:
            if self._poller is None or self._poller.done():
                self._api = self._make_api(token)
                self._error = None
                self._poller = asyncio.create_task(self._poll(self._api), name="lilly-telegram-poll")
                self._watcher = asyncio.create_task(self._watch(), name="lilly-telegram-watch")
        else:
            await self._halt()

    async def _halt(self) -> None:
        for task in (self._poller, self._watcher):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(t for t in (self._poller, self._watcher) if t is not None), return_exceptions=True)
        self._poller = self._watcher = self._api = None
        self._tracked.clear()
        self._announced.clear()

    async def aclose(self) -> None:
        await self._halt()

    # ---- what the interface asks -----------------------------------------------------------------
    def status(self) -> dict[str, object]:
        settings = self._rt.settings.bridges
        until = self._pairing.active()
        return {"platform": PLATFORM, "enabled": settings.enabled, "running": self._poller is not None and not self._poller.done(),
                "token_set": self._rt.keys.get(TOKEN_REF) is not None, "bot": self._bot, "error": self._error,
                "pairing_until": until,
                "identities": [{"user_id": i.user_id, "label": i.label, "paired_at": i.paired_at}
                               for i in bridges.list_identities(self._rt.db.reader, PLATFORM)]}

    async def new_pairing(self) -> dict[str, object]:
        if self._bot is None and await asyncio.to_thread(self._rt.keys.get, TOKEN_REF) is None:
            raise ConflictError("add the bot token first")
        code = self._pairing.new()
        return {"code": code, "pairing_until": self._pairing.active(), "bot": self._bot}

    async def set_token(self, token: str) -> str:
        """Check the token with Telegram, keep it in the key store, and return the bot's username."""
        secret = Secret(token.strip())
        try:
            bot = await self._make_api(secret).me()
        except TelegramError as exc:
            raise ConflictError(f"that token did not work: {exc}") from None
        if bot != self._bot:                             # another bot counts its updates from its own start
            await self._rt.db.write(lambda con: bridges.reset_last_update(con, PLATFORM))
        self._bot = bot
        await asyncio.to_thread(self._rt.keys.put, TOKEN_REF, secret)
        await self._halt()                               # a new token starts clean on the next configure
        await self._configure(self._rt.settings)
        return self._bot

    async def clear_token(self) -> None:
        await self._halt()
        await asyncio.to_thread(self._rt.keys.delete, TOKEN_REF)
        await self._rt.db.write(lambda con: bridges.reset_last_update(con, PLATFORM))
        self._bot = None
        self._error = None

    async def unpair(self, user_id: int) -> bool:
        removed = await self._rt.db.write(lambda con: bridges.remove_identity(con, PLATFORM, user_id))
        for task_id in [t for t, user in self._tracked.items() if user == user_id]:
            del self._tracked[task_id]                    # nothing in flight reports to a chat that is no longer linked
        return removed

    # ---- polling ----------------------------------------------------------------------------------
    async def _poll(self, api: TelegramApi) -> None:
        delay = self._backoff_first
        if self._bot is None:
            try:
                self._bot = await api.me()
            except TelegramError as exc:
                if exc.fatal:                                 # a revoked token: nothing will work, say so and stop
                    self._error = str(exc)
                    log.warning("telegram bridge stopped: %s", exc)
                    return
        while True:
            try:
                after = bridges.last_update(self._rt.db.reader, PLATFORM)
                batch = await api.updates(after, self._poll_s)
                self._error, delay = None, self._backoff_first
                for raw in batch:
                    await self._take(api, raw)
            except TelegramError as exc:
                self._error = str(exc)
                if exc.fatal:
                    log.warning("telegram bridge stopped: %s", exc)
                    return
                await asyncio.sleep(min(exc.retry_after or delay, BACKOFF_MAX_S))
                delay = min(delay * 2, BACKOFF_MAX_S)
            except httpx.HTTPError:
                self._error = "Telegram could not be reached"
                await asyncio.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
            except Exception:
                log.exception("telegram polling failed")      # a bug must not end the bridge silently
                self._error = "the chat bridge hit an unexpected problem; details are in Lilly's log"
                await asyncio.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)

    async def _take(self, api: TelegramApi, raw: object) -> None:
        parsed = parse_update(raw)
        update_id = raw.get("update_id") if isinstance(raw, dict) else None
        if not isinstance(update_id, int) or isinstance(update_id, bool) or update_id <= 0:
            return
        if update_id <= bridges.last_update(self._rt.db.reader, PLATFORM):
            return                                        # a replay of something already handled
        # Remembered before it is handled (even when it is something Lilly ignores, so it is not sent again): a
        # crash may drop one message, but can never run one twice.
        await self._rt.db.write(lambda con: bridges.set_last_update(con, PLATFORM, update_id))
        if parsed is None:
            return
        try:
            if isinstance(parsed, Text):
                await self._on_text(api, parsed)
            else:
                await self._on_press(api, parsed)
        except TelegramError as exc:
            log.warning("telegram reply failed: %s", exc)
        except LillyError as exc:
            log.warning("chat request refused: %s", type(exc).__name__)
        except Exception:
            log.exception("chat message handling failed")

    # ---- messages -----------------------------------------------------------------------------------
    async def _on_text(self, api: TelegramApi, msg: Text) -> None:
        if msg.chat_type != "private":
            return                                        # only direct chats: nobody else in a group can talk to Lilly
        linked = bridges.identity(self._rt.db.reader, PLATFORM, msg.user_id) is not None
        if msg.text.startswith("/pair"):
            await self._pair(api, msg)
            return
        if not linked:
            return                                        # strangers get no answer at all
        settings = self._rt.settings.bridges
        if msg.text.split()[0] in ("/start", "/help"):
            await api.send(msg.chat_id, HELP)
            return
        if msg.text.strip() == "/stop":
            stopped = await self._stop_user(msg.user_id)
            await api.send(msg.chat_id, f"Stopped {stopped} task(s)." if stopped else "Nothing is running from this chat.")
            return
        if not self._limit.allow(msg.user_id):
            await api.send(msg.chat_id, "That is a lot of messages. Try again in a minute.")
            return
        if len(msg.text) > settings.max_chars:
            await api.send(msg.chat_id, f"That message is too long (the limit is {settings.max_chars} characters).")
            return
        goal = clean_inbound(msg.text, settings.max_chars)
        if not goal:
            return
        agent = agents.get_agent(self._rt.db.reader, settings.agent_id) if settings.agent_id else None
        if agent is None or not agent.chat_allowed:
            await api.send(msg.chat_id, "No agent is set up for chat yet. Choose one in Lilly under Settings → Chat apps.")
            return
        try:
            row = await self._rt.orchestrator.submit(SubmitRequest(goal, agent_id=agent.id, source=PLATFORM, outside=True))
        except ConflictError as exc:
            await api.send(msg.chat_id, str(exc))
            return
        self._tracked[row.id] = msg.user_id
        while len(self._tracked) > MAX_TRACKED:
            self._tracked.popitem(last=False)
        await api.send(msg.chat_id, "On it.")

    async def _pair(self, api: TelegramApi, msg: Text) -> None:
        if not self._strangers.allow(msg.user_id):
            return
        code = msg.text[len("/pair"):].strip()
        if code and self._pairing.redeem(code, msg.user_id):
            now = self._rt.clock()
            await self._rt.db.write(lambda con: bridges.add_identity(con, PLATFORM, msg.user_id, msg.chat_id, msg.name, now))
            await api.send(msg.chat_id, "Paired. This chat can now talk to Lilly. Send /help to see what it can do.")
        else:
            await api.send(msg.chat_id, "That code did not work. Make a new one in Lilly under Settings → Chat apps.")

    async def _stop_user(self, user_id: int) -> int:
        stopped = 0
        for task_id, user in list(self._tracked.items()):
            if user == user_id:
                with contextlib.suppress(LillyError):
                    await self._rt.orchestrator.cancel(task_id)
                    stopped += 1
        return stopped

    # ---- approvals from chat ------------------------------------------------------------------------
    async def _on_press(self, api: TelegramApi, press: Press) -> None:
        if bridges.identity(self._rt.db.reader, PLATFORM, press.user_id) is None:
            return
        parts = press.data.split(":")
        if len(parts) != 3 or parts[0] != "a" or parts[2] not in ("y", "n"):
            await api.answer(press.query_id)
            return
        approval = self._rt.approvals.get(parts[1])
        if approval is None or approval.status != "pending" or approval.task_id not in self._tracked:
            await api.answer(press.query_id, "That request is no longer waiting.")
            return
        yes = parts[2] == "y"
        try:
            # The hash comes from the stored request, so only exactly what was shown can be approved.
            await self._rt.approvals.decide(approval.id, approve=yes, payload_hash=approval.payload_hash)
        except LillyError:
            await api.answer(press.query_id, "That request is no longer waiting.")
            return
        await api.answer(press.query_id, "Approved." if yes else "Declined.")
        await api.edit(press.chat_id, press.message_id, f"{approval.summary}\n\n{'Approved' if yes else 'Declined'}.")

    async def _ask(self, api: TelegramApi, task_id: str) -> None:
        user = self._tracked.get(task_id)
        owner = None if user is None else bridges.identity(self._rt.db.reader, PLATFORM, user)
        if owner is None:
            return
        chat_id = owner.chat_id
        for approval in self._rt.approvals.pending():
            if approval.task_id != task_id or approval.id in self._announced:
                continue
            self._announced.add(approval.id)
            shown, whole = _describe(approval.summary, approval.payload_json)
            tool = _tool_of(approval.payload_json)
            if approval.kind != "step" or tool.startswith("computer."):
                await api.send(chat_id, f"{shown}\n\nThis one has to be approved in the Lilly app.")
            elif not whole:                               # approving would run more than what is shown here
                await api.send(chat_id, f"{shown}\n\nThis one is too long to show in full, so it has to be approved "
                                        "in the Lilly app.")
            else:
                await api.send(chat_id, shown, [("Approve", f"a:{approval.id}:y"), ("Decline", f"a:{approval.id}:n")])

    # ---- answers ------------------------------------------------------------------------------------
    async def _watch(self) -> None:
        feed = self._rt.bus.subscribe()
        try:
            async for message in feed:
                api, task_id = self._api, message.get("task_id")
                if api is None or not isinstance(task_id, str) or task_id not in self._tracked:
                    continue
                try:
                    if message.get("type") == "approval" and message.get("action") == "created":
                        await self._ask(api, task_id)
                    elif message.get("type") == "task" and message.get("state") in TERMINAL:
                        await self._finish(api, task_id)
                except TelegramError as exc:
                    log.warning("telegram reply failed: %s", exc)
                except Exception:
                    log.exception("chat reply failed")
        finally:
            await feed.aclose()

    async def _finish(self, api: TelegramApi, task_id: str) -> None:
        user = self._tracked.pop(task_id, None)
        owner = None if user is None else bridges.identity(self._rt.db.reader, PLATFORM, user)
        row = tasks.get_task(self._rt.db.reader, task_id)
        if owner is None or row is None:
            return
        if row.state.value == "DONE" and row.answer:
            private = row.label is not Label.PUBLIC and not self._rt.settings.bridges.private_replies
            text = ("Done. The answer used private data, so it stays in Lilly. Open the app to read it." if private
                    else row.answer)
        else:
            text = f"Lilly stopped: {(row.error or row.state.value.lower())[:300]}"
        await api.send(owner.chat_id, text)


def _tool_of(payload_json: str) -> str:
    try:
        data = json.loads(payload_json)
    except ValueError:
        return ""
    return str(data.get("tool", "")) if isinstance(data, dict) else ""


def _describe(summary: str, payload_json: str) -> tuple[str, bool]:
    """What the approval will do, in the words the app shows: the summary, the exact arguments and the reason, and
    whether that is everything (a list or text cut for display, or a card cut to fit, is not)."""
    try:
        data: Any = json.loads(payload_json)
    except ValueError:
        data = {}
    lines, whole = [f"Lilly wants to: {summary}"], True
    if isinstance(data, dict) and data.get("args"):
        exact = json.dumps(data["args"], ensure_ascii=False)
        whole = len(exact) <= EXACT_CHARS and not is_clipped(data["args"])
        lines.append("Exactly: " + exact[:EXACT_CHARS] + ("" if whole else "…"))
    return "\n".join(lines), whole
