# Laya

Laya is a small helper model that Lilly can use for a few quick decisions to save tokens. The installer sets it up by default (`--no-laya` skips it), and Lilly works fully without it.

## What it is, and what it is not

* **It is** a small classifier (a 421-million-parameter model, run on your own processor). Given a piece of text it answers a yes/no or pick-one question and says how sure it is.
* **It is not** a chat model. It cannot write text, run tools, read your files or approve anything.
* **It only ever adds caution.** Its answer must be one of the options Lilly's code offered, and it can make Lilly more careful (treat a text as outside text, stop a run that is going round in circles, ask you before a step, flag a reply), never less. It cannot allow an action or skip an approval. Policy and approvals never look at it.

## What it is for in Lilly

| Question | What a Laya answer does |
| --- | --- |
| Is this run going round in circles? | A repeating run is stopped, with a plain message. |
| Does this text read like orders aimed at the agent? | The result is treated as outside text: nothing it says is acted on without asking. |
| Which item of a short list does this wording mean? | Picks an app or element; if unsure you are asked. |
| *Laya assist*, optional, off by default: does a step that changes something serve what you asked? | A step Laya doubts asks for your approval even if policy would have allowed it. |
| *Laya assist*, optional, off by default: does a finished reply follow your request and the agent's instructions? | A small warning under the reply. The reply is never changed or held back. |
| *Token saving*, starts as watch only when Laya is turned on: can this request be answered from general knowledge, with nothing to look up or change? | A quick model answers without being sent the tool list. If it says it needs tools, the normal planner runs. |

