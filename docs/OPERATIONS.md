# Operations

## Where things are

| Path | Contents |
| --- | --- |
| `~/.lilly/lilly.db` | All data (SQLite, WAL mode) |
| `~/.lilly/config/settings.json` | Settings (no secrets) |
| `~/.lilly/config/access-token`, `secret.key` | Sign-in token; cookie-signing secret (both 0600) |
| `~/.lilly/config/keys.json` | API keys, only if no system keychain exists (0600) |
| `~/.lilly/addons/laya/` | The optional Laya add-on, absent unless you set it up: its own Python environment and the model; `lilly laya remove` deletes it (see [LAYA.md](LAYA.md)) |
| `~/.lilly/backups/` | Daily backups, newest 7 |
| `~/.lilly/log/` | `lilly.out.log` (started by `lilly open`), `service.*.log` (started at login) |
| `~/.local/share/lilly-app` | The installed program (replaceable) |

Set `LILLY_HOME` to move the data folder and `LILLY_PORT` to change the port.

## Housekeeping (automatic while Lilly runs)

* Every hour: finished tasks older than the retention period (default 90 days) are removed; a one-line summary that still commits to the end of the event chain remains.
* Daily: an online backup with integrity check, keeping the newest 7.
* Tasks that were running when Lilly stopped are marked failed ("interrupted by a restart") and never resumed automatically.

## Restore from a backup

```bash
lilly stop
cp ~/.lilly/backups/lilly-<timestamp>.db ~/.lilly/lilly.db
rm -f ~/.lilly/lilly.db-wal ~/.lilly/lilly.db-shm
lilly open
```

## Upgrade

Unzip the new version and run `./install.sh` again. Data and settings are kept; database migrations run on start and refuse to run on a database from a newer version. Before an upgrade changes the database, a copy is saved as `~/.lilly/backups/preupgrade-<time>-v<old version>.db` (the newest three are kept). A settings file that the new version cannot use is replaced by the defaults, and the old one is kept as `settings.json.invalid` next to it; the reasons are shown in Settings.

## Health

`GET /healthz` returns `{"ok": true, "app": "lilly", "version": ...}` without needing to sign in. Settings → About shows live model quota and breaker state, power state and the last backup.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
make install   # editable install with dev tools
make check     # ruff + mypy --strict + bandit + vulture + deptry + pytest with a coverage floor
make web       # rebuild src/lilly/web from web/ (Node 20+)
cd web && npm run dev   # interface with hot reload, proxying the API on :8787
```

Tests need no network and no real models: the integration suite builds a real `Runtime` against a stand-in model served through `httpx.MockTransport`.

## Quick deciders and Laya

* `lilly decisions report` shows, per question and decider, how often it answered and how often it was right (outcomes you mark through `POST /api/decisions/<id>/outcome`). `lilly decisions calibrate` suggests a minimum confidence from that log and changes nothing.
* Settings → the `decisions` section of `settings.json` holds the master switch, per-question chains, thresholds, time limits, shadow mode (log what a chain would have answered without acting) and per-task caps. An invalid section makes the settings invalid, and the defaults are used until it is fixed.
* Laya, the helper model that saves tokens, has its own guide: **[LAYA.md](LAYA.md)** (pre-check with `lilly laya check`, proof with `lilly laya test`, setup, judging it with `lilly decisions report`, the optional assist checks, troubleshooting).
* Free-tier limits: enter each model's per-minute and per-day limits from its provider's console (Settings → Models & keys → Edit). If you leave them blank, Lilly learns them from the provider's own refusals and offers "Limit it to N per minute?" on the model; nothing is applied until you click it. A model that has just refused for rate is not asked again until the wait it was given is over.
* Steps that only read run up to *Steps at once in one task* (the Resources screen, default 3) side by side; set it to 1 for strictly one at a time.

## Browser

* Switch on *Browser* under Settings → Privacy & access, then choose how much it may do without asking. It needs Chrome, Chromium, Edge or Brave installed (or set `browser.chrome_path` / `$LILLY_CHROME`). Nothing large is downloaded.
* Agents need *research* access to use it. Tools: `browser.open`, `read`, `find`, `click`, `type`, `select`, `press`, `submit`, `scroll`, `back`, `close`. A plan finds an element first and passes the line it returns to the next step, because pages are only known at run time.
* The browser starts when a task first needs it and quits after `browser.idle_quit_s` unused (default 300 s). *Stop all* closes it immediately.

## Chat apps (Telegram)

* Make a bot with @BotFather, then Settings → Chat apps → paste the token, press *Link a Telegram account*, and send the 8-character code to the bot in a private chat within 10 minutes. Mark an agent *Reachable from chat apps* (Team) and choose it under *Agent that answers*, then switch on *Answer messages*.
* Messages from chat are treated as outside text. Approvals appear with the exact action and Approve / Decline buttons; computer-control approvals stay in the app. Answers that used private data stay in the app unless *Send private answers to chat* is on.
* To stop: switch it off, unlink an account, or remove the bot (the token is forgotten).

## Devbox

* Install Docker or Podman yourself. Settings → Devbox: choose a shared folder (inside a folder you shared with Lilly, made for this purpose), press *Download image* once, switch the *Devbox* module on under General, and allow *files* for the agent.
* Tool: `devbox.run` (one shell command, optional folder inside the shared folder). Output streams as it is written. The box has no network, so packages cannot be installed from inside it; use an image that has what you need.
* It starts when a plan includes a devbox step, sleeps after `idle_stop_s` (default 600), is removed after `destroy_after_s` (default 86400), and is removed on a timeout, a cancel, *Stop all* and shutdown. *Reset box* removes it now. Files in the shared folder stay.

## Resource settings

* The Resources screen → *Keep a local model loaded* (default 300 s; 0 unloads after each answer). Local model calls take turns, and switching models unloads the previous one.
* Housekeeping sleeps until the next routine is due (at most 60 s when idle).
* The Resources screen → *Presets*: low-resource, balanced, fast, careful. They change only limits and idle times, never what Lilly may touch.

## Doctor

`lilly doctor` checks Python, the data folder's permissions, free disk, the database, settings, the folders you shared and the container engine (when the devbox is on). It changes nothing and exits 1 when something needs fixing.

## Interface

* **Ctrl/Cmd+K** opens *Jump to*: views, recent conversations, new chat, theme, stop all.
* The tab title shows where you are and how many approvals wait.
* Blur ("glass") is on four floating surfaces only. It switches itself off when the system asks for reduced transparency or more contrast.
* Team → a pet: species, colour, accessory, eyes, an optional **skills.md** (added to every task of that pet, so it costs tokens) and an optional model the pet always uses (a task fails clearly if that model is unavailable).
