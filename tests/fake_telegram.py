"""A stand-in for Telegram's Bot API, served through httpx's mock transport. It keeps every call it was given."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

TOKEN = "123456:TEST-TOKEN"
BASE = "https://tg.test"


@dataclass
class FakeTelegram:
    updates: list[dict[str, Any]] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    edits: list[dict[str, Any]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    fail: list[httpx.Response] = field(default_factory=list)        # served, in order, instead of the real answer
    next_id: int = 100
    username: str = "lilly_test_bot"

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    # ---- what a person does in the chat app ---------------------------------------------------------
    def say(self, user: int, text: str, chat_type: str = "private", chat: int | None = None) -> int:
        self.next_id += 1
        self.updates.append({"update_id": self.next_id, "message": {
            "message_id": self.next_id, "from": {"id": user, "is_bot": False, "first_name": f"User{user}"},
            "chat": {"id": chat if chat is not None else user, "type": chat_type}, "text": text}})
        return self.next_id

    def press(self, user: int, data: str, message_id: int = 1) -> None:
        self.next_id += 1
        self.updates.append({"update_id": self.next_id, "callback_query": {
            "id": f"q{self.next_id}", "from": {"id": user, "is_bot": False, "first_name": "x"}, "data": data,
            "message": {"message_id": message_id, "chat": {"id": user, "type": "private"}}}})

    def texts(self, chat: int) -> list[str]:
        return [str(m["text"]) for m in self.sent if m["chat_id"] == chat]

    # ---- the server -------------------------------------------------------------------------------------
    async def handle(self, request: httpx.Request) -> httpx.Response:
        prefix = f"/bot{TOKEN}/"
        if not request.url.path.startswith(prefix):
            return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})
        method = request.url.path[len(prefix):]
        body: dict[str, Any] = json.loads(request.content or b"{}")
        self.calls.append(method)
        if self.fail:
            return self.fail.pop(0)
        if method == "getMe":
            return self._ok({"id": 1, "is_bot": True, "username": self.username})
        if method == "getUpdates":
            wanted = body.get("offset", 0)
            ready = [u for u in self.updates if u["update_id"] >= wanted]
            if not ready:
                await asyncio.sleep(0.01)         # a long poll with nothing to say
            return self._ok(ready)
        if method == "sendMessage":
            self.sent.append(body)
            return self._ok({"message_id": len(self.sent)})
        if method == "answerCallbackQuery":
            self.answers.append(body)
            return self._ok(True)
        if method == "editMessageText":
            self.edits.append(body)
            return self._ok(True)
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})

    @staticmethod
    def _ok(result: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})


def error(code: int, retry_after: int | None = None) -> httpx.Response:
    body: dict[str, Any] = {"ok": False, "error_code": code, "description": "nope"}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return httpx.Response(code, json=body)
