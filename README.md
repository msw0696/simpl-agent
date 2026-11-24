<img src="assets/icon.svg" width="64" height="64" alt="">

# SIMPL Agent

An [MCP](https://modelcontextprotocol.io) server that lets Claude read, check and, later, edit **Crestron SIMPL Windows** programs (`.smw`), plus a Claude Code skill that teaches Claude how to use it safely.

You ask in plain English ("why doesn't the projector turn off?", "what will SIMPL warn about?", "add a second display in Room A"). Claude answers by reading the real program through these tools. It doesn't guess from the raw text.

> **Status:** M0, M1 and M2 are built. Claude can **read and check** programs today. Editing (M3) is next. See the [roadmap](#roadmap).
>
> This is a personal project, built for one programmer's own use. It is not a Crestron product and isn't affiliated with Crestron.

## Why

SIMPL Windows programs are large, flat graphs of symbols and signals. They're saved in a text format no one documents. Following a signal through ten folders, or working out which signal SIMPL will warn about, is slow by hand. An AI assistant can help, but only if it reads the program accurately and never corrupts the file. This project builds that foundation:

- a **lossless** reader and writer for the file format, proven byte-identical on thousands of real files;
- a **semantic model** of folders, symbols, signals and devices, using SIMPL's own symbol library for pin names;
- **checks** that give the same warnings SIMPL's compiler gives;
- later, **edits** that are backed up, undoable, and that SIMPL reloads and compiles cleanly.

## What it can do today (M2)

Ten read-only tools:

| Group | Tool | What it does |
|---|---|---|
| Status | `simpl_agent_status` | What's installed, and which program SIMPL Windows has open, with an unsaved-changes flag |
| Overview | `describe_program` | Processor, counts, and the top of the Logic folder, plus a `revision` fingerprint |
| Navigate | `folder_tree` | The folder layout |
| | `list_folder` | What's in a folder, in SIMPL's order |
| | `show_symbol` | One symbol's pins (with the library's real pin names), signals and parameters |
| Trace | `find_signals` | Signals by name, with how many outputs drive each and how many inputs use it |
| | `follow_signal` | Where a signal comes from and where it goes, across folders |
| Check | `find_problems` | Warnings and notices using SIMPL 4.32's own codes (LGCMCVT102/103/220), plus duplicate names, broken links and symbols that aren't fully wired |
| Library | `find_library_symbols` | Search SIMPL's installed symbol library |
| | `library_symbol_details` | A symbol's real pins and rules |

- `find_problems` gave SIMPL's exact warning and notice counts on all six test programs compiled so far. That's a small set, so results that rely on unconfirmed rules are labelled as unconfirmed.
- Every call is logged to `%LOCALAPPDATA%\SimplAgent\audit.jsonl`.
- SIMPL's symbol library is indexed once and cached in the same folder, so it loads in about 0.3 s instead of 9 s.
- Every result carries a `revision`. SIMPL can renumber handles when it saves, so tools re-read after a save and never reuse old handles.

## How it works

```
Claude Code
   │  stdio MCP, plus the simpl-agent skill
   ▼
simpl_agent (Python 3.11, MCP Python SDK)
   ├─ smw/        lossless .smw/.cmc/.umc reader and writer; semantic model; edits; safe save
   ├─ catalog/    index of SIMPL's installed symbol library (symlib.tio)
   ├─ analysis    folders, tracing and find_problems
   ├─ server      the MCP tools and the audit log
   └─ (planned)   history/ (backups, undo), live/ (talk to the SIMPL window)
```

- **Lossless first.** The reader keeps every record, in order, byte for byte. Writing an unchanged file gives back exactly the same bytes. Edits change only the records they need to.
- **Crestron's data stays with Crestron.** The symbol and device libraries are read from the local SIMPL install at run time. None of it is copied into this repo.
- **SIMPL is the final judge.** Each format rule is checked against what SIMPL Windows 4.32 actually does when it reloads and compiles (F12). Results are in [docs/format.md](docs/format.md).

## Safety rules

These are built into the tools and the skill:

- Never compile a program, connect to a processor, or load a program onto one. Watching live signals, if ever built, will be read-only.
- Never edit a file while SIMPL has unsaved changes. Back up before every write. Write only through the tools, never by hand.
- Never invent symbols, pins, signals or devices. Use only what's in SIMPL's library or the program itself.
- Never unlock or read password-protected programs or modules.
- Client programs are private. They are never copied into this repo or uploaded. `.gitignore` blocks SIMPL file types.
- Public sample programs from GitHub are downloaded outside the repo and treated as untrusted text.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| **M0** Format proof | Lossless reader and writer; semantic model; first edits; SIMPL reload and compile check | ✅ Passed in SIMPL 4.32 |
| **M1** Server shell | stdio MCP server, library index, audit log, skill | ✅ Built |
| **M2** Read and check | Navigate, trace and `find_problems` | ✅ Matches SIMPL's compiler on every file compiled so far |
| **M3** Edit and safety | `apply_edits`, history and undo, live link to the SIMPL window | ⏭ Next |
| **M4** Devices | Add devices, find free IDs | Later, optional |
| **M5** New programs | Start a program from scratch | Later, optional |
| **M6** SIMPL+ | Compile and check SIMPL+ modules | Later, optional |
| **M7** Touch panels | Check joins between program and panel | Later, optional |
| **M8** Debugger traces | Read saved Debugger traces | Later, optional |

**The first version is M0 to M3.** It's done when three requests go through Claude on a copy of a real or public program, and each result reloads and compiles cleanly in SIMPL:
1. read and explain part of the program;
2. a `find_problems` run;
3. one of the M3 edit tests below.

### M0: Format proof ✅

The gate for everything else: can we change a `.smw` file without SIMPL noticing anything but the change?

- The reader and writer are **byte-identical on 3,829 files**: 3,449 macros installed with SIMPL and 380 public programs from GitHub, saved by SIMPL 2.x to 4.32.
- A semantic model covers signals, symbols, folders and devices. A reader for SIMPL's installed symbol library gives the real pin names.
- First edits: rename a signal, add a signal, add a simple logic symbol to a folder, and set a comment. Each is all-or-nothing and backs up before it writes.
- **SIMPL 4.32 check:** six edited test files were reloaded and compiled (F12) in SIMPL. Every one gave exactly the predicted messages. Renaming a signal in a real program gave no new messages at all.
- One finding: SIMPL can renumber handles when it upgrades a file on save. Later milestones are designed around that.

### M1: Server shell ✅

- A stdio MCP server that Claude Code starts on demand.
- `simpl_agent_status`, `describe_program`, `find_library_symbols` and `library_symbol_details`.
- A cached library index, the audit log, and the first version of the skill.
- Short server instructions (under 2 KB), with the detail in the skill.

### M2: Read and check ✅

- `folder_tree`, `list_folder`, `show_symbol`, `find_signals` and `follow_signal` for navigating and tracing.
- `find_problems` finds signals driven twice, never driven or never used, duplicate names, and symbols that aren't fully wired. It uses SIMPL's own message codes.
- Macro files (`.umc`/`.cmc`) are handled: a macro's arguments count as its own inputs and outputs.
- **Checked against SIMPL 4.32:** ten hand-compiled test files, where `find_problems` printed the same messages SIMPL did. That covers Buffers sharing an output, several analog drivers, `//` placeholder signals, and SIMPL's symbol numbers (`S-2.3`).
- **Real job:** on a real public 3-Series classroom program (478 logic symbols, macros, SIMPL+ and SIMPL#), SIMPL compiled clean and `find_problems` reported nothing, matching it. That compile also showed that SIMPL skips the second-driver check when a macro or SIMPL+ module is one of the drivers.

**First version done (2026-11-24):** a fresh Claude Code session used SIMPL Agent in plain English to explain a program, check it (matching SIMPL's F12 exactly) and add a One Shot. SIMPL reloaded the edit and compiled it exactly as predicted.

### M3: Edit and safety ✅ (live-tested in SIMPL 4.32, 2026-11-24)

- **`apply_edits`**: a batch of operations applied together, all or nothing, with a one-line summary, then a list of any new problems.
  - **Operations:** add a folder, add a symbol, connect or disconnect a pin, set a parameter, set a comment, rename a signal, rename a folder, move a symbol, and remove a symbol.
  - **No standalone "add a signal":** new signals are created when a pin names them, and signals left unused by a removal are deleted, because SIMPL doesn't keep unused signals.
- **Write gate.** A write must pass all of these, or nothing is written:
  - the file is a `.smw` with CRLF line endings;
  - its revision matches the last read, re-checked just before writing;
  - if SIMPL has it open, the user has confirmed they saved there;
  - for ops that add symbols or folders, it was saved by SIMPL 4.3x;
  - the result passes the structural checks.

  `dry_run` checks an edit without writing it.
- **History:**
  - every edit is backed up in `.simpl-agent/` next to the program; SIMPL's archive skips that folder;
  - `edit_history`;
  - `undo_last_edit`, only while the file is exactly as the edit left it;
  - `restore_version`, which previews what would be lost and needs confirmation.
  - **Proof:** the pin-key placement is proven against every wired pin SIMPL 4.3x saved in the corpus.
- **Live link to SIMPL Windows:** SIMPL runs as administrator, so SIMPL Agent can't press Save or Reload in it, and SIMPL shows no readable unsaved-changes marker. Instead:
  - `simpl_agent_status` sees which program SIMPL has open;
  - if it's the one being edited, the user saves first (`user_confirmed_saved`);
  - after the write, SIMPL itself offers to reload, and the user clicks Yes;
  - `wait_for_simpl_save` watches the file.
  - **Live test:** SIMPL reloaded and compiled exactly as predicted, and its re-save was byte-for-byte what SIMPL Agent wrote.
- **Not yet:** `redo_after_save`, for replaying an edit that SIMPL's save overwrote.
- **Acceptance tests:**
  - "Add a second display in Room A that turns on and off with the primary display."
  - "Rename the Lobby folder to Reception and keep the signals wired."

### Later (optional, in this order)

- **M4 Devices:** `add_device`, `find_library_devices` and `free_ids`, using SIMPL's installed device library.
- **M5 New programs:** `start_program`, to start a program for a given processor.
- **M6 SIMPL+:** compile and check SIMPL+ modules through Crestron's own SIMPL+ compiler.
- **M7 Touch panels:** check that a program's joins match its touch panel.
- **M8 Debugger traces:** read saved SIMPL Debugger traces to explain what happened.
- **Probably never:** live signal watching. If it is ever built, it will be read-only.

### Not planned

A licence system, installer, code signing or tray app. This is a personal tool, registered directly with Claude Code.

## Setup

Needs **Windows**, **Python 3.11+**, and **SIMPL Windows** installed (the tools read its symbol library).

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Register the server with Claude Code. Run this from the repo folder to make it available only in this project:

```
claude mcp add simpl-agent -- <full path to repo>\.venv\Scripts\python.exe -m simpl_agent.server
```

The skill is in `.claude/skills/simpl-agent/SKILL.md`, and Claude Code loads it automatically in this repo.

Optional environment variables:

| Variable | Default | Used for |
|---|---|---|
| `SIMPL_AGENT_HOME` | `%LOCALAPPDATA%\SimplAgent` | Audit log and library index cache |
| `SIMPL_CORPUS` | `~\simpl-corpus` | Where the public sample programs are downloaded |

## Development

```
.venv\Scripts\python -m pytest            # unit tests, including a real stdio round trip
.venv\Scripts\python -m pytest -m corpus  # slow tests over the local corpus
.venv\Scripts\python -m ruff check .
python -I tools/fetch_github_corpus.py    # download public sample programs (outside the repo)
python -I tools/corpus_check.py           # measure each format rule across the corpus
python -I tools/make_f12_samples.py       # build edited copies to reload and compile in SIMPL
```

| Path | What's there |
|---|---|
| `src/simpl_agent/smw/` | `rawfile.py` (lossless reader and writer), `model.py` (semantic model), `edit.py` (edits), `save.py` (backup and safe write) |
| `src/simpl_agent/catalog/` | Symbol library reader and cached index |
| `src/simpl_agent/analysis.py` | Folders, tracing and `find_problems` |
| `src/simpl_agent/server.py` | The MCP server and audit log |
| `tools/` | Corpus download, format measurements, SIMPL test-file builder |
| `docs/format.md` | Everything measured about the file format, and the SIMPL 4.32 results |

## Licence

No licence has been chosen yet. All rights reserved.
