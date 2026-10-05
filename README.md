# Lilly

A private AI assistant that runs on your own computer. You talk to it in your browser; it can search the web, read and organise files in folders you choose, remember facts about you, keep notes and run ready-made routines. It never does anything outside the permissions you set, and anything that changes your files or leaves your computer waits for your approval.

Lilly is free to run: it uses the free tiers of Mistral, OpenRouter and Gemini (in the order you choose) and, optionally, a local Ollama model that keeps everything on your machine.

## Install (one click)

* **Mac:** double-click **`Install Lilly.command`**. If macOS objects, right-click → Open once.
* **Mac or Linux, from a terminal:** `./install.sh` (add `--login-item` on a Mac to start Lilly when you log in).

Needs Python 3.12 or newer and an internet connection for the install. Then run `lilly open`; the full walk-through, including adding a free API key, is in **[docs/SETUP.md](docs/SETUP.md)**.

**Laya**, a small helper model that saves tokens on quick decisions, is set up by the installer (skip it with `--no-laya`; Lilly works fully without it). Setup can also be done or redone in Settings → Quick decisions, and **[docs/LAYA.md](docs/LAYA.md)** explains what it is and is not.

## What you get

| Screen | What it is for |
| --- | --- |
| Talk | Chat. Each answer shows the steps taken and which model wrote it. |
| Approvals | Every file change or sensitive action waits here for a yes or no, bound to exactly what will happen. |
| Activity | A tamper-evident log of everything Lilly did, with verification. |
| Notes, Memory | Your notes, and short facts Lilly remembers (editable, deletable, clearable). Agents can propose a note; it is saved only after you have read it and approved. |
| Routines | Requests that run on a schedule (daily at a time, chosen weekdays, or every few minutes or hours) while Lilly is running. Pause, run now, see the last result. Stop all pauses every routine. |
| Team | Different assistants, each with its own pet, instructions, access level (Locked / Ask / Open) and a separate switch for controlling this computer. The pet shows what the agent is doing. |
| Resources | Live processor, memory and disk, the heaviest programs, work in progress (with Stop), and limits you can change while Lilly runs: tasks at once, longest step, longest task. |
| Settings | Models and keys, shared folders, modules, privacy, security, backup and export. Light, dark or system theme. |

## Controlling your computer

Turn on **Settings → Privacy & access → Computer control**, then allow it per agent in **Team**. Lilly can then open a link or app, list and stop your programs, show a notification, and run a command in a folder you shared. **Every one of these asks you first, in every mode, including Open.** Commands run without a shell, with a cleaned environment, a time limit and capped output; `sudo`, shutdown, disk tools and similar are refused outright.

Not included yet: clicking on your own screen, and a phone or desktop screen view.

## Talking to it from Telegram, running code safely, watching the browser

* **Settings → Chat apps:** paste a Telegram bot token, link your account with a one-time code, and mark which agent may answer. Nothing connects in to your computer; only linked accounts are answered.
* **Settings → Devbox:** needs Docker or Podman. Agents you allow can run commands in a sealed container with no network that sees only one folder you share. It starts when needed and sleeps when idle.
* **Watch browser** on a running task shows a read-only picture of the agent's browser tab.

## How it stays safe

A model only *proposes* a plan. A small deterministic policy (`domain/policy.py`) decides what runs, using fixed risk levels from a code-defined tool registry. Lilly listens on `127.0.0.1` only, signs you in with a private access token, protects every request with a session cookie, CSRF token and origin check, keeps API keys in the system keychain, and never lets a model see private data without your permission. Details and limits: **[docs/SECURITY.md](docs/SECURITY.md)**.

## Documents

* [docs/SETUP.md](docs/SETUP.md): installation, first run, keys, folders, phone access, backups, troubleshooting, uninstall
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): layers, request flow, data
* [docs/SECURITY.md](docs/SECURITY.md): threat model, controls, honest limits
* [docs/ROADMAP.md](docs/ROADMAP.md): what is next, and what is left out on purpose
* [docs/OPERATIONS.md](docs/OPERATIONS.md): files, logs, backups, upgrades, development commands

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
make install        # Lilly plus dev tools
make check          # ruff, mypy --strict, bandit, pytest
make web            # rebuild the interface (Node 20+); the built files ship in src/lilly/web
```
