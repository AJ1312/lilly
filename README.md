# Lilly

A private AI assistant that runs on your own computer. Give Lilly a job and it plans, acts, verifies the result, and keeps you posted in a persistent task workspace. It can research, work with files, remember facts, use a browser or computer, run isolated DevBox commands and run routines within the permissions you set.

Lilly is free to run: it uses the free tiers of Mistral, OpenRouter and Gemini (in the order you choose) and, optionally, a local Ollama model that keeps everything on your machine.

## Install (one click)

* **Mac:** double-click **`Install Lilly.command`**. If macOS objects, right-click → Open once.
* **Mac or Linux, from a terminal:** `./install.sh` (add `--login-item` on a Mac to start Lilly when you log in).

Needs Python 3.12 or newer and an internet connection for the install. Then run `lilly open`; the full walk-through, including adding a free API key, is in **[docs/SETUP.md](docs/SETUP.md)**.

**Laya**, a small helper model that saves tokens on quick decisions, is set up by the installer (skip it with `--no-laya`; Lilly works fully without it). Setup can also be done or redone in Settings → Quick decisions, and **[docs/LAYA.md](docs/LAYA.md)** explains what it is and is not.

## What you get

| Screen | What it is for |
| --- | --- |
| Sessions | Persistent task workspace with live progress, approvals, computer/browser state, results and artifacts. |
| Approvals | Every file change or sensitive action waits here for a yes or no, bound to exactly what will happen. |
| Activity | A tamper-evident log of everything Lilly did, with verification. |
| Notes, Memory | Your notes, and short facts Lilly remembers (editable, deletable, clearable). Agents can propose a note; it is saved only after you have read it and approved. |
| Routines | Requests that run on a schedule (daily at a time, chosen weekdays, or every few minutes or hours) while Lilly is running. Pause, run now, see the last result. Stop all pauses every routine. |
| Agents | Different personality and permission profiles. Pets are visual state only; they never create separate brains or sessions. |
| Resources | Live processor, memory and disk, the heaviest programs, work in progress (with Stop), and limits you can change while Lilly runs: tasks at once, longest step, longest task. |
| Settings | Models and keys, shared folders, modules, privacy, security, backup and export. Light, dark or system theme. |

## Controlling your computer

Turn on **Settings → Privacy & access → Computer control**, then allow it per agent in **Agents**. Lilly can observe screenshots and accessibility state, move/click/type/scroll/drag, open apps and links, and verify fresh state after actions. Grounding uses semantic accessibility/DOM targets first, vision when configured, and coordinates only as a fallback. macOS Screen Recording and Accessibility permissions are required.

`MANUAL` asks for approval, `AUTO` runs ordinary safe actions directly, and `OFF` suppresses prompts. None of these modes bypasses hard policy denials, permissions, sandboxing or auditing.

## Talking to it from Telegram, running code safely, watching the browser

* **Settings → Chat apps:** paste a Telegram bot token, link your account with a one-time code, and mark which agent may answer. Nothing connects in to your computer; only linked accounts are answered.
* **Settings → Devbox:** needs Docker or Podman. Agents you allow can run commands in a sealed container with no network that sees only one folder you share. It starts when needed and sleeps when idle.
* A running task shows an integrated browser/computer preview only when Lilly is using one.

## How it stays safe

A model only *proposes* a plan. A small deterministic policy (`domain/policy.py`) decides what runs, using fixed risk levels from a code-defined tool registry. Lilly listens on `127.0.0.1` only, signs you in with a private access token, protects every request with a session cookie, CSRF token and origin check, keeps API keys in the system keychain, and never lets a model see private data without your permission. Details and limits: **[docs/SECURITY.md](docs/SECURITY.md)**.

## Documents

* [docs/SETUP.md](docs/SETUP.md): installation, setup wizard, keys, folders, phone access, backups, troubleshooting, uninstall
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): layers, request flow, data
* [docs/SECURITY.md](docs/SECURITY.md): threat model, controls, honest limits
* [docs/ROADMAP.md](docs/ROADMAP.md): what is next, and what is left out on purpose
* [docs/OPERATIONS.md](docs/OPERATIONS.md): files, logs, backups, upgrades, development commands
* [docs/VERIFICATION.md](docs/VERIFICATION.md): automated gates and real-machine limits

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
make install        # Lilly plus dev tools
make check          # ruff, mypy --strict, bandit, pytest
make web            # rebuild the interface (Node 20+); the built files ship in src/lilly/web
```
