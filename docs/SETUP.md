# Setting up Lilly

## 1. Requirements

* macOS 12+ or Linux. (Lilly is developed and tested on Linux; see "What has and has not been verified" below for the Mac-specific parts.)
* Python 3.12 or newer. Check with `python3 --version`. Get it from <https://www.python.org/downloads/> or `brew install python`.
* An internet connection for the install and for the models and web search you choose to use.
* A modern browser.

## 2. Install

**One click (Mac):** double-click `Install Lilly.command` in this folder. If macOS says it is from an unidentified developer, right-click it and choose Open.

**Terminal (Mac or Linux):**

```bash
./install.sh                # install or update
./install.sh --login-item   # Mac: also start Lilly automatically when you log in
./install.sh --no-laya      # skip Laya, the helper model that saves tokens (download of about 850 MB; see docs/LAYA.md)
```

The installer creates a private Python environment in `~/.local/share/lilly-app`, installs Lilly and its dependencies there, adds the `lilly` command to `~/.local/bin` (it tells you if that folder is not on your PATH), and on a Mac adds **Lilly.app** to `~/Applications`. It never uses `sudo`.

## 3. First run

```bash
lilly open
```

This starts Lilly in the background if it is not already running, then opens your browser already signed in. Lilly runs only on your own computer at `http://127.0.0.1:8787` (change with `--port` or `LILLY_PORT`). On a Mac you can also open **Lilly.app**.

The first launch wizard is resumable. It walks through Welcome, pet identity,
models/providers, Laya, local model, permissions, browser/computer, DevBox,
approval mode, notifications, health check and Ready. You can skip it and
resume from the setup prompt later; changing the pet never resets tasks,
sessions or memory.

If the browser did not open, go to `http://127.0.0.1:8787`, run `lilly token` in a terminal and paste the token into the sign-in box.

## 4. Add a model (required, free)

Lilly has no built-in intelligence; it uses models you connect. Open **Settings → Models & keys**. Three free options are preconfigured, in this priority order; add a key for at least one:

| Model | Where to get a free key |
| --- | --- |
| Mistral Small | <https://console.mistral.ai> → API keys |
| OpenRouter (free router) | <https://openrouter.ai/settings/keys> |
| Gemini Flash | <https://aistudio.google.com/apikey> |

Press **Key** on that model's row, paste the key and press **Save key**. It goes into the macOS Keychain (or a private `0600` file if no keychain exists; the screen tells you which). Press **Save** at the bottom to keep any other changes, then **Test** to check the model answers. Free tiers have rate limits, so enter your own per-minute and per-day limits from the provider's console and Lilly will route around a model that is used up. Use the up and down arrows on each row to change the order.

