# Roadmap

What Lilly does today, what comes next, and what is left out on purpose. Written after comparing Lilly with a
larger feature list (an "agent OS" with scheduler, connectors, sandbox and workspace). Each item was judged on three
questions: does it help one person on one laptop, can it be made safe, and can it be verified before it ships.

## Already in Lilly

Chat with steps shown · approvals bound to the exact action · tamper-evident activity log · notes (spaces and pages) ·
searchable memory · team of agents with pets · model list with automatic fallback and per-model quotas ·
computer control that always asks · live Resources screen with limits · backup, export, kill switch · MCP connections (reviewed, pinned, started on demand) · Ollama on this computer or a private network with plain-words diagnosis · OpenAI API key · quick deciders (tool shortlist, loop stop, instructions-in-data flag, pick-one) with a log and calibration · read-only steps side by side · optional Laya model · agent browser (your installed Chrome, separate empty profile, three approval modes) · streaming replies and the plan in the step list · Telegram chat with pairing and approval buttons · read-only live view of the agent's browser · devbox (sealed container, on demand, idle stop) · local-model resource rules · settings presets and `lilly doctor` · customisable pets (look, skills file, own model) · jump-to palette (Ctrl/Cmd+K) · glass surfaces with solid fallback · routines (scheduled requests) · Laya guided setup, self-test and the optional *Laya assist* checks on plans and replies (`docs/LAYA.md`).

## Next (needs design, not just code)

| Item | Why it waits |
| --- | --- |
| Browser take-over (you type a password in the agent's browser) | Needs a visible window and a hand-back protocol. |
| Agent-built extensions (manifest, protected paths, install, test, enable, roll back) | Lets an agent change Lilly itself; needs the devbox verified on a real engine first. |
| Learned playbooks, model-per-step routing, read cache, failover across keys, an eval set | The planned token and free-limit savings. Nothing is measured yet. |
| Desktop and phone screen view | Needs OS screen capture that cannot be tested on Linux, and a safe way to reach Lilly from a phone. |
| Pets: lit 3D models that move and react, and a range of allowed models per pet (today one pinned model) | Started and paused: a small WebGL renderer is the plan, with a still fallback and a frame-time guard for the 2019 Mac. Today's pets are layered SVG with a CSS tilt. |
| Desktop notification when an approval or routine needs you | Small, but the macOS path must be tested on a Mac first. |
| Email and WhatsApp as chat apps | Telegram is built with the taint rules and sender allowlist; the others reuse them but each needs its own verified API and signature checks. |
| Signed inbound webhook | Same trust question as above; a shared secret and replay protection are required. |
| Memory tags | Useful at scale; low risk. |

## Left out on purpose

| Item | Reason |
| --- | --- |
| Switches that turn security rules off | The approval floor and secret handling are not preferences. A posture score over switches that can be flipped invites the exact mistake the rules prevent. Tune freedom per agent instead. |
| Passkeys, OAuth, push for remote access | Lilly listens on this computer only. Exposing it to the internet is not a supported setup, so the login machinery would add attack surface for no supported use. |
| A bundled container engine | The devbox uses Docker or Podman if you already have one; Lilly does not install one. |
| Voice, rich block editor | Large surfaces that do not make the assistant more capable or safer. |
| "Better than X" tables and test-count slogans | Not verifiable from this codebase. Lilly states what was tested and what was not, in `docs/SETUP.md`. |
