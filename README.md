<img src="assets/icon.svg" width="64" height="64" alt="">

# SIMPL Agent

An [MCP](https://modelcontextprotocol.io) server that lets Claude read, check, edit and compile **Crestron SIMPL Windows** programs (`.smw`), plus a Claude Code skill that teaches Claude how to use it safely.

You ask in plain English ("why doesn't the projector turn off?", "what will SIMPL warn about?", "add a TSW-1070 at IP ID 03"). Claude answers by reading the real program through these tools. It doesn't guess from the raw text.

> **Status (2026-11-25):** M0 to M7 are done and checked against SIMPL 4.32's own saves and compiles: reading, checking, editing, devices, new programs and **SIMPL+ modules** (writing, compiling and placing them, drop-down parameters, and warnings when a placed module's pins change), and **touch-panel joins** checked and wired from CH5 Agent's join maps. **M8**, reading saved Debugger traces, is built but not yet checked against a real saved log. A real conference-room program built end to end compiled clean. See the [roadmap](#roadmap).
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

27 tools. Every call is logged to `%LOCALAPPDATA%\SimplAgent\audit.jsonl`.

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
| | `simpl_open` | Open a program in SIMPL without admin rights, so SIMPL Agent can save and reload it there |
| | `simpl_save` | Save the program in SIMPL; edits then go ahead without asking, and SIMPL reloads them automatically |
| Compile | `compile_program` | Compile in SIMPL Windows unattended and compare SIMPL's messages with `find_problems` |
| Traces | `read_trace` | Read a saved SIMPL Debugger log: signal changes, events and timestamps with a per-signal summary; with the program, check the names and show what drove a signal's changes |
| Panels | `check_panel_joins` | Check a touch panel's joins (CH5 Agent's `joins.json`) against what the program wires on that panel: missing, different and unused joins, and a ready fix for the missing ones |
| SIMPL+ | `splus_reference` | Look up functions, declarations, directives, events and compiler errors in Crestron's SIMPL+ Language Reference (installed with SIMPL) |
| | `splus_compile` | Compile a SIMPL+ module with Crestron's own SPlusCC (no window, no admin): errors and warnings per target with the help's explanation, and the pins SIMPL will show |