**Fully offline option:** install [Ollama](https://ollama.com), run `ollama pull llama3.2`, then enable the `ollama-local` row. A local model can be given standing access to private data; remote models never get that without your permission.

## Laya (installed by default)

Laya is a small helper model that saves tokens on quick decisions. `install.sh` sets it up after a check and a test; if that fails, Lilly still works and you can retry in Settings → Quick decisions → Laya, or skip it with `--no-laya`. Read **[LAYA.md](LAYA.md)**.

## 5. Share folders (optional)

Lilly cannot see any file until you share a folder. In **Settings → Privacy & access**, add a folder (for example `~/Documents/Taxes`, not your whole home folder or `/`). You can turn the Files, Web, Memory, Notes and Skills modules on or off in the same place. Changes apply when you press **Save**.

## 6. Use it

* Create a task in **Sessions**. Try *"Research the best way to back up a laptop"* or *"Summarise ~/Documents/Taxes/notes.txt"*.
* Anything that changes files or sends private data appears in **Approvals**. Read it, then approve or decline. Approvals are single-use and expire after 15 minutes.
* **Stop all** (top right) cancels everything that is running.
* **Agents** lets you create pets with their own instructions and an access level: *Locked* (no private data), *Ask* (asks first, the default) or *Open* (fewer prompts; the safety floor still applies).

## 7. Use it from your phone (optional)

Lilly never listens on your network. To reach it from your phone safely, use [Tailscale](https://tailscale.com):

1. Install Tailscale on the computer and the phone and sign in to both.
2. On the computer: `tailscale serve --bg 8787`. Note the `https://<name>.<tailnet>.ts.net` address it prints.
3. In Lilly, **Settings → Security → Allowed hosts**, add `<name>.<tailnet>.ts.net` and save.
4. On the phone open that address and sign in with your access token (`lilly token`).

Do not use Tailscale Funnel or any other public tunnel.

## 8. Back up and export

**Settings → Your data** has **Back up now** (backups also happen automatically once a day while Lilly runs; the newest 7 are kept in `~/.lilly/backups`), **Clean up old tasks now** (the number of days to keep is set on the same screen; 0 keeps everything) and **Download everything** (one JSON export). Memory can be cleared from the Memory screen.

## 9. Everyday commands

```bash
lilly open               # start if needed and open the browser
lilly status             # is it running?
lilly stop               # stop it
lilly token              # show the access token
lilly install-service    # Mac: start at login        (lilly uninstall-service removes it)
```

## 10. Uninstall

```bash
./uninstall.sh                 # removes the program, keeps your data in ~/.lilly
./uninstall.sh --purge-data    # removes the data too
```

API keys saved in the macOS Keychain stay until you delete the `lilly` items in Keychain Access.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `Python 3.12 or newer is required` | Install a newer Python (see Requirements) and run the installer again. |
| `lilly: command not found` | Add `~/.local/bin` to your PATH: `export PATH="$HOME/.local/bin:$PATH"` in `~/.zshrc`. |
| "cannot listen on port 8787" | Something else uses the port (some developer tools default to 8787). Find it with `lsof -nP -iTCP:8787 -sTCP:LISTEN`, or use another port: `lilly --port 8790 open` (or set `LILLY_PORT`). |
| `pip` fails with an SSL or certificate error during install | Your network is intercepting or blocking PyPI (office or school networks, VPNs). Try another network, then run `./install.sh` again. |
| "no model may see this data" | The task touched private data and no model is allowed to see it. Enable a local model or allow a remote one to ask in Settings → Models & keys. |
| Model says quota or "unavailable" | Check the key with **Test**, and the rate limits you entered. Lilly tries the next model in your list. |
| Signed out / lost the token | `lilly token` prints it. **Settings → Security** can replace it and sign out every browser. |
| Lilly will not start | Read `~/.lilly/log/lilly.out.log` (and `service.err.log` if started at login). Lilly refuses to run if `~/.lilly` is writable by other users: `chmod 700 ~/.lilly`. |
| Web search returns nothing | DuckDuckGo may be rate limiting you. Choose Brave (add its key under Models & keys) or your own SearXNG in Settings → Privacy & access → Web search. |

## What has and has not been verified

Verified in development: the automated Python and frontend gates, release wheel, policy and security behavior, browser/CDP adapters, deterministic ComputerRuntime contract, DevBox fake engine, restart/re-drive, model fallback, Laya routing and API flows. See `docs/VERIFICATION.md` for the exact gate and the real-machine checks that still require your Mac, browser, provider keys or container engine.

**Not verified here, so treat as untested until you try them:** the Mac-specific parts (launchd login item, Keychain storage, the Lilly.app launcher, power-assertion for "stay awake"); real Mistral/OpenRouter/Gemini/Ollama services; a real Docker or Podman for the devbox; a real Telegram bot; the real Laya download and model (see docs/LAYA.md); live DuckDuckGo, Brave and SearXNG search; Tailscale and phone access. These use standard system interfaces and fail with a clear message rather than silently, but they have not been run on real hardware or accounts by the author.
