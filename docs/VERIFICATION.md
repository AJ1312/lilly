# Verification record

What was checked for each delivered milestone, how, and what was **not** checked. "Done" here means the gates pass
and no high or medium review finding is open. It does not mean "no bugs". The last section of each milestone says
what only a real device or service can confirm.

## How a milestone is verified

1. Tests are written with the code, and each fix for a found bug comes with a test that fails without the fix.
2. Gates: `make check` runs ruff, `mypy --strict`, bandit, vulture (dead code), deptry (unused or missing
   dependencies), the import-boundary test (layer ranks) and the full test suite with a coverage floor of 82%.
   The interface is checked with `tsc -b` and `oxlint`.
3. An independent reviewer, who did not write the code, reads the whole diff against the security principles and
   reproduces every claim before reporting it.
4. The tagged tree is packaged with `git archive`, installed into a clean environment with `install.sh`, and started
   once.

## Lilly 2.0 verification record

### Scope
Settings now says why a Laya install made by `install.sh` or `lilly laya install` failed (the reason is kept beside
the add-on until an install succeeds or Laya is removed), instead of only showing "not installed". The installer's
closing message no longer says Laya is not installed when it is; it reports installed, not set up, or skipped. The Laya
card shows "Downloaded and ready on this computer" once installed and is no longer labelled optional.

### What was run
An end-to-end run on a fresh server (separate home, fake Ollama server, real HTTP API): a tool-using task (plan,
`system.stats`, `llm.work`) finished DONE with the right answer, with and without an "installed" Laya whose worker cannot
start. `/api/laya` reported installed in the second case. A 1.7-style settings file without the new `route` question loads
without problems.

### Not verified
Why a particular Mac showed Laya as not downloaded or tasks as failing: neither could be reproduced here. The most likely
cause of the first is that the installer's Laya step failed (for example a blocked download or no Python 3.12 or older
on an Intel Mac); the reason is now recorded and shown.

## Version 1.8.3 (shorter pause after a rate refusal)

### Scope
1.8.2 closed a model for 60 s after any rate refusal that did not say how long to wait, which pushed all the load onto
the other models and made them hit their limits sooner. The pause is now 5 s, doubling only while refusals keep
coming (up to 60 s) and reset by the next success; a stated wait from the provider is still used as given.

### Not verified
Real provider behaviour: whether Gemini and Mistral send a retry time with their refusals is unconfirmed. The only
call-adding change since 1.7.0 is the Laya route shortcut, and only when it is switched to acting.

## Version 1.8.2 (learns provider limits)

### Scope
`LimitWatch`: from a provider's rate refusals Lilly learns how many calls worked in the minute (or day, when the wait
is long) and suggests a limit, shown on the Models screen with a one-click apply; never applied by itself. A model
that refused for rate is now closed to calls for the wait it was given (60 s when none was given) instead of being
tried again on every request.

### Results
Unit tests for the learning (minute, day, lowest kept, bounded memory, owner limit hides the hint), the breaker and
a router test with a provider that starts refusing. Full gate run recorded below.

### Not verified
Real Gemini and Mistral refusals: their retry-after values and wording have not been seen here. Rate-limit headers on
successful calls are not read (a possible next step). Preferring the model with the most headroom is not built.

## Version 1.8.1 (livelier, cuter pets)

### Scope
Pets: pupils follow the pointer (one shared listener, none when no pet is on screen), a tap gives a hop and hearts,
ears and leaves sway while idle, an occasional idle hop, larger glossy eyes and a "w" mouth. All CSS and SVG, no
new dependency; stops for reduced motion. The lit WebGL 3D version is **not** built and stays parked.

### Results
`tsc -b`, `oxlint` clean; budgets and web-contract tests pass; headless Chromium: gaze variables follow the
pointer, a tap sets and clears the poked state with two hearts, no console errors. The full gate run is the one
recorded for 1.8.0 plus these front-end files.

