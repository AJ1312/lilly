"""A scripted HTTP server speaking OpenAI, Gemini, and Ollama dialects for tests.

Runs on 127.0.0.1 on an ephemeral port.
Records every incoming request and answers from a predetermined list of scripted replies.
Supports text, native tool calls, SSE streaming, 429 rate limits with Retry-After or retryDelay,
503 errors, malformed responses, and stalls.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


@dataclass
class RecordedRequest:
    """Details of an HTTP request received by FakeLLMServer."""

    method: str
    path: str
    headers: Mapping[str, str]
    body: dict[str, Any] | None
    raw_body: bytes
    tools: list[dict[str, Any]] | None
    messages: list[dict[str, Any]] | None
    received_at: float


@dataclass
class ScriptedReply:
    """A configured response to serve to an LLM client call."""

    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    error_body: dict[str, Any] | str | None = None
    malformed: bool = False
    stall_s: float | None = None
    retry_after: str | float | None = None
    retry_delay: str | None = None
    provider_state: dict[str, Any] | None = None


class FakeLLMServer:
    """Scriptable HTTP mock server for OpenAI, Gemini, and Ollama endpoints."""

    def __init__(self, replies: list[ScriptedReply | str | dict[str, Any]] | None = None) -> None:
        self.replies: list[ScriptedReply] = []
        if replies:
            for r in replies:
                self.enqueue(r)
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass  # suppress console logging in test runs

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path in ("/health", "/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length)
                body: dict[str, Any] | None = None
                try:
                    body = json.loads(raw_body.decode("utf-8")) if raw_body else None
                except Exception:
                    pass

                tools = body.get("tools") if isinstance(body, dict) else None
                messages = body.get("messages") if isinstance(body, dict) else None
                if not messages and isinstance(body, dict) and "contents" in body:
                    messages = body["contents"]

                req_record = RecordedRequest(
                    method=self.command,
                    path=self.path,
                    headers=dict(self.headers),
                    body=body,
                    raw_body=raw_body,
                    tools=tools,
                    messages=messages,
                    received_at=time.time(),
                )
                with outer._lock:
                    outer.requests.append(req_record)
                    reply = outer._pop_reply()

                if reply.stall_s:
                    time.sleep(reply.stall_s)

                if reply.malformed:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b"{this is not valid json")
                    return

                # Check for rate limit or custom error
                if reply.status_code != 200:
                    self._send_error(reply, body)
                    return

                parsed_path = urlparse(self.path).path
                is_stream = bool(body and body.get("stream"))

                if "/api/chat" in parsed_path:
                    # Ollama dialect
                    self._send_ollama(reply, body)
                elif "generateContent" in parsed_path:
                    # Gemini dialect
                    self._send_gemini(reply, body)
                else:
                    # OpenAI chat completions dialect
                    if is_stream:
                        self._send_openai_stream(reply, body)
                    else:
                        self._send_openai(reply, body)

            def _send_error(self, reply: ScriptedReply, body: dict[str, Any] | None) -> None:
                self.send_response(reply.status_code)
                headers = dict(reply.headers)
                if reply.retry_after is not None:
                    headers["Retry-After"] = str(reply.retry_after)

                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                if reply.error_body is not None:
                    if isinstance(reply.error_body, str):
                        self.wfile.write(reply.error_body.encode("utf-8"))
                    else:
                        self.wfile.write(json.dumps(reply.error_body).encode("utf-8"))
                    return

                # Default error payload matching dialect
                parsed_path = urlparse(self.path).path
                if "generateContent" in parsed_path:
                    details = []
                    if reply.retry_delay:
                        details.append({
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": reply.retry_delay,
                        })
                    resp = {
                        "error": {
                            "code": reply.status_code,
                            "message": "Resource has been exhausted" if reply.status_code == 429 else "Error",
                            "status": "RESOURCE_EXHAUSTED" if reply.status_code == 429 else "UNAVAILABLE",
                            "details": details,
                        }
                    }
                else:
                    resp = {
                        "error": {
                            "message": f"Rate limit reached. Retry in {reply.retry_after} s" if reply.retry_after else "Error",
                            "type": "rate_limit_error" if reply.status_code == 429 else "server_error",
                            "code": "rate_limit_exceeded" if reply.status_code == 429 else None,
                        }
                    }
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            def _send_openai(self, reply: ScriptedReply, body: dict[str, Any] | None) -> None:
                self.send_response(200)
                for k, v in reply.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                choices: list[dict[str, Any]] = []
                if reply.tool_calls:
                    formatted_calls = []
                    for i, tc in enumerate(reply.tool_calls):
                        raw_args = tc.get("arguments", {})
                        arg_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args)
                        formatted_calls.append({
                            "id": tc.get("id", f"call_{i}_{int(time.time()*1000)}"),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": arg_str,
                            },
                        })
                    choices.append({
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": reply.content or None,
                            "tool_calls": formatted_calls,
                        },
                        "finish_reason": "tool_calls",
                    })
                else:
                    choices.append({
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": reply.content,
                        },
                        "finish_reason": "stop",
                    })

                resp = {
                    "id": f"chatcmpl-{int(time.time()*1000)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.get("model", "fake-model") if body else "fake-model",
                    "choices": choices,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            def _send_openai_stream(self, reply: ScriptedReply, body: dict[str, Any] | None) -> None:
                self.send_response(200)
                for k, v in reply.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                model = body.get("model", "fake-model") if body else "fake-model"
                cid = f"chatcmpl-{int(time.time()*1000)}"

                if reply.tool_calls:
                    # Role chunk
                    c1 = {
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                    }
                    self.wfile.write(f"data: {json.dumps(c1)}\n\n".encode("utf-8"))
                    self.wfile.flush()

                    for i, tc in enumerate(reply.tool_calls):
                        raw_args = tc.get("arguments", {})
                        arg_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args)
                        call_id = tc.get("id", f"call_{i}_{int(time.time()*1000)}")
                        # Send name chunk
                        c_name = {
                            "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                            "model": model, "choices": [{
                                "index": 0,
                                "delta": {
                                    "tool_calls": [{
                                        "index": i,
                                        "id": call_id,
                                        "type": "function",
                                        "function": {"name": tc["name"], "arguments": ""},
                                    }]
                                },
                                "finish_reason": None,
                            }],
                        }
                        self.wfile.write(f"data: {json.dumps(c_name)}\n\n".encode("utf-8"))
                        self.wfile.flush()

                        # Send arguments chunk (split in 2 chunks to test streaming accumulation)
                        half = len(arg_str) // 2
                        part1, part2 = arg_str[:half], arg_str[half:]
                        for part in (part1, part2):
                            if part:
                                c_arg = {
                                    "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                                    "model": model, "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [{
                                                "index": i,
                                                "function": {"arguments": part},
                                            }]
                                        },
                                        "finish_reason": None,
                                    }],
                                }
                                self.wfile.write(f"data: {json.dumps(c_arg)}\n\n".encode("utf-8"))
                                self.wfile.flush()

                    # Finish chunk
                    c_end = {
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    }
                    self.wfile.write(f"data: {json.dumps(c_end)}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    # Text chunks
                    c1 = {
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model, "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply.content}, "finish_reason": None}],
                    }
                    self.wfile.write(f"data: {json.dumps(c1)}\n\n".encode("utf-8"))
                    c2 = {
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    self.wfile.write(f"data: {json.dumps(c2)}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()

            def _send_gemini(self, reply: ScriptedReply, body: dict[str, Any] | None) -> None:
                self.send_response(200)
                for k, v in reply.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                parts: list[dict[str, Any]] = []
                if reply.tool_calls:
                    for tc in reply.tool_calls:
                        args = tc.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        parts.append({
                            "functionCall": {
                                "name": tc["name"],
                                "args": args,
                            }
                        })
                else:
                    parts.append({"text": reply.content})

                candidate: dict[str, Any] = {
                    "content": {
                        "role": "model",
                        "parts": parts,
                    },
                    "finishReason": "STOP",
                }
                resp: dict[str, Any] = {
                    "candidates": [candidate],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                }
                if reply.provider_state:
                    resp["providerState"] = reply.provider_state
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            def _send_ollama(self, reply: ScriptedReply, body: dict[str, Any] | None) -> None:
                self.send_response(200)
                for k, v in reply.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                model = body.get("model", "fake-model") if body else "fake-model"
                msg: dict[str, Any] = {"role": "assistant", "content": reply.content}
                if reply.tool_calls:
                    tcs = []
                    for tc in reply.tool_calls:
                        args = tc.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        tcs.append({
                            "function": {
                                "name": tc["name"],
                                "arguments": args,
                            }
                        })
                    msg["tool_calls"] = tcs

                resp = {
                    "model": model,
                    "message": msg,
                    "done": True,
                    "prompt_eval_count": 10,
                    "eval_count": 5,
                }
                self.wfile.write(json.dumps(resp).encode("utf-8"))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.openai_url = f"http://127.0.0.1:{self.port}/v1"
        self.gemini_url = f"http://127.0.0.1:{self.port}/v1beta"
        self.ollama_url = f"http://127.0.0.1:{self.port}"
        self._thread: threading.Thread | None = None

    def enqueue(self, reply: ScriptedReply | str | dict[str, Any]) -> None:
        """Add a scripted reply to the FIFO queue."""
        if isinstance(reply, str):
            r = ScriptedReply(content=reply)
        elif isinstance(reply, dict):
            if "status_code" in reply or "tool_calls" in reply:
                r = ScriptedReply(**reply)
            else:
                r = ScriptedReply(content=json.dumps(reply))
        else:
            r = reply
        with self._lock:
            self.replies.append(r)

    def _pop_reply(self) -> ScriptedReply:
        if self.replies:
            return self.replies.pop(0)
        return ScriptedReply(content="ok")

    def start(self) -> FakeLLMServer:
        """Start the background server thread."""
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        """Stop and close the server."""
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)

    def __enter__(self) -> FakeLLMServer:
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.close()
