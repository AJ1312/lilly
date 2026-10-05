"""Telegram's Bot API: the few calls Lilly makes, and strict parsing of what comes back.

Lilly only ever reaches out (long polling); it opens no port. The bot token is part of the request address, so it
is held as a Secret, never logged, and no error message here carries the address."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from lilly.domain.ports import Secret

API = "https://api.telegram.org"
MAX_TEXT = 4000                 # Telegram refuses messages over 4096 characters
MAX_RESPONSE_BYTES = 1_000_000


class TelegramError(Exception):
    """A plain-words reason. `status` is Telegram's error code when it gave one; `retry_after` seconds when asked to wait."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status, self.retry_after = status, retry_after

    @property
    def fatal(self) -> bool:
        """The token is wrong or revoked: retrying cannot help."""
        return self.status in (401, 404)


@dataclass(frozen=True, slots=True)
class Text:
    update_id: int
    user_id: int
    chat_id: int
    chat_type: str
    text: str
    name: str                   # shown to the owner when pairing; never used to decide anything


@dataclass(frozen=True, slots=True)
class Press:
    update_id: int
    user_id: int
    chat_id: int
    message_id: int
    query_id: str
    data: str


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_update(update: object) -> Text | Press | None:
    """A text message or a button press, or None for anything else. Nothing is trusted: every field is checked."""
    if not isinstance(update, dict) or (update_id := _int(update.get("update_id"))) is None:
        return None
    if isinstance(message := update.get("message"), dict):
        sender, chat, text = message.get("from"), message.get("chat"), message.get("text")
        if not (isinstance(sender, dict) and isinstance(chat, dict) and isinstance(text, str)):
            return None
        user_id, chat_id, kind = _int(sender.get("id")), _int(chat.get("id")), chat.get("type")
        if user_id is None or chat_id is None or not isinstance(kind, str) or sender.get("is_bot") is True:
            return None
        name = sender.get("first_name")
        return Text(update_id, user_id, chat_id, kind, text, name[:80] if isinstance(name, str) else "")
    if isinstance(query := update.get("callback_query"), dict):
        sender, data, query_id = query.get("from"), query.get("data"), query.get("id")
        message = query.get("message")
        if not (isinstance(sender, dict) and isinstance(data, str) and isinstance(query_id, str)
                and isinstance(message, dict) and isinstance(message.get("chat"), dict)):
            return None
        user_id, chat_id, message_id = _int(sender.get("id")), _int(message["chat"].get("id")), _int(message.get("message_id"))
        if user_id is None or chat_id is None or message_id is None:
            return None
        return Press(update_id, user_id, chat_id, message_id, query_id, data[:64])
    return None


class TelegramApi:
    def __init__(self, client: httpx.AsyncClient, token: Secret, base: str = API) -> None:
        self._client, self._token, self._base = client, token, base.rstrip("/")

    async def call(self, method: str, payload: dict[str, Any], wait_s: float = 15.0) -> Any:
        url = f"{self._base}/bot{self._token.reveal()}/{method}"
        try:
            resp = await self._client.post(url, json=payload, timeout=httpx.Timeout(wait_s, connect=10.0))
        except httpx.HTTPError:
            raise TelegramError("Telegram could not be reached") from None      # the cause would carry the address
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise TelegramError("Telegram sent too much data")
        try:
            data = resp.json()
        except ValueError:
            raise TelegramError("Telegram sent something unreadable", resp.status_code) from None
        if not isinstance(data, dict) or data.get("ok") is not True:
            code = _int(data.get("error_code")) if isinstance(data, dict) else None
            params = data.get("parameters") if isinstance(data, dict) else None
            wait = params.get("retry_after") if isinstance(params, dict) else None
            raise TelegramError(_explain(code or resp.status_code), code or resp.status_code,
                                float(wait) if isinstance(wait, int | float) and not isinstance(wait, bool) else None)
        return data.get("result")

    async def me(self) -> str:
        """The bot's username, which also proves the token works."""
        result = await self.call("getMe", {})
        name = result.get("username") if isinstance(result, dict) else None
        if not isinstance(name, str):
            raise TelegramError("Telegram did not name the bot")
        return name

    async def updates(self, after: int, wait_s: int) -> list[object]:
        result = await self.call("getUpdates", {"offset": after + 1, "timeout": wait_s, "limit": 20,
                                                "allowed_updates": ["message", "callback_query"]}, wait_s + 10.0)
        return result if isinstance(result, list) else []

    async def send(self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        await self.call("sendMessage", payload)

    async def answer(self, query_id: str, text: str = "") -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": query_id, "text": text[:180]})

    async def edit(self, chat_id: int, message_id: int, text: str) -> None:
        """Replace a message's text and remove its buttons."""
        await self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text[:MAX_TEXT]})


def _explain(code: int | None) -> str:
    return {401: "Telegram rejected the bot token", 404: "Telegram does not know that bot token",
            409: "another program is already reading this bot's messages", 429: "Telegram asked Lilly to slow down",
            }.get(code or 0, f"Telegram refused the request (error {code})" if code else "Telegram refused the request")