### Not verified
Safari on the Intel Mac (the `rotate` property for the sway needs Safari 14.1 or newer; older ones simply do not
sway), and how it feels on that machine.

## Version 1.8.0 (Laya by default, token saving, agent changes act at once, agent notes)

### Scope
The installer sets Laya up by default (`--no-laya` skips it; a failed Laya step never fails the install). A new Laya
question, "can this be answered without tools?", lets a quick model answer simple requests without the tool list; it
starts watch-only and is labelled by what happened. Narrowing or deleting an agent now cancels its unfinished tasks.
`notes.write` (always asks, edits need the revision that `notes.read` showed). Tests that file tools cannot reach
Lilly's own data. `lilly stop` waits for the server to exit and never signals a process that is not Lilly. `lilly laya
enable/disable` refuses while Lilly is running. The export now keeps agents' skills, pet, look, model and permissions,
and routines. A clear message when no model has a key, shown on the first screen too. Settings no longer fail to
save after Laya is switched on or off with unsaved edits. Doctor requires Python 3.12. Documentation names corrected.

### Results at the tagged commit
`make check`: 1712 passed, 1 skipped, coverage 90.8%; ruff, mypy --strict, bandit, vulture, deptry and the layer test
clean. `tsc -b` and `oxlint` clean; production build 111 kB gzip.

### What was run
Against a scripted model and a fake Laya: the route question (direct answer never sees the tool list, falls back to the
planner when the quick model asks for tools, watch-only changes nothing, a crashing Laya changes nothing, Laya is
warmed, outcomes labelled accepted or corrected); `lilly stop` with real child processes (waits, ignores an unrelated
pid); the CLI refusal while running; the export. Headless Chromium at desktop and phone width: every screen and every
Settings tab opens with no console or page errors, the no-key note shows, and the three assist switches are listed.

### Not verified
* **The real Laya** (still unreachable from this sandbox): download, load, real answers, speed, hashes. The token
  saving is therefore unproven in practice; judge it with `lilly decisions report` before switching it from watch only to acting.
* Laya picking tools or filling in their arguments is **not built** (it cannot generate text); the question list is
  as above. Batching several questions into one model pass is not built.
* Settings drafting after switching Laya on and off with unsaved edits was reasoned and type-checked, not clicked through
  (it needs an installed Laya).
* A real Intel Mac and Safari, real Docker, Telegram, and idle CPU use on the target machine.
* Not done: a pinned-model "unavailable" hint on the pet screen; the reply check still fetches the task once more.

## Version 1.7.0 (Laya assist, guided Laya setup, cleanup)

### Scope
Laya assist (optional plan check and reply check); guided Laya setup with a pre-check, a self-test and a single guide
(`docs/LAYA.md`); the installer no longer downloads Laya unless asked (`--laya`); `lilly doctor` reports Laya; stale
roadmap text removed; unfinished work kept out of the tree.

### Results at the tagged commit
`make check`: 1599 passed, 1 skipped, coverage 90.5%; ruff, mypy --strict, bandit, vulture, deptry and the layer test
clean. `tsc -b`, `oxlint` and the production build clean. Vulture at 60% confidence and an unused-CSS-class scan found
nothing.

### What was run
Against a stand-in worker (`tests/laya_stub`), never the real model: pre-check with injected host, disk and Python;
the self-test (success, failure, timeout, concurrent call refused); the plan check (a doubted step needs approval; a
decider can never turn ask or deny into allow, tested over every verdict); the reply check (runs after the task is
DONE, records an event, survives a failing decider); the answer cache; CLI `check`, `test` and `doctor` exit codes.
The real `install.sh --no-open` into a temp directory: no Laya download, `lilly laya check` passes. The guided card
and the assist card in headless Chromium (steps follow state, failure help shows, no page errors).

### Not verified
* **The real Laya.** This sandbox cannot reach huggingface.co. The real download, `pip install laya`, loading the
  model, its real answers, its speed, and the pinned file sizes and hashes against real files are all unrun.
* The success path of the self-test in the browser (covered by the API test only), and the Download button in the UI.
* Whether Laya's judgement of plans and replies is any good. Both checks ship as watch-only for that reason.
* Everything still listed under "needs the real thing" for 1.4.0 to 1.6.0.

### Left unfinished on purpose
Lit 3D pets: a WebGL renderer was started and paused. The partial work is not in this release.

## Version 1.6.0 (interface and pets)

### Scope
Design tokens and glass on four floating surfaces; a jump-to palette; page titles with the waiting count; fade-in on
views; customisable pets (look, `skills.md`, one pinned model per pet).

### Results at the tagged commit
`make check`: 1459 passed, 1 skipped, coverage 90.2%; ruff, mypy --strict, bandit, vulture, deptry, layer test clean.
`tsc -b`, `oxlint` clean. Built JS 108 kB gzip (budget 130 kB), CSS inside its 14 kB budget; `test_interface_budget.py`
pins both, pins that blur is used only on `.rail`, `.dialog`, `.toast`, `.savebar`, and that the reduced-transparency
and more-contrast switches exist.

### What was run
Headless Chromium on Linux: sign-in, palette (keyboard filter and choose), light and dark, phone width, creating pets
through the API (valid look accepted, `hue: 999` refused with 400), customizer create/edit/reopen, hue slider by
keyboard, pet tilt variables set and cleared with the pointer. No console errors apart from the deliberate 400.
Backend: look, skills and model validated; an agent's model becomes the task's pin and an explicit pin wins; skills
reach the planner.

### Not verified
* Safari and an Intel Mac: the glass uses `-webkit-backdrop-filter`, never seen on a real Safari. If blur is slow there,
  the solid fallback is one media query away (`prefers-reduced-transparency`).
* Idle CPU and memory of the page. The budget is in size only; nothing was measured.
* The reduced-motion branch, and pets in the chat reply row, were only read.
* "3D" is layered SVG with a CSS tilt, not a 3D engine, by decision.
* A pet pins one model. A range of allowed models is not built.
* `tests/unit/test_doctor.py` failed once in a full run that overlapped with another tool and passed in 12 repeats and
  two more full runs; the cause is unknown.

## Version 1.5.0 (audit, savings, presets, doctor)

### Scope
A full read-only audit of the 1.4.0 code by independent reviewers, with every finding fixed and tested; fewer model tokens
per task; resource presets; `lilly doctor`.

### Results at the tagged commit
`make check`: 1402 passed, 1 skipped, coverage 90.1% (floor 82%), ruff, mypy --strict, bandit, vulture, deptry and the
layer test clean. `tsc -b`, `oxlint` and the web contract test clean.

### Audit findings fixed (each has a regression test)
Chat bridge: no approval buttons on a clipped approval; unpairing forgets the person's running tasks; identity re-checked
before asking and finishing; update offset reset when the bot changes; wrong pairing guesses counted per sender.
Browser and devbox: per-task action budget kept by the manager; folder validated after resolving; split UTF-8 characters
decoded correctly. Engine: state change and reply saved in one transaction; approval expiry committed and the waiter
woken; a step that raises ends as a failed step; scheduler slot reserved before the first await. Stores and runtime:
snapshot integrity checked before old backups rotate out; backup retry after failure; writer drains on close. Providers:
unexpected exceptions become retryable errors; key text must be printable ASCII; counters survive a settings change that
does not touch the model. Laya: a worker that times out is stopped and counts toward giving up. Found while writing
doctor: a damaged database file left a read connection open.
Interface: throttled refresh, resync after the event stream drops, sign-in probe with backoff, dialog focus trap, no
polling in hidden views, and several smaller fixes.

### Savings (what was measured and what was not)
Measured: the planner prompt now starts with the part that never changes (rules, tools), which is what a provider's
prompt cache can reuse; a test pins the order. Small `llm.work` steps (3000 characters or less) go to a model marked
"quick" first. Per-model call and token counters show in Resources.
Not measured: real savings in dollars or in free-tier quota. That needs real provider keys and real tasks.

### Presets
Low-resource, balanced, fast, careful. A property test proves a preset changes only limits, idle times and box size,
never modules, folders, agents, chat apps or allowed hosts, and can only tighten the browser's approval mode.

### What needs the real thing
Docker or Podman (devbox on a real engine), Telegram, the Laya download on an Intel Mac, the Watch-browser click-through,
macOS and Windows. Unchanged since 1.4.0; nothing in this version was run on those.

## Milestones 4, 5 and 6 (version 1.4.0)

### Scope
* **M4 (interface and sync, partly):** streaming replies; the plan shown in the step list; Laya as a service
  (install, switch on and off, remove, from Settings, taking effect without a restart); the Quick decisions screen;
  Intel Mac handling for the Laya install (older Python and pins, refusal before any download); a contract test that
  fails when the interface and the server disagree.
* **M5 (chat and watching):** Telegram bridge (pairing, allowlist, rate limit, tainted tasks, approval buttons,
  at-most-once polling), its API and the Chat apps screen; read-only live view of the agent's browser tab.
* **M6 (devbox, without extensions):** sealed container behind an engine interface; settings and API; Devbox screen;
  `devbox.run` with streamed output; idle stop, destroy, warm start; Stop all and shutdown.
* **Resources:** Ollama keep-alive setting, one local call at a time, one local model in memory, a scheduler that
  sleeps until the next routine is due.

### Results at the tagged commit
ruff, `mypy --strict`, bandit, vulture, deptry and the import-boundary test clean; `tsc -b` and `oxlint` clean;
`pytest -W error`: 1352 passed, 1 skipped; coverage 89.7% (floor 82%). New tests: devbox rules (38 cases), devbox
manager and tool against a fake engine (lifecycle, limits, idle clean-up, timeout, cancel, Stop all, warm start, a
shared folder that contains something private), the engine adapter against a stand-in `docker` script (real
subprocesses: output streaming, runaway output, timeout and process-group kill), Telegram against a fake server (18),
the bridge and live-view APIs, local-model gate, scheduler sleep and wake, and the interface contract. The live-view
picture was taken from a real Chromium. The new screens (Chat apps, Devbox, Resources) were opened in a real Chromium
at desktop and phone width against a running server; a bad bot token was refused with a plain message.

### Flaws found by reading and testing the author's own code, and fixed
A shared folder that merely contained Lilly's data or the user's keys was accepted; a cancelled devbox command kept
running inside the container; Stop all waited for a running command; a database error could end the housekeeping loop;
a killed engine command could leave its children and an unclosed pipe; a Laya idle-unload test raced its own timer;
the interface lacked the new settings (caught by the contract test).

### Independent review: NOT DONE
Skipped by the owner's decision, as for M2 and M3.

### What needs the real thing
| Area | Status |
| --- | --- |
| Devbox on a real Docker or Podman | **Not run.** No container daemon in the build environment. The arguments, the engine adapter and the lifecycle are tested against fakes. Needs one manual run: download the image, run a command, confirm there is no network and that only the shared folder is visible |
| Telegram | **Not run against Telegram.** Tested against a fake server; message and button limits are from memory |
| Laya model download and Intel Mac run | **Not run.** Hugging Face is unreachable from the build machine; the real install is the check |
| Live view in the interface | The picture endpoint is tested with a real browser; the Watch button was built and linted, not clicked through during a real browser task |
| Mac and Windows | Not run. Devbox is offered on Mac and Linux paths only |
| Not built | Agent-built extensions, playbooks, model-per-step routing, reply checks, read cache, key failover, an eval set, presets, `lilly doctor`, take-over, desktop and phone screen view, 3D pets, design tokens and glass surfaces, interface budgets |

## Milestone 3 (version 1.3.0)

### Scope
Agent browser: a Chrome-family browser driven over its debugging protocol in a throwaway profile; numbered page targets
with stale-snapshot and changed-element refusal; eleven `browser.*` tools; three approval modes (ask every time, ask for
risky things, trusted sites only) applied on the exact target; per-request network guard; action budget; idle quit; Stop
all closes it; Settings card. A shortlist that hid a needed tool now falls back to the full catalog (found while testing).

### Results at the tagged commit
All gates clean (ruff, mypy --strict, bandit, vulture, deptry, import boundaries); `pytest -W error`: 1172 passed,
1 skipped; coverage 89.2%; the browser tests were run three times in a row with the same result. The browser tests drive a
real Chromium 141 against a local test site: forms, selects, stale and shifted targets, injected text, pop-ups, dialogs,
downloads, budget, two tasks, idle quit, crash recovery, and the mode matrix on real targets; engine tests check
approvals per mode, that a password can never be typed, and that a page taints the task. The pop-up handling was
mutation-checked.

### Independent review: NOT DONE
Skipped by the owner's decision, as for M2.

### What needs the real thing
| Area | Status |
| --- | --- |
| Chrome, Edge, Brave, Chromium on a Mac or Windows | Not run. Only Linux Chromium was driven. The launch flags and the Keychain flag are from knowledge of Chrome, not tested |
| Real websites | Not tested: consent banners, shadow DOM, iframes (only the main frame is read), canvas apps, very large pages (150 elements, 8000 characters kept) |
| Network guard | Checked per request before it leaves; a DNS answer that changes in between is not stopped (documented) |
| Take-over, live view, saved sign-ins | Not built (planned with M5) |

## Milestone 2 (version 1.2.0)

### Scope
Quick deciders (tool shortlist, loop stop, instructions-in-data taint, pick-one) with a bounded log and calibration;
lane executor (read-only steps side by side under a worst-case policy rule) and the runner split; the `lanes` limit;
optional Laya add-on (pinned install, isolated worker, decider).

### Results at the tagged commit
ruff, `mypy --strict`, bandit, vulture, deptry and the import-boundary test are clean; `pytest -W error`: 1112 passed,
1 skipped; coverage 89.2% (floor 82%). The lane tests include a seeded 400-case property test (no non-ALLOW step ever
overlaps another; verdicts and final context equal a sequential run), mutation-checked.

### Independent review: NOT DONE
The owner chose to skip the independent review for this milestone. Only the author's own tests and gates were run, so
"done" here means gates pass, not "reviewed". Bugs found by those tests and fixed: the orchestrator dropped the decision
pipeline for every task; the Laya worker would have imported its neighbour `laya.py` instead of the real package; the
UI resource editor reset `lanes` on save.

### What needs the real thing
| Area | Status |
| --- | --- |
| Laya install, model load and answers | **Not verified.** No access to Hugging Face from the build machine; the pins were read from the listing, not from a download. Tested only against a stub `laya` package and a fake downloader. May not install on Intel Macs (no PyTorch wheel) |
| Small-model decider | Tested only with a scripted model |
| Lanes with real tools | Tested with fake tools that sleep; the rule that no tool result exceeds its ToolSpec label was checked by reading, not enforced by a test |
| Web UI | Lanes control built and type-checked; not driven in a browser this milestone |

## Milestone 0 and 1 (version 1.1.0)

### Scope

* M0, baseline and hygiene: dead code removed, dead-code and dependency gates added, coverage floor, schema upgrade
  rewritten (a copy of the database is saved before an upgrade; a failing migration rolls back), and bugs found by
  new tests fixed (below).
* M1, connections: MCP servers (add, review tools, approve per tool, start on demand, stop when idle), Ollama
  streaming with plain-words diagnosis and its own proxy-free client, rule that a `local` model must be Ollama on this
  computer or a private network, OpenAI API-key provider, and the Connections screen.

### Results at the tagged commit

| Gate | Result |
| --- | --- |
| `ruff check` | clean |
| `mypy --strict` (97 source files) | clean |
| `bandit` | clean |
| `vulture`, `deptry` | clean |
| import boundaries | pass |
| `pytest -W error` | 789 passed, 1 skipped (a permission test that cannot run as root) |
| coverage | 85.3% (floor 82%) |
| stability | full suite run three times in a row, same result |
| interface | `tsc -b` and `oxlint` clean; built into `src/lilly/web` |

### Bugs found and fixed (each has a regression test)

Found by the new tests: shared-folder deny list bypassed by `fs.search` and `fs.apply_moves`; `fs.list` truncation
flag; web fetch of bracketed IPv6 hosts, raw exceptions leaking from fetches, non-JSON search answers; queued
database writes left hanging when the writer stopped; duplicate memories under a race; blank CSV lines miscounted.

Found by the independent review of M0 and M1 (none rated high):

1. A failing MCP tool call did not taint the task, and the server's error text reached the replanning prompt as
   trusted text. Now it taints, and replan text is fenced as data (a closing tag inside it is defused).
2. Two overlapping reloads of MCP settings could bring a revoked approval back. Reload and configure are serialized.
3. A `local` model's address check accepted some non-private addresses (6to4, Teredo, `0.0.0.0`, link-local). It now
   accepts only loopback, RFC 1918, Tailscale 100.64/10 and IPv6 `::1` / `fc00::/7`.
4. Ollama's size cap only applied once a full line had arrived. It now counts bytes as they arrive.
5. The restart counter of an MCP server never reset, so occasional crashes eventually marked it failed. It resets after
   a successful call.
6. A secret could be typed as a plain MCP setting and then be shown by the API. Names that look like secrets are refused.
7. Name patterns accepted a trailing newline. They use whole-string matching now.

Also from the review: a settings file that no longer validates is kept as `settings.json.invalid` instead of being
overwritten by the defaults at the next save.

### What was tested, what was only read, what needs the real thing

| Area | Tested by running | Only read, or tested against a fake | Needs a real device or service |
| --- | --- | --- | --- |
| MCP client, manager, process handling | 125 tests, most against a real stdio server (`tests/fake_mcp_server.py`) including crashes, hangs, oversize output, tool-list change after approval, process-group kill, idle stop | | A real third-party MCP server (for example a filesystem or GitHub server) |
| MCP API and engine | End to end through the web API with a real runtime: add, review, approve, task that uses an approved tool, approvals, labels, secrets reach only the server's environment | | |
| Ollama | Streaming, partial lines, early end, missing model, not running, oversize, diagnosis messages, all against a faked HTTP server | | A real Ollama (cold model load time, real error texts) |
| OpenAI | Request shape (token field, temperature rules, JSON mode, missing key) against a faked HTTP server | The default model id `gpt-4o-mini` and the rule for models that think first (`o*`, `gpt-5*`) come from the author's knowledge of the API | A real key: the first real call is the check. Change the model id in Settings if it is retired |
| Interface | Connections and Ollama screens driven in headless Chromium (add, secret, review, approve, diagnosis); no console errors | Layout on a phone | |
| Operating systems | Linux only | Windows and macOS code paths (process-group handling, Keychain, launchd) | A Mac and a Windows machine |
| Upgrade | Migration tests, pre-upgrade copy, rollback of a failing migration | | An upgrade of a real 1.0 database with real data |

### Known limits (not bugs, by decision)

* An MCP server runs as you with no sandbox. Lilly controls what it is told and what it may use, not what the program
  does. Documented in `docs/SECURITY.md`.
* A private-network model is only as private as that network.
* More than 64 tools, or more than 8 pages of tools, from one server makes its listing fail.
* Coverage is lower in `ui/api_chat.py` (56%), `ui/api_data.py` (70%) and `tools/computer.py` (71%); these are covered by
  the end-to-end API tests for their main paths but not for every error branch.
