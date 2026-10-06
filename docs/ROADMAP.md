# Roadmap

What Lilly does today, what comes next, and what is left out on purpose. Written after comparing Lilly with a
larger feature list (an "agent OS" with scheduler, connectors, sandbox and workspace). Each item was judged on three
questions: does it help one person on one laptop, can it be made safe, and can it be verified before it ships.

## Already in Lilly

Persistent task workspace · approvals bound to the exact action · tamper-evident activity log · notes (spaces and pages) ·
searchable memory · agents with pets as personality state · ModelBroker fallback and per-model quotas · persistent
ComputerRuntime with screenshots, AX/DOM, pointer, keyboard, scroll, drag and stale-frame verification · live Resources
screen with limits · backup, export, kill switch · MCP connections (reviewed, pinned, started on demand) · Ollama on
this computer or a private network with plain-words diagnosis · OpenAI API key · typed Laya System-1 routing and
verification · policy-filtered capability namespaces with lazy discovery · optional Laya model · agent browser (your
installed Chrome, separate empty profile, approval modes) · streaming task activity · Telegram chat with pairing and
approval buttons · integrated live browser/computer view · persistent sealed DevBox · local-model resource rules ·
settings presets and `lilly doctor` · customisable pets (look, skills file, own model) · jump-to palette (Ctrl/Cmd+K) ·
routines (scheduled requests) · resumable first-run wizard.

## Next (needs design, not just code)

| Item | Why it waits |
| --- | --- |
| Browser take-over (you type a password in the agent's browser) | Needs a visible window and a hand-back protocol. |
| Agent-built extensions (manifest, protected paths, install, test, enable, roll back) | Lets an agent change Lilly itself; needs the devbox verified on a real engine first. |
| Learned playbooks, trajectory-aware routing, failover across keys, an eval set | Per-turn capability and health routing exists; these learning and multi-credential policies need measurements before they can safely change selection. |
| Desktop hand-back/take-over flow | Needs a visible hand-back protocol so Lilly can pause while the owner enters sensitive information. |
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
