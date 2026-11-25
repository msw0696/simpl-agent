<img src="assets/icon.svg" width="64" height="64" alt="">

# SIMPL Agent

An [MCP](https://modelcontextprotocol.io) server that lets Claude read, check, edit and compile **Crestron SIMPL Windows** programs (`.smw`), plus a Claude Code skill that teaches Claude how to use it safely.

You ask in plain English ("why doesn't the projector turn off?", "what will SIMPL warn about?", "add a TSW-1070 at IP ID 03"). Claude answers by reading the real program through these tools. It doesn't guess from the raw text.

> **Status (2026-11-24):** the first version (M0 to M3) is done and live-tested in SIMPL 4.32. Since then: placing macros and SIMPL+ modules, unattended compiling, and **M4 devices** (in progress). See the [roadmap](#roadmap).
>
> This is a personal project, built for one programmer's own use. It is not a Crestron product and isn't affiliated with Crestron.

## Why

SIMPL Windows programs are large, flat graphs of symbols and signals. They're saved in a text format no one documents. Following a signal through ten folders, or working out which signal SIMPL will warn about, is slow by hand. An AI assistant can help, but only if it reads the program accurately and never corrupts the file. This project provides that:

- a **lossless** reader and writer for the file format, proven byte-identical on 3,829 real files;
- a **semantic model** of folders, symbols, signals and devices, using SIMPL's own symbol and device libraries for names;
- **checks** that give the same warnings SIMPL's compiler gives;
- **edits** that are backed up, undoable, and that SIMPL reloads and compiles as predicted;
- **unattended compiles** in SIMPL Windows itself, compared with the checks.

## Tools

21 tools. Every call is logged to `%LOCALAPPDATA%\SimplAgent\audit.jsonl`.

| Group | Tool | What it does |
|---|---|---|
| Status | `simpl_agent_status` | What's installed, and which program SIMPL Windows has open |
| Overview | `describe_program` | Processor, counts, and the top of the Logic folder, plus a `revision` fingerprint |
| Navigate | `folder_tree` | The folder layout |
| | `list_folder` | What's in a folder, in SIMPL's order, with SIMPL's symbol numbers (`S-2.3`) |
| | `show_symbol` | One symbol's pins (with real pin names), signals and parameters |
| Trace | `find_signals` | Signals by name, with how many outputs drive each and how many inputs use it |
| | `follow_signal` | Where a signal comes from and where it goes, across folders |
| Check | `find_problems` | Warnings and notices using SIMPL 4.32's own codes (LGCMCVT102/103/220), plus duplicate names, broken links and symbols that aren't fully wired |
| Library | `find_library_symbols` | Search SIMPL's installed symbol library |
| | `library_symbol_details` | A symbol's real pins and rules |
| | `module_details` | A macro's (`.umc`/`.cmc`) or SIMPL+ module's pins, types and parameters |
| Devices | `device_tree` | Every device: processor, cards, Ethernet and Cresnet devices, ports, addresses, IPs |
| | `free_ids` | Free and used IP IDs and Cresnet IDs on each network |
| | `find_library_devices` | Search SIMPL's device library; says where each device goes and whether `add_device` can place it |
| Edit | `apply_edits` | One all-or-nothing batch of edits (below) |
| | `new_program` | A new, empty program for a processor, exactly as SIMPL's File > New writes it |
| History | `edit_history` | SIMPL Agent's changes to a program |
| | `undo_last_edit` | Undo the last change, only while the file is exactly as that edit left it |
| | `restore_version` | Go back to before any change, with a preview of what would be lost |
| Live | `wait_for_simpl_save` | Wait for the user to save in SIMPL |
| Compile | `compile_program` | Compile in SIMPL Windows unattended and compare SIMPL's messages with `find_problems` |

**`apply_edits` operations:**
- **Folders and logic:** `add_folder`, `add_symbol` (126 simple logic symbols proven in SIMPL 4.3x files), `move_symbol`, `remove_symbol`.
- **Wiring and settings:** `connect` (or disconnect), `set_parameter`, `set_comment`, `rename_signal`, `rename_folder`. New signals are created when a pin names them.
- **Modules:** `add_module` places a macro or SIMPL+ module, wired by pin name. Unused required pins go on SIMPL's `//__…_reserved__` placeholders.
- **Devices:** `add_device` places a device at an IP ID or Cresnet ID the user chooses, or a card in a frame's slot; `remove_device` removes one with everything inside it; `wire_joins` connects a panel's or EISC's digital, analog and serial joins by number, growing its join lists as needed (see [M4](#m4-devices-in-progress)).
- **New programs:** `new_program` (a tool of its own) writes an empty program for a processor exactly as SIMPL's File > New does.

Every result carries a `revision`. SIMPL can renumber handles when it saves, so tools re-read after a save and never reuse old handles.

## How it works

```
Claude Code
   │  stdio MCP, plus the simpl-agent skill
   ▼
simpl_agent (Python 3.11, MCP Python SDK)
   ├─ smw/          lossless .smw/.cmc/.umc reader and writer; semantic model; edits; device builder; safe save
   ├─ catalog/      cached indexes of SIMPL's installed symbol library (symlib.tio) and device library (iodev.tio)
   ├─ analysis      folders, tracing, module pins and find_problems
   ├─ checks        structural rules every SIMPL-saved file follows; the write gate refuses new violations
   ├─ history       backups and history next to each program, for undo and restore
   ├─ compile       unattended SIMPL compiles through an elevated scheduled task
   └─ server        the MCP tools and the audit log
```

- **Lossless first.** The reader keeps every record, in order, byte for byte. Writing an unchanged file gives back exactly the same bytes. Edits change only the records they need to.
- **Crestron's data stays with Crestron.** The symbol and device libraries are read from the local SIMPL install at run time and cached in `%LOCALAPPDATA%\SimplAgent`. None of it is copied into this repo.
- **SIMPL is the final judge.** Each format rule is measured across the public corpus, then checked against what SIMPL Windows 4.32 does when it reloads, compiles and re-saves. Results are in [docs/format.md](docs/format.md).

## Safety rules

These are built into the tools and the skill:

- **Never touch a processor.** No connecting to one, loading a program onto one, or sending it anything. Compiles run only in SIMPL Windows on this PC.
- **Never overwrite unsaved work.** SIMPL shows no unsaved-changes marker, so when SIMPL has the program open the user is asked to save there first. Every write is backed up first. Programs are changed only through the tools, never by hand.
- **Write gate.** A write must pass all of these, or nothing is written:
  - the file is a `.smw` with CRLF line endings;
  - its revision matches the last read, re-checked just before writing;
  - edits that add records only go into files saved by SIMPL 4.3x;
  - the result passes the structural checks.
- **Never invent** symbols, pins, signals or devices. Use only what's in SIMPL's libraries or the program itself. Never pick an IP ID for the user.
- **Never unlock** or read password-protected programs or modules.
- **Client programs are private.** They are never copied into this repo or uploaded; `.gitignore` blocks SIMPL file types. Public sample programs from GitHub are downloaded outside the repo and treated as untrusted text.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| **M0** Format proof | Lossless reader and writer; semantic model; first edits | ✅ Passed in SIMPL 4.32 |
| **M1** Server shell | stdio MCP server, library index, audit log, skill | ✅ |
| **M2** Read and check | Navigate, trace and `find_problems` | ✅ Matches SIMPL's compiler on every file compiled so far |
| **M3** Edit and safety | `apply_edits`, write gate, history and undo, live workflow with SIMPL open | ✅ Live-tested in SIMPL 4.32 |
| Extras | Placing macros and SIMPL+ modules; unattended compiling | ✅ |
| **M4** Devices | Device tree, free IDs, adding devices and frames | 🔨 In progress |
| **M5** New programs | Start a program from scratch | ✅ `new_program`: 13 processors proven identical to SIMPL's File > New (CP3, CP3N, CP4, CP4N, PRO3, PRO4, AV4, MC3, MC4, RMC3, RMC4, DIN-AP4, MPC3-302) |
| **M6** SIMPL+ | Write and compile SIMPL+ modules | Later |
| **M7** Touch panels | Check joins between program and panel | Later |
| **M8** Debugger traces | Read saved Debugger traces | Later |

**The first version (M0 to M3) is done (2026-11-24):** a fresh Claude Code session used SIMPL Agent in plain English to explain a program, check it (matching SIMPL's F12 exactly) and add a One Shot. SIMPL reloaded the edit and compiled it exactly as predicted.

### M0: Format proof ✅

- The reader and writer are **byte-identical on 3,829 files**: 3,449 macros installed with SIMPL and 380 public programs from GitHub, saved by SIMPL 2.x to 4.32.
- A semantic model covers signals, symbols, folders and devices.
- **SIMPL 4.32 check:** six edited test files were reloaded and compiled (F12) in SIMPL, and each gave exactly the predicted messages.
- **Finding:** SIMPL can renumber handles when it upgrades a file on save. Everything later is designed around that.

### M1: Server shell ✅

- A stdio MCP server that Claude Code starts on demand.
- A cached library index (about 0.3 s to load instead of 9 s), the audit log, and the skill.
- Short server instructions (under 2 KB), with the detail in the skill.

### M2: Read and check ✅

- Navigating and tracing tools, and `find_problems` with SIMPL's own message codes and symbol numbers (`S-2.3` is a path: 3rd symbol in the 2nd folder).
- Macro files (`.umc`/`.cmc`) are handled: a macro's arguments count as its own inputs and outputs. Module pins show their real names from the module files.
- **Checked against SIMPL 4.32:** ten hand-compiled test files, where `find_problems` printed the same messages SIMPL did. That covers Buffers sharing an output, several analog drivers, `//` placeholder signals, and second drivers when a macro or SIMPL+ module is one of them (SIMPL doesn't warn).
- **Real job:** on a public DMPS3-4K-150-C classroom program (478 logic symbols, macros, SIMPL+ and SIMPL#), SIMPL compiled clean and `find_problems` reported nothing.
- **Known gap:** signals wired to Smart Graphics list extenders (`.ced`) under an XPanel get SIMPL warnings and notices that `find_problems` doesn't predict yet.

### M3: Edit and safety ✅

- **`apply_edits`** with the write gate above and `dry_run`.
- **History:** every edit is backed up in `.simpl-agent/` next to the program (SIMPL's archive skips that folder). `edit_history`, `undo_last_edit` and `restore_version`.
- **Live workflow with SIMPL open:** SIMPL runs as administrator, so SIMPL Agent can't press Save or Reload in it. The user saves first; after the write SIMPL offers to reload and the user clicks Yes. `wait_for_simpl_save` watches the file.
- **Live tests:** SIMPL reloaded and compiled exactly as predicted, and its re-save was byte-for-byte what SIMPL Agent wrote. On the real classroom program, an edit (a new folder, an OR, a changed pulse time) compiled with exactly the one predicted notice.

### Modules and automatic compiling ✅

- **`add_module`** places macros and SIMPL+ modules, wired by pin name. The record rules were measured on 631 placed modules in the corpus. A macro and a SIMPL+ module placed in the classroom program compiled with exactly the predicted messages.
  - Not yet: SIMPL+ modules with drop-down parameters.
- **`compile_program`** compiles in SIMPL Windows with no clicking, in about a minute, and reports SIMPL's errors, warnings, notices and any dialogs it showed. It uses [smpc](https://github.com/Norgate-AV/smpc) (MIT) through a one-time elevated scheduled task; see [Setup](#setup). It refuses while SIMPL is open.
- SIMPL+ and SIMPL# need Microsoft **.NET Compact Framework 3.5** installed, or SIMPL gives error LGCMCVT277.

### M4: Devices (in progress)

- **`device_tree`** and **`free_ids`** read the device tree and free IP IDs and Cresnet IDs.
- **`add_device`** places a device at a free IP ID (4-Series, 3-Series, MC3 Ethernet) or Cresnet ID:
  - **What it writes, as SIMPL does:** the device, its model record and default IP, and its logic symbol under the network in ID order. Free IDs stay in one record.
  - **Frames:** a device with its own slots (DM frames, NVX endpoints, ST-IO) is built with every slot and every device SIMPL puts inside it, numbered the way SIMPL numbers them.
  - **Cards:** cards go into a frame's slots (`network` = the frame, `address` = the slot number), for card types SIMPL writes consistently: DM input and output cards, DM endpoints, HDBT receivers and similar. A full output card (DMCO-22) replaces the default "DM Outputs" after `remove_device`.
  - **Which devices:** any whose pins are all optional and whose parameters have known defaults (touch panels, XPanels, EISCs, DM frames and endpoints, NVX and many more). Others are refused with the reason.
- **Proof:**
  - It rebuilds SIMPL 4.32's own saves byte for byte: a TSW-1070 and an EISC, and a DM-MD8x8 with input cards, a DM-NVX-36x, a CEN-IO-COM-102, a CEN-RGBHV8x4, XPanel and TSW panels, placed in SIMPL by SIMPL Agent driving SIMPL's own window (`tools/simpl_gui.py`).
  - `tools/prove_devices.py` and `tools/prove_frames.py` rebuild every device and frame in the 380 public programs from today's libraries. 770 device types match; 63 frames rebuild identically; 238 of 239 cards in slots rebuild identically. In modern files the only differences left are things users attach later (logic modules, HDBaseT links, replaced drivers).
  - Automatic compiles: 15 device types in one program; a DM-MD8x8, DM-NVX-36x and ST-IO together; a DM-MD8x8 with two input cards plus a DM-TX-201-C. All 0 errors, 0 warnings and 0 notices.
- **Panels:** `wire_joins` maps joins to pins (digital first, then analog, then serial, for inputs and outputs; all 5,045 wired panel pins in modern public files fit) and grows a list's inputs and outputs together when a join is past its end. SIMPL re-saved a grown, wired TSW-1070 byte for byte, and it compiled with exactly the predicted messages.
- **Next:** COM/IR drivers placed by users, devices with required pins, and device parameters without defaults (e.g. a TCP/IP Client's port).

### Later

- **M6 SIMPL+:** write and compile SIMPL+ modules through Crestron's own SIMPL+ compiler.
- **M7 Touch panels:** check that a program's joins match its touch panel, and wire a panel's joins in bulk.
- **M8 Debugger traces:** read saved SIMPL Debugger traces to explain what happened.
- **Probably never:** live signal watching. If it is ever built, it will be read-only.

### Not planned

A licence system, installer, code signing or tray app. This is a personal tool, registered directly with Claude Code.

## Setup

Needs **Windows**, **Python 3.11+**, and **SIMPL Windows** installed (the tools read its symbol and device libraries).

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Register the server with Claude Code for all your sessions:

```
claude mcp add --scope user simpl-agent -- <full path to repo>\.venv\Scripts\python.exe -m simpl_agent.server
```

The skill is in `.claude/skills/simpl-agent/SKILL.md`. Claude Code loads it automatically inside this repo; to use it everywhere, link that folder into `%USERPROFILE%\.claude\skills\simpl-agent`.

**Unattended compiling (optional).** Download [smpc](https://github.com/Norgate-AV/smpc) and verify its checksum, then run once, elevated (one UAC prompt):

```
powershell -ExecutionPolicy Bypass -File tools\compile_task\setup.ps1 -SmpcExe <smpc.exe> -AllowedRoots <folder>,<folder> -User <DOMAIN\user>
```

This installs smpc and a small wrapper into `C:\Program Files\SimplAgent` (admin-only) and registers the on-demand task `\SIMPL Agent\Compile`. The task compiles only `.smw` files under the allowed folders.

Optional environment variables:

| Variable | Default | Used for |
|---|---|---|
| `SIMPL_AGENT_HOME` | `%LOCALAPPDATA%\SimplAgent` | Audit log and library index caches |
| `SIMPL_CORPUS` | `~\simpl-corpus` | Where the public sample programs are downloaded |

## Development

```
.venv\Scripts\python -m pytest -m "corpus or not corpus"   # all 184 tests (corpus tests need the local corpus)
.venv\Scripts\python -m pytest                             # fast tests only
.venv\Scripts\python -m ruff check .
python -I tools/fetch_github_corpus.py    # download public sample programs (outside the repo)
python -I tools/corpus_check.py           # measure each format rule across the corpus
.venv\Scripts\python tools/prove_devices.py   # rebuild every corpus device from the libraries
.venv\Scripts\python tools/prove_frames.py    # rebuild every corpus frame (slots and built-in devices)
```

Some device tests compare against SIMPL's own saves. Those files are real SIMPL output, so they stay out of the repo; the tests skip when `tests/data/` doesn't have them.

| Path | What's there |
|---|---|
| `src/simpl_agent/smw/` | `rawfile.py` (lossless reader and writer), `model.py` (semantic model), `edit.py` (edits), `device_edit.py` (devices and frames), `save.py` (backup and safe write) |
| `src/simpl_agent/catalog/` | Symbol and device library readers and cached indexes |
| `src/simpl_agent/analysis.py` | Folders, tracing, module pins and `find_problems` |
| `src/simpl_agent/checks.py` | Structural rules for the write gate |
| `src/simpl_agent/devices.py` | `device_tree` and `free_ids` |
| `src/simpl_agent/edit_tools.py`, `history.py` | `apply_edits`, the write gate, history, undo and restore |
| `src/simpl_agent/compile.py` | `compile_program` |
| `src/simpl_agent/server.py` | The MCP server and audit log |
| `tools/` | Corpus download, format measurements, device proofs and slot rules (`build_slot_rules.py`), `simpl_gui.py` (drives SIMPL's window for proof rounds), SIMPL test-file builders, compile task setup |
| `docs/format.md` | Everything measured about the file format, and every SIMPL 4.32 result |

## Licence

No licence has been chosen yet. All rights reserved.