**`apply_edits` operations:**
- **Folders and logic:** `add_folder`, `add_symbol` (126 simple logic symbols proven in SIMPL 4.3x files), `move_symbol`, `remove_symbol`.
- **Wiring and settings:** `connect` (or disconnect), `set_parameter`, `set_comment`, `rename_signal`, `rename_folder`. New signals are created when a pin names them.
- **Modules:** `add_module` places a macro or SIMPL+ module, wired by pin name. Unused required pins go on SIMPL's `//__…_reserved__` placeholders.
- **Devices:** `add_device` places a device at an IP ID or Cresnet ID the user chooses, or a card in a frame's slot; `remove_device` removes one with everything inside it; `wire_joins` connects a panel's or EISC's digital, analog and serial joins by number, growing its join lists as needed (see [M4](#m4-devices--2026-11-24)). With `joins_file` it wires straight from CH5 Agent's `joins.json` and never replaces a join wired to another signal (see [M7](#m7-touch-panels--2026-11-25)).
- **New programs:** `new_program` (a tool of its own) writes an empty program for a processor exactly as SIMPL's File > New does. SIMPL won't compile a program with a blank Program ID Tag, which File > New leaves blank; the `set_program_header` edit sets it (and the Program Name).
- **Signal types:** a new signal takes its pin's type from the library (a Serial Send's `out$` gets a serial signal), and a signal of the wrong type is refused. On devices with several pin lists (panels, EISCs, dimmers), a pin takes its list's type: digital, analog or serial. That held for all 64,525 wired pins of such devices in the corpus.

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
| **M4** Devices | Device tree, free IDs, adding and removing devices, frames, cards, drivers, panel joins | ✅ Matches SIMPL 4.32's own saves |
| **M5** New programs | Start a program from scratch | ✅ `new_program`: 13 processors proven identical to SIMPL's File > New (CP3, CP3N, CP4, CP4N, PRO3, PRO4, AV4, MC3, MC4, RMC3, RMC4, DIN-AP4, MPC3-302) |
| **M6** SIMPL+ | Write, compile and place SIMPL+ modules | ✅ Checked in SIMPL 4.32: drop-downs, changed pins; `splus_reference`, `splus_compile` |
| **M7** Touch panels | Check joins between program and panel | ✅ For CH5 Agent's `joins.json`: `check_panel_joins`, `wire_joins {joins_file}`; checked in SIMPL 4.32 |
| **M8** Debugger traces | Read saved Debugger traces | 🔨 `read_trace` built; not yet checked against a real saved log |

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
- **Live workflow with SIMPL open:** when SIMPL runs as administrator (its default), SIMPL Agent can't press Save or Reload in it: the user saves first, and after the write SIMPL offers to reload and the user clicks Yes. `wait_for_simpl_save` watches the file.
- **Live link (2026-11-24):** opened with `simpl_open`, SIMPL runs without admin rights and takes plain window messages, even with the screen locked. `simpl_save` saves the program there (File > Save by its menu command), `apply_edits` accepts that revision, and after the write SIMPL Agent makes SIMPL check the file and answers its reload prompt. Checked end to end: SIMPL's next save was byte-identical to SIMPL Agent's write.
- **Live tests:** SIMPL reloaded and compiled exactly as predicted, and its re-save was byte-for-byte what SIMPL Agent wrote. On the real classroom program, an edit (a new folder, an OR, a changed pulse time) compiled with exactly the one predicted notice.

### Modules and automatic compiling ✅

- **`add_module`** places macros and SIMPL+ modules, wired by pin name. The record rules were measured on 631 placed modules in the corpus. A macro and a SIMPL+ module placed in the classroom program compiled with exactly the predicted messages.
  - SIMPL+ drop-down parameters take a listed value or its label (since 2026-11-25; see [M6](#m6-simpl--2026-11-25)).
- **`compile_program`** compiles in SIMPL Windows with no clicking and reports SIMPL's errors, warnings, notices and any dialogs it showed. Since 2026-11-24 it opens SIMPL without admin rights and drives it by menu commands, so it works even with the screen locked and needs no elevated task. It answers only routine dialogs (load notices, commented-out symbols) and always answers No to "Transfer Program?". If SIMPL is already open as administrator it falls back to [smpc](https://github.com/Norgate-AV/smpc) (MIT) through a one-time elevated scheduled task; see [Setup](#setup).
- SIMPL+ and SIMPL# need Microsoft **.NET Compact Framework 3.5** installed, or SIMPL gives error LGCMCVT277.

### M4: Devices ✅ (2026-11-24)

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
- **Parameters and pins at placement:** `add_device` takes `parameters` (by name or in order) and `connect` (pin name to signal). A device whose parameter has no default (a TCP/IP Client's Port, lighting settings) needs its value; SIMPL marks it incomplete otherwise. A TCP/IP Client with just its Port compiled cleanly.
- **COM drivers** go on COM ports (`network` = the COM card, `address` = the port) like SIMPL's own default drivers, with their `Cm` settings record; removing the CP4N's COM 1 driver and adding one back gives the original file byte for byte.
- **Handles:** new devices, symbols and their `Db`/`Et`/`Cm` records take the lowest unused handle, as SIMPL does after a delete.
- **Not supported (refused with the reason):** IR drivers (they need an IR driver file from Crestron's database), one-way serial drivers on IR ports, devices whose symbols SIMPL marks incomplete until wired (Virtual Communication Port), and `new_program` for DMPS3, 2-Series and the Ethernet-only processor.

### M6: SIMPL+ ✅ (2026-11-25)

- **Workflow:** look things up with `splus_reference`, write the `.usp` beside the program, `splus_compile` until clean, place it with `add_module`, then `compile_program`.
- **`splus_reference`** searches Crestron's SIMPL+ Language Reference (`Simpl+lr.chm`, installed with SIMPL). On first use it is unpacked with Windows' `hh.exe` into SIMPL Agent's cache, never into this repo. It covers 526 pages: syntax, parameters, return values, examples, series support, and one page per compiler error. A `#CATEGORY` lookup also lists the category IDs.
- **`splus_compile`** adds the help's explanation to each coded error. It returns the module's pins as SIMPL will show them, read from the `.ush` SPlusCC writes.
  - **It converts the file to CRLF first.** SPlusCC drops everything after a `//` comment in a file with LF line endings, then reports a clean compile of an empty module. 71 of the 76 public modules checked for this needed the fix.
- **Proof:** a feedback-parser module written for the conference-room program compiled with SPlusCC, was placed on COM 1's `rx$`, and compiled in SIMPL with 0 errors, warnings and notices. A fresh SIMPL re-saved the program byte for byte. All 156 public `.usp` files compiled in scratch copies: 113 compile, the failures I checked are SIMPL# libraries missing from their repos, and the parser accounts for every message SPlusCC counts.
- **SIMPL keeps the module build it read first,** even after reloading the program. `compile_program` saves and restarts a SIMPL started with `simpl_open` if any of the program's `.ush` files is newer than that SIMPL. `simpl_open` waits until SIMPL has loaded the program, which took 68 s here.
- **Drop-down parameters** (`propList`): `module_details` lists each one's options and default. `add_module` takes a listed value or its label and refuses anything else, as SIMPL's drop-down does. It stores the value and SIMPL's label (`Plb`). SIMPL 4.32 compiled a module placed this way with 0 errors, and re-saved it byte for byte. SIMPL also keeps one placed without the label, so older programs are fine either way.
- **Changing a placed module's pins:** SIMPL keeps a placed module's wires by **position** within each pin list, not by name. Tested in SIMPL 4.32 with a module wired on every pin, one change at a time:

  | Change to the `.usp` | SIMPL |
  |---|---|
  | none (just recompiled) | compiles as before |
  | pin inserted or appended | "Incomplete Symbols": won't compile |
  | pin type changed | "Incomplete Symbols": won't compile |
  | pin removed | compiles with notice 202; the wires shift, so one signal lands on the wrong pin and another is dropped |
  | two pins swapped | compiles with no message; the wires are on the wrong pins |
  | pin renamed | compiles; the wire stays (fine) |

  **Warnings:** `splus_compile` compares the new pins with the previous build. When they changed, it lists every placed copy in the programs beside the module, with its wiring named by the previous build and a ready re-place. This is the only way to catch swapped pins. `find_problems` reports `SA-MODULE-CHANGED` when a placed copy's pin counts or types no longer fit (0 false alarms on 365 placed modules in the corpus). `show_symbol` and `compile_program` say so too.

  **The fix:** `remove_symbol` and `add_module` with `connect` by name in one `apply_edits`. SIMPL compiled both re-placed test programs as predicted and re-saved them byte for byte. When SIMPL has marked a module incomplete, it also marks every folder above it; `remove_symbol` clears those marks once nothing incomplete is left, as SIMPL does.

### M7: Touch panels ✅ (2026-11-25)

- **Source:** the join map that CH5 Agent, a separate personal tool, writes for the CH5 panels it generates (`joins.json`: each join's type, number and SIMPL signal `in`/`out`, the XPanel's IP ID, and joins with no SIMPL name yet). VT Pro-e and Construct files aren't read.
- **`check_panel_joins`** finds the panel, XPanel or EISC at the map's IP ID (or takes a symbol) and compares each join direction:
  - **ok**, **missing** (nothing wired) or **different** (another signal);
  - **joins the panel uses without a SIMPL name**, and what the program has on them;
  - **joins the program wires that the panel doesn't use** (information only).

  It returns a ready `wire_joins` list for the missing ones.
- **`wire_joins {joins_file}`** wires from the map in one edit, filling only empty joins. It refuses one already wired to a different signal and says which, so the user decides; listing a join in `joins` replaces it. Wiring the same map again changes nothing. The history records the joins as wired, not just the file name.
- **Fixes found on the way:**
  - A join list only grows on the side being wired. A public TSW-760 has 32 serial inputs but 18 serial outputs, and rewiring its inputs used to equalise them.
  - A signal a pin lets go of (rewired or disconnected) is removed at the end of the edit when nothing else uses it, as SIMPL drops unused signals on its next save.
- **Proof:**
  - Every wired pin on the panel symbols in the SIMPL 4.3x corpus files reads back as exactly one join, and rewiring each panel from its own joins leaves the file byte for byte.
  - Live in SIMPL 4.32: an RMC3 program with an XPanel 3.0 at IP ID 03, wired from CH5 Agent's test `joins.json`. Its digital, analog and serial joins compiled with exactly the predicted messages and re-saved byte for byte, including after breaking and restoring joins.

### M8: Debugger traces 🔨 (2026-11-25)

- **`read_trace`** reads a log saved by Toolbox's SIMPL Debugger (Logging > Save Current or Start Logging, a `.txt` in `Documents\Crestron\Toolbox\SIMPL Debugger Logs` by default). It returns:
  - every signal change, event (SIMPL+ `Trace()` output, console data, user stimulus) and timestamp, filtered by `query` and paged;
  - a per-signal summary: number of changes, first and last time, last value.
- **With the program,** it adds each signal's type and lists traced names the program doesn't have (another version, or another program on the processor). Module signals (`::` prefix) are counted separately.
- **`signal`** shows each change of one signal with the symbols that drive it in the program, and the last value the trace showed on each of their inputs. That's evidence for "why did this change"; SIMPL Agent doesn't evaluate the logic, and modules are opaque.
- **The layout is inferred, not yet seen.** No saved log was available, and making one needs a running processor, which SIMPL Agent never touches. The line shapes come from the Debugger's own format strings in `SIMPL Debugger.ocx` (`$time: $signame -> $sigvalue`, `$time: [$type] : $msg`, `*** Timestamp n`, four time formats). They're backed by the Toolbox help's screenshots (digital values as 0/1) and a 2017 MIT-licensed log parser's example line. Any line that doesn't fit is counted and shown, so the first real log will say whether the parser is right.
- **Privacy:** traces are client data, like programs. The audit log records the trace's path, never its content.

### Later

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
.venv\Scripts\python -m pytest -m "corpus or not corpus"   # all 193 tests (corpus tests need the local corpus)
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
| `src/simpl_agent/compile.py`, `splus.py` | `compile_program`, `splus_compile` |
| `src/simpl_agent/live.py` | The live link: `simpl_open`, `simpl_save`, automatic reload |
| `src/simpl_agent/server.py` | The MCP server and audit log |
| `tools/` | Corpus download, format measurements, device proofs and slot rules (`build_slot_rules.py`), `simpl_gui.py` (drives SIMPL's window for proof rounds), SIMPL test-file builders, compile task setup |
| `docs/format.md` | Everything measured about the file format, and every SIMPL 4.32 result |

## Licence

No licence has been chosen yet. All rights reserved.
