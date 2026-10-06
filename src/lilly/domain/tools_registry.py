"""Tool registry. A tool's risk, egress and label come from here, never from a plan, a skill or the tool itself."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lilly.domain.labels import Label, Risk

# Verified naming rules as of 2026-09-24:
# - OpenAI / Mistral: ^[a-zA-Z0-9_-]{1,64}$ (docs.openai.com, docs.mistral.ai: alphanumeric, underscore, hyphen; no dots)
# - Gemini: ^[a-zA-Z_][a-zA-Z0-9_]*$ (ai.google.dev: alphanumeric and underscore; no dots, no hyphens)
# - Ollama: standard function identifier (ollama.com: alphanumeric and underscore; no dots)

def wire_name(name: str) -> str:
    """Translate dotted Lilly tool name to provider-safe function identifier with double underscore."""
    return name.replace(".", "__")


def unwire_name(wire: str) -> str:
    """Translate provider function identifier back to dotted Lilly tool name."""
    return wire.replace("__", ".")


def check_tool_name(name: str) -> None:
    """Refuse to register any tool whose real name already contains double underscore."""
    if "__" in name:
        raise ValueError(f"Tool name {name!r} cannot contain '__' as it is reserved for provider wire encoding")


def render_args_from_schema(schema: Mapping[str, Any]) -> str:
    """Render a human-readable argument summary string from a JSON Schema for the legacy planner."""
    props = schema.get("properties", {})
    required = set(schema.get("required", ()))
    pieces: list[str] = []
    for k, v in props.items():
        desc = v.get("description") or v.get("type", "value")
        if k not in required:
            desc = f"optional {desc}"
        pieces.append(f'"{k}": "{desc}"')
    return "{" + ", ".join(pieces) + "}"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    risk: Risk
    egress: bool = False                   # sends data off the device (a request can carry private data out)
    reads_label: Label = Label.PUBLIC      # sensitivity of what the tool reads
    untrusted: bool = False                # returns content that came from outside
    path_args: tuple[str, ...] = ("path",) # arguments that are file paths, checked against the granted roots
    confirm: bool = False                  # needs the user's approval in every mode, even Open
    module: str | None = None              # optional module that provides it; None means always available
    serial: bool = False                   # keeps state between calls: never runs beside another step
    doc: str = ""                          # one line for the planner
    args: str = ""                         # argument summary for the planner
    schema: Mapping[str, Any] = field(default_factory=dict)  # JSON Schema for native tool calling
    terminal: bool = False                  # a successful call can be the whole task; the answer is written by code
    standing_ok: bool = False              # the owner may allow this tool for one named target without asking each time

    def __post_init__(self) -> None:
        if not self.args and self.schema:
            object.__setattr__(self, "args", render_args_from_schema(self.schema))


_P = Label.PERSONAL

DEFAULT_TOOLS: dict[str, ToolSpec] = {
    "fs.list": ToolSpec(
        Risk.R0, reads_label=_P, module="files",
        doc="List the entries of a folder.",
        args='{"path": "folder", "max_entries": "optional number"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path to list"},
                "max_entries": {"type": "integer", "description": "Optional maximum entries to return", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    "fs.read": ToolSpec(
        Risk.R0, reads_label=_P, module="files",
        doc="Read a text file. Use offset and limit (lines) to read part of a large file. Lines are numbered.",
        args='{"path": "file", "offset": "optional line number", "limit": "optional line count", "max_bytes": "optional number"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "1-based line number to start reading from", "minimum": 1},
                "limit": {"type": "integer", "description": "Maximum number of lines to read", "minimum": 1},
                "max_bytes": {"type": "integer", "description": "Optional maximum bytes to read", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    "fs.edit": ToolSpec(
        Risk.R1, module="files",
        doc="Replace exact text in an existing file. old must match the file exactly and appear once, unless replace_all is true. Read the file first.",
        args='{"path": "file", "old": "exact text to replace", "new": "substitute text", "replace_all": "optional boolean"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old": {"type": "string", "description": "Exact text to replace (must match uniquely unless replace_all is true)"},
                "new": {"type": "string", "description": "New text to substitute in place of old"},
                "replace_all": {"type": "boolean", "description": "Whether to replace all occurrences instead of requiring a unique match"},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        },
    ),
    "fs.search": ToolSpec(
        Risk.R0, reads_label=_P, module="files",
        doc="Find files by name or text inside a folder.",
        args='{"path": "folder", "query": "text", "max_results": "optional number"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path to search inside"},
                "query": {"type": "string", "description": "Text query or filename pattern"},
                "max_results": {"type": "integer", "description": "Optional maximum results to return", "minimum": 1},
            },
            "required": ["path", "query"],
            "additionalProperties": False,
        },
    ),
    "fs.write": ToolSpec(
        Risk.R1, module="files",
        doc="Create a text file. Refuses to replace an existing file unless overwrite is true.",
        args='{"path": "file", "content": "text", "overwrite": "optional true/false"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to create"},
                "content": {"type": "string", "description": "Text content to write"},
                "overwrite": {"type": "boolean", "description": "Whether to overwrite if file exists"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    ),
    "fs.apply_moves": ToolSpec(
        Risk.R1, path_args=("root",), module="files",
        doc="Move or rename files inside one folder. Never deletes or overwrites.",
        args='{"root": "folder", "moves": [{"from": "relative path", "to": "relative path"}]}',
        schema={
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Root folder for relative move paths"},
                "moves": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string", "description": "Relative source path"},
                            "to": {"type": "string", "description": "Relative destination path"},
                        },
                        "required": ["from", "to"],
                        "additionalProperties": False,
                    },
                    "description": "List of move operations",
                },
            },
            "required": ["root", "moves"],
            "additionalProperties": False,
        },
    ),
    "fs.trash": ToolSpec(
        Risk.R1, module="files",
        doc="Move a file or folder to the Trash.",
        args='{"path": "file or folder"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or folder path to move to Trash"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    "data.profile": ToolSpec(
        Risk.R0, reads_label=_P, module="files",
        doc="Profile a CSV or XLSX file: rows, types, blanks, duplicates, odd values.",
        args='{"path": "file"}',
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "CSV or XLSX file path to profile"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    "web.search": ToolSpec(
        Risk.R0, egress=True, untrusted=True, module="web",
        doc="Search the web. Returns titles, links and snippets.",
        args='{"query": "search terms", "max_results": "optional number"}',
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms to look up"},
                "max_results": {"type": "integer", "description": "Optional maximum results to return", "minimum": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "web.fetch": ToolSpec(
        Risk.R0, egress=True, untrusted=True, module="web",
        doc="Fetch web pages as readable text. Accepts one or several http(s) URLs.",
        args='{"urls": "one URL or a list of URLs"}',
        schema={
            "type": "object",
            "properties": {
                "urls": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": "One URL string or list of URLs to fetch",
                },
            },
            "required": ["urls"],
            "additionalProperties": False,
        },
    ),
    "web.research": ToolSpec(
        Risk.R0, egress=True, untrusted=True, module="web",
        doc="Search the web and read the top results in one step. Returns title, URL and an excerpt for each. Use this instead of web.search followed by web.fetch.",
        args='{"query": "search query", "max_sources": "optional number 1..5"}',
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Web search query"},
                "max_sources": {"type": "integer", "description": "Number of top sources to read (1 to 5)", "minimum": 1, "maximum": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "memory.search": ToolSpec(
        Risk.R0, reads_label=_P, module="memory",
        doc="Search what Lilly remembers about the user.",
        args='{"query": "text"}',
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query about user memory"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "memory.write": ToolSpec(
        Risk.R1, module="memory",
        doc="Remember a short fact about the user.",
        args='{"text": "the fact", "tags": ["preference"]}',
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Short fact about the user to remember"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional short tags"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    "notes.search": ToolSpec(
        Risk.R0, reads_label=_P, module="notes",
        doc="Search the user's notes.",
        args='{"query": "text"}',
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query in user notes"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "notes.read": ToolSpec(
        Risk.R0, reads_label=_P, module="notes",
        doc="Read one note by id.",
        args='{"id": "note id from notes.search"}',
        schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Note id from notes.search"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    "notes.write": ToolSpec(
        Risk.R2, confirm=True, path_args=(), module="notes",
        doc="Propose a note: create one in a space, or replace an existing note. The user reads the "
            "text and must approve it before anything is saved.",
        args='{"space": "space name or id as notes.search shows (new note)", "title": "note title", '
             '"content": "plain text, at most 8000 characters", "id": "note id (to edit instead)", '
             '"base_revision": "revision that notes.read showed (required with id)"}',
        schema={
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name or id (new note)"},
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Plain text content (max 8000 chars)", "maxLength": 8000},
                "id": {"type": "string", "description": "Note id to edit instead"},
                "base_revision": {"type": "integer", "description": "Revision that notes.read showed (required with id)"},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    ),
    "computer.open_url": ToolSpec(
        Risk.R2, egress=True, confirm=True, path_args=(), module="computer",
        terminal=False, standing_ok=True,
        doc="Open a web link in the user's own browser (they see it; Lilly cannot read it).",
        args='{"url": "http(s) link"}',
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) link to open"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    "computer.open_app": ToolSpec(
        Risk.R2, confirm=True, path_args=(), module="computer",
        terminal=False, standing_ok=True,
        doc="Start an application on the user's computer.",
        args='{"name": "application name"}',
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Application name to start"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    "computer.processes": ToolSpec(
        Risk.R0, reads_label=_P, path_args=(), module="computer",
        doc="List the user's running programs by memory or CPU use.",
        args='{"limit": "optional number", "sort": "memory or cpu"}',
        schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum processes to list", "minimum": 1},
                "sort": {"type": "string", "enum": ["memory", "cpu"], "description": "Sort order: memory or cpu"},
            },
            "additionalProperties": False,
        },
    ),
    "computer.stop_process": ToolSpec(
        Risk.R2, confirm=True, path_args=(), module="computer",
        doc="Stop one of the user's running programs. Needs its pid and exact name from computer.processes.",
        args='{"pid": "number", "name": "exact process name", "force": "optional true/false"}',
        schema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID"},
                "name": {"type": "string", "description": "Exact process name"},
                "force": {"type": "boolean", "description": "Force kill if true"},
            },
            "required": ["pid", "name"],
            "additionalProperties": False,
        },
    ),
    "computer.notify": ToolSpec(
        Risk.R1, path_args=(), module="computer",
        doc="Show a desktop notification.",
        args='{"title": "optional", "message": "text"}',
        schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification message text"},
                "title": {"type": "string", "description": "Optional notification title"},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    ),
    "computer.run": ToolSpec(
        Risk.R2, egress=True, confirm=True, reads_label=_P, untrusted=True, path_args=("cwd",),
        module="computer",
        doc="Run one command (no pipes or shell syntax) inside a shared folder and return its output.",
        args='{"command": "program and arguments", "cwd": "optional shared folder"}',
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Program and arguments to run (no pipes or shell syntax)"},
                "cwd": {"type": "string", "description": "Optional shared folder path"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    ),
    "browser.open": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Open a web page in the agent's own browser and list what can be clicked. Page text is untrusted.",
        args='{"url": "http(s) address"}',
        schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "http(s) address to open"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    "browser.read": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Read the current page again: its text and numbered elements.",
        args="{}",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "browser.find": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Find the elements of the current page that match some words. Returns targets to pass to the other browser tools.",
        args='{"query": "words, e.g. search box"}',
        schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search words to find elements"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "browser.click": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Click an element. target is exactly one line returned by browser.open, read or find.",
        args='{"target": "s1.e3 button \\"Name\\" @host"}',
        schema={
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Target element line"}},
            "required": ["target"],
            "additionalProperties": False,
        },
    ),
    "browser.type": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Type text into an element (never passwords or card numbers).",
        args='{"target": "a target line", "text": "text", "clear": "optional true/false"}',
        schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target element line"},
                "text": {"type": "string", "description": "Text to type"},
                "clear": {"type": "boolean", "description": "Whether to clear input first"},
            },
            "required": ["target", "text"],
            "additionalProperties": False,
        },
    ),
    "browser.select": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Choose an option of a drop-down.",
        args='{"target": "a target line", "value": "option text"}',
        schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target element line"},
                "value": {"type": "string", "description": "Option text or value to choose"},
            },
            "required": ["target", "value"],
            "additionalProperties": False,
        },
    ),
    "browser.press": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Press one key: Enter, Tab, Escape, arrows, PageDown, PageUp, Home, End, Backspace.",
        args='{"key": "key name"}',
        schema={
            "type": "object",
            "properties": {"key": {"type": "string", "description": "Key name to press"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    ),
    "browser.submit": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Submit a form by clicking its submit button (a target line).",
        args='{"target": "a target line"}',
        schema={
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Target submit button line"}},
            "required": ["target"],
            "additionalProperties": False,
        },
    ),
    "browser.scroll": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Scroll the page down or up.",
        args='{"direction": "down or up"}',
        schema={
            "type": "object",
            "properties": {"direction": {"type": "string", "enum": ["down", "up"], "description": "Scroll direction"}},
            "required": ["direction"],
            "additionalProperties": False,
        },
    ),
    "browser.back": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Go back one page.",
        args="{}",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "browser.close": ToolSpec(
        Risk.R0, egress=True, untrusted=True, path_args=(), serial=True, module="browser",
        doc="Close the agent's browser tab for this task.",
        args="{}",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "devbox.run": ToolSpec(
        Risk.R1, reads_label=_P, untrusted=True, path_args=(), serial=True, module="devbox",
        doc="Run one shell command in the devbox: a sealed container with no network, where only the "
            "shared folder can be seen and changed. Use it to run code, scripts and tests.",
        args='{"command": "shell command", "dir": "optional folder inside the shared folder"}',
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "dir": {"type": "string", "description": "Optional working directory relative to shared folder"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    ),
    "system.stats": ToolSpec(
        Risk.R0,
        doc="Report disk, memory, CPU and the heaviest processes.",
        args="{}",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "llm.work": ToolSpec(
        Risk.R0,
        doc="Have a language model write, summarise, classify or decide, using earlier results. "
            "Always use it to compose the final answer.",
        args='{"task": "what to produce", "input": "text or $step.output references"}',
        schema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What to produce or perform"},
                "input": {"type": "string", "description": "Input text or step references"},
            },
            "required": ["task", "input"],
            "additionalProperties": False,
        },
    ),
    # Control tools
    "result.read": ToolSpec(
        Risk.R0,
        doc="Read more of an earlier result that was cut short. Give the step id and an offset in characters.",
        args='{"step": "step id", "offset": "optional character offset"}',
        schema={
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step ID whose output to read"},
                "offset": {"type": "integer", "description": "Character offset to start reading from", "minimum": 0},
            },
            "required": ["step"],
            "additionalProperties": False,
        },
    ),
    "agent.plan": ToolSpec(
        Risk.R0,
        doc="Write or update your to-do list. Send the whole list each time. Each item has text and a status: todo, doing, done or blocked.",
        args='{"todos": [{"text": "item description", "status": "todo"}]}',
        schema={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {"type": "string", "maxLength": 120},
                            {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string", "maxLength": 120},
                                    "status": {"type": "string", "enum": ["todo", "doing", "done", "blocked"]},
                                },
                                "required": ["text"],
                                "additionalProperties": False,
                            },
                        ],
                    },
                    "maxItems": 12,
                    "description": "List of to-do items (at most 12 items of at most 120 characters)",
                },
            },
            "required": ["todos"],
            "additionalProperties": False,
        },
    ),
    "agent.ask": ToolSpec(
        Risk.R0,
        doc="Ask the user one short question and wait for the answer. Use it only for information you cannot look up.",
        args='{"question": "the question", "choices": ["optional", "choices"]}',
        schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Short question for the user"},
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": "Optional choices for the user (at most 5)",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    "agent.delegate": ToolSpec(
        Risk.R0,
        doc="Hand a self-contained job to another agent in the user's crew and get back its answer. Name the agent and say exactly what you need.",
        args='{"agent": "Mochi", "task": "Research Python 3.13"}',
        schema={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Name or pet species of the agent"},
                "task": {"type": "string", "description": "Self-contained task instructions for the agent"},
            },
            "required": ["agent", "task"],
            "additionalProperties": False,
        },
    ),
    "skill.load": ToolSpec(
        Risk.R0,
        doc="Load the full text of one of your named skills.",
        args='{"name": "skill name"}',
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the skill to load from the pet sheet"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
}

# Verify all default tools have valid names
for tool_name in DEFAULT_TOOLS:
    check_tool_name(tool_name)