Simple rules answer the first three questions first; Laya is asked only when the rules are not sure. See [Laya assist](#laya-assist).

## Requirements

* Python 3.10 or newer for Laya's own environment. Lilly uses its own Python when it fits, otherwise another one it finds on the PATH.
* **Intel Macs:** PyTorch no longer publishes wheels for them for current Pythons, so Laya needs **Python 3.12 or older** there. Install it (`brew install python@3.12` or python.org) and Lilly finds it. Lilly then holds `numpy<2` and `transformers>=4.48,<5` for you.
* About 5 GB of free disk space while installing (the download is about 846 MB; the packages and the environment make up the rest).
* Internet access to **huggingface.co** (the model) and **pypi.org** (the packages), for the install only. Afterwards Laya runs offline.
* About 2 GB of memory while the model is loaded. It is loaded only when a question needs it and let go after about 90 seconds of quiet.

## Set it up

Check first, install, test, then turn it on. Any of the three routes does the same thing.

**In the app (guided).** Settings → Quick decisions → *Laya*. Five steps follow what is true now: check this computer (with what to fix), download and install (with progress), test it, turn it on, and the optional assist.

**From a terminal.**

```bash
lilly laya check      # can this computer run Laya? downloads nothing
lilly laya install    # download the model and set up its own environment
lilly laya test       # load it and ask three questions with known answers
lilly laya enable     # use it (a running Lilly needs lilly stop, then lilly open)
```

**With the installer (the default).** `./install.sh` runs check, install and test, and turns Laya on only if the test passes. If any step fails, Lilly is still installed and works without it; you can retry later. `./install.sh --no-laya` skips Laya.

To go back: `lilly laya disable` (keeps the files) or `lilly laya remove` (deletes them and turns it off). In the app: *Turn off* and *Remove*.

## Verify that it works

* `lilly laya check` or the app's step 1: the computer, the Python that will be used, disk space and the size of the download.
* `lilly laya test` or the app's step 3: loads Laya through the same code Lilly uses and asks three questions: an order aimed at an agent (expected *yes*), ordinary prose (expected *no*) and a repeating step list (expected *loop*). It prints, for each, what was expected, what came back, how sure Laya was and how long it took, plus the load time. Exit code 1 if anything is wrong. It never turns Laya on and lets the model go again straight afterwards. The whole test is stopped after about two and a half minutes.
* `lilly doctor` has a *Laya (optional)* line: not installed (fine), installed and off, or on; and a problem only if an install is incomplete, is not the version this Lilly expects, or is turned on without being installed.

## Judge whether it is good enough

Passing the self-test shows that Laya runs, not that it is accurate on your work. Lilly records every question and answer (a redacted 300-character summary, never the full text).

1. Turn the assist questions on as **Watch only**: Laya's answers are logged and nothing acts on them.
2. After some use, run `lilly decisions report`. It shows, per question and decider, how often it answered and, for answers you marked, how often it was right. Mark answers *Right* or *Wrong* under Settings → Quick decisions → *How they are doing*.
3. `lilly decisions calibrate` suggests a minimum confidence from your marks and changes nothing. Edit `decisions.<question>.min_confidence` to apply it.
4. Only when the numbers satisfy you, switch a question from *Watch only* to acting.

## Laya assist

Three extra questions at Settings → Quick decisions → *Laya assist*. Each starts as watch only. The first two are off until you switch them on; the third is switched on, watch only, when Laya is turned on.

* **Check steps before they run.** Before a step that changes something would run on its own, Laya is asked whether it serves what you asked and respects the agent's instructions. If it says no and the question is set to act (*Ask me when Laya doubts*), the step needs your approval even though policy would have allowed it. A step that already needs approval, or is denied, is never changed. Steps that only read are never checked.
* **Check replies afterwards.** Once a reply is saved, in the background, Laya is asked whether it follows your request and the agent's instructions (topic, language, format, length). If it says it drifts and the question is set to act, a small warning appears under the reply. The reply is never rewritten or held back. If the model had already been let go when the reply finished, that reply is simply not checked.

* **Answer simple questions without tools** (token saving). At the start of a task Laya is asked whether the request can be answered from general knowledge alone. If it says yes and the question is set to act (*Use Laya to skip the tool list*), a quick model gets the request without the tool list, which is most of the planner's prompt. If that model says it needs tools, or gives anything but a plain answer, the normal planner runs, so the cost of a wrong guess is one small call. This can only skip work: nothing runs without a plan, and approvals and policy are untouched. Laya's guess is compared with what happened and recorded, in watch-only mode too, so `lilly decisions report` shows how often it was right. The first task after a start may not use it, because Laya is still loading.

Turning Laya off turns all three off.

Laya cannot run tools or write their arguments: it only picks from options that Lilly offers. In the normal runtime its typed System-1 output can route a model tier, capability namespace, tool family and verification depth. It never chooses arbitrary concrete tool arguments or widens policy.

## Resource use

| | |
| --- | --- |
| Disk | about 846 MB of model plus its Python packages, in `~/.lilly/addons/laya` |
| Memory | about 2 GB while loaded |
| Processor | two threads, on the CPU; no GPU is used |
| When it runs | only when a question needs it; first load takes seconds to a minute |
| Let go | after about 90 seconds without a question |
| Given up on | for the rest of the session, after three timeouts in a row |

## If something goes wrong

Messages are shown in the app and printed by the commands. Lilly keeps working in every case.

| Message | What it means and what to do |
| --- | --- |
| `there is not enough free disk space (about 5 GB is needed)` | Free some space and try again. |
| `Laya needs Python 3.10 or newer, and none was found.` | Install a newer Python and try again. |
| `Laya's machine-learning library supports Intel Macs only up to Python 3.12, and no Python 3.10 to 3.12 was found. Install Python 3.12 …` | Install Python 3.12 (`brew install python@3.12`), then try again. |
| `could not create the environment: …` | On Debian or Ubuntu: `sudo apt install python3-venv`. |
| `pip could not install Laya and the packages it needs on this computer: …` | No PyTorch wheel for this computer or Python, or PyPI cannot be reached (proxy, VPN, school or office network). Try another network. |
| `could not download <file>: …` | huggingface.co cannot be reached. Check the connection or any proxy, then try again; finished files are kept. |
| `<file> ended early (… of … bytes)` | The download was cut off. Try again. |
| `<file> is larger than the reviewed file; stopped` | The server sent more than the pinned file. Nothing is kept. |
| `<file> is not the reviewed file (git id …)` or `(sha256 …)` | The download is not the exact file that was reviewed. Nothing is kept. Do not work around it; see `src/lilly/decide/laya_pins.py`. |
| `Laya is already being installed` | One install at a time. Wait for it. |
| `Laya is not installed yet` | Install it first (step 2). |
| `A Laya test is already running` | Wait for the other test to finish. |
| `Laya could not be loaded. Run 'lilly laya install' to repair the installation…` | The worker did not start. Run `lilly laya install` again; Lilly's log has details. |
| `The test took too long and was stopped…` | This computer may be too slow or short of memory for Laya. Remove it, or leave it off. |
| `Laya ran, but N of 3 answers were not the expected ones…` | It runs but answered unexpectedly. If you use it, keep it on watch only and check `lilly decisions report`. |
| `lilly doctor`: *an install is there but is not the version this Lilly expects* | Run `lilly laya install` to repair it, or `lilly laya remove`. |

## Remove it

`lilly laya remove` (or *Remove* in the app) turns Laya off and deletes `~/.lilly/addons/laya`. Nothing else of yours is touched.

## Not verified

The author has **not** downloaded the real model or run the real Laya package. The development environment could not reach huggingface.co. What has been run is everything around it, against a stand-in worker that answers by simple text rules:

* the pre-check, the installer's file checks (size, git id and SHA-256 against the pinned values), the worker protocol, answer parsing, caching, warm-up and unloading;
* the self-test, the guided setup screens, the commands and the installer script.

What has never been run: the real download, `pip install laya` with its real dependencies, loading the real model, the real answers (so whether it passes the three-question test, how fast it is, and how accurate it is on your work), and the pinned file sizes and hashes against real files. The first real install is that check, and it refuses on any mismatch. Treat Laya as unproven until you have run `lilly laya test` and judged it yourself as above.
