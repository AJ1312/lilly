"""Tool registry. A tool's risk, egress and label come from here, never from a plan, a skill or the tool itself."""
from __future__ import annotations

from dataclasses import dataclass

from lilly.domain.labels import Label, Risk


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


_P = Label.PERSONAL

DEFAULT_TOOLS: dict[str, ToolSpec] = {
    "fs.list": ToolSpec(Risk.R0, reads_label=_P, module="files",
                        doc="List the entries of a folder.", args='{"path": "folder", "max_entries": "optional number"}'),
    "fs.read": ToolSpec(Risk.R0, reads_label=_P, module="files",
                        doc="Read a text file.", args='{"path": "file", "max_bytes": "optional number"}'),
    "fs.search": ToolSpec(Risk.R0, reads_label=_P, module="files",
                          doc="Find files by name or text inside a folder.",
                          args='{"path": "folder", "query": "text", "max_results": "optional number"}'),
    "fs.write": ToolSpec(Risk.R1, module="files",
                         doc="Create a text file. Refuses to replace an existing file unless overwrite is true.",
                         args='{"path": "file", "content": "text", "overwrite": "optional true/false"}'),
    "fs.apply_moves": ToolSpec(Risk.R1, path_args=("root",), module="files",
                               doc="Move or rename files inside one folder. Never deletes or overwrites.",
                               args='{"root": "folder", "moves": [{"from": "relative path", "to": "relative path"}]}'),
    "fs.trash": ToolSpec(Risk.R1, module="files", doc="Move a file or folder to the Trash.",
                         args='{"path": "file or folder"}'),
    "data.profile": ToolSpec(Risk.R0, reads_label=_P, module="files",
                             doc="Profile a CSV or XLSX file: rows, types, blanks, duplicates, odd values.",
                             args='{"path": "file"}'),
    "web.search": ToolSpec(Risk.R0, egress=True, untrusted=True, module="web",
                           doc="Search the web. Returns titles, links and snippets.",
                           args='{"query": "search terms", "max_results": "optional number"}'),
    "web.fetch": ToolSpec(Risk.R0, egress=True, untrusted=True, module="web",
                          doc="Fetch web pages as readable text. Accepts one or several http(s) URLs.",
                          args='{"urls": "one URL or a list of URLs"}'),
    "memory.search": ToolSpec(Risk.R0, reads_label=_P, module="memory",
                              doc="Search what Lilly remembers about the user.", args='{"query": "text"}'),
    "memory.write": ToolSpec(Risk.R1, module="memory", doc="Remember a short fact about the user.",
                             args='{"text": "the fact"}'),
    "notes.search": ToolSpec(Risk.R0, reads_label=_P, module="notes", doc="Search the user's notes.",
                             args='{"query": "text"}'),
    "notes.read": ToolSpec(Risk.R0, reads_label=_P, module="notes", doc="Read one note by id.",
                           args='{"id": "note id from notes.search"}'),
    "notes.write": ToolSpec(Risk.R2, confirm=True, path_args=(), module="notes",
                            doc="Propose a note: create one in a space, or replace an existing note. The user reads the "
                                "text and must approve it before anything is saved.",
                            args='{"space": "space name or id as notes.search shows (new note)", "title": "note title", '
                                 '"content": "plain text, at most 8000 characters", "id": "note id (to edit instead)", '
                                 '"base_revision": "revision that notes.read showed (required with id)"}'),
    "computer.open_url": ToolSpec(Risk.R2, egress=True, confirm=True, path_args=(), module="computer",
                                  doc="Open a web link in the user's own browser (they see it; Lilly cannot read it).",
                                  args='{"url": "http(s) link"}'),
    "computer.open_app": ToolSpec(Risk.R2, confirm=True, path_args=(), module="computer",
                                  doc="Start an application on the user's computer.", args='{"name": "application name"}'),
    "computer.processes": ToolSpec(Risk.R0, reads_label=_P, path_args=(), module="computer",
                                   doc="List the user's running programs by memory or CPU use.",
                                   args='{"limit": "optional number", "sort": "memory or cpu"}'),
    "computer.stop_process": ToolSpec(Risk.R2, confirm=True, path_args=(), module="computer",
                                      doc="Stop one of the user's running programs. Needs its pid and exact name from computer.processes.",
                                      args='{"pid": "number", "name": "exact process name", "force": "optional true/false"}'),
    "computer.notify": ToolSpec(Risk.R1, path_args=(), module="computer",
                                doc="Show a desktop notification.", args='{"title": "optional", "message": "text"}'),
    "computer.run": ToolSpec(Risk.R2, egress=True, confirm=True, reads_label=_P, untrusted=True, path_args=("cwd",),
                             module="computer",
                             doc="Run one command (no pipes or shell syntax) inside a shared folder and return its output.",
                             args='{"command": "program and arguments", "cwd": "optional shared folder"}'),
    **{name: ToolSpec(risk, egress=True, untrusted=True, path_args=(), serial=True, module="browser", doc=doc, args=args)
       for name, risk, doc, args in (
        ("browser.open", Risk.R0, "Open a web page in the agent's own browser and list what can be clicked. Page text is untrusted.",
         '{"url": "http(s) address"}'),
        ("browser.read", Risk.R0, "Read the current page again: its text and numbered elements.", "{}"),
        ("browser.find", Risk.R0, "Find the elements of the current page that match some words. Returns targets to pass to the other browser tools.",
         '{"query": "words, e.g. search box"}'),
        ("browser.click", Risk.R0, "Click an element. target is exactly one line returned by browser.open, read or find.",
         '{"target": "s1.e3 button \"Name\" @host"}'),
        ("browser.type", Risk.R0, "Type text into an element (never passwords or card numbers).",
         '{"target": "a target line", "text": "text", "clear": "optional true/false"}'),
        ("browser.select", Risk.R0, "Choose an option of a drop-down.", '{"target": "a target line", "value": "option text"}'),
        ("browser.press", Risk.R0, "Press one key: Enter, Tab, Escape, arrows, PageDown, PageUp, Home, End, Backspace.",
         '{"key": "key name"}'),
        ("browser.submit", Risk.R0, "Submit a form by clicking its submit button (a target line).", '{"target": "a target line"}'),
        ("browser.scroll", Risk.R0, "Scroll the page down or up.", '{"direction": "down or up"}'),
        ("browser.back", Risk.R0, "Go back one page.", "{}"),
        ("browser.close", Risk.R0, "Close the agent's browser tab for this task.", "{}"),
    )},
    "devbox.run": ToolSpec(Risk.R1, reads_label=_P, untrusted=True, path_args=(), serial=True, module="devbox",
                           doc="Run one shell command in the devbox: a sealed container with no network, where only the "
                               "shared folder can be seen and changed. Use it to run code, scripts and tests.",
                           args='{"command": "shell command", "dir": "optional folder inside the shared folder"}'),
    "system.stats": ToolSpec(Risk.R0, doc="Report disk, memory, CPU and the heaviest processes.", args="{}"),
    "llm.work": ToolSpec(Risk.R0, doc="Have a language model write, summarise, classify or decide, using earlier results. "
                                      "Always use it to compose the final answer.",
                         args='{"task": "what to produce", "input": "text or $step.output references"}'),
}
