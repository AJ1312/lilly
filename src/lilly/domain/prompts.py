"""Shared prompts and message templates for Lilly 2.0 domain and providers."""
from __future__ import annotations

ACTION_PROTOCOL = """Reply with exactly one JSON object and nothing else, in one of these two shapes.

To use tools:
{{"thought": "<one sentence: why this action>", "calls": [{{"tool": "<name>", "args": {{ }} }}]}}

To finish:
{{"thought": "<one sentence>", "final": "<the answer the user will read>"}}

Use several entries in "calls" only for independent reads. After the tools run you will receive their results in the next message, and you reply again in the same format.

Tools:
{rendered_tool_list}"""

ACTION_PROTOCOL_REPAIR = (
    "That reply was not a single valid JSON object in one of the two shapes. "
    "Reply again with only the JSON object."
)

PROTECTED_PATH_REASON = "This file looks like a test. Changing tests can hide a bug instead of fixing it."

