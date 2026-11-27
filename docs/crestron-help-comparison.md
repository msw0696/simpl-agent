# SIMPL Agent against Crestron's SIMPL Windows help (2026-11-27)

Crestron's own documentation for SIMPL Windows, read and compared with what SIMPL Agent does.

**Source:** `SIMPL_Windows.chm`, installed with the Crestron Device Database (`Cresdb\Help`), unpacked locally with `hh.exe`. That's 4,168 pages, most of them per-device. Read in full for this comparison:
- Compiler Errors (105 pages);
- Signal Operations, Symbol Completeness, Definitions, the SIMPL Primer and programming tips;
- User Modules, Smart Objects and the GUI Extender (Smart Graphics and CH5) pages;
- Working with Program Files and Program Settings.

Page titles are cited; nothing is copied from the help. SIMPL's behaviour was checked live in SIMPL 4.32 where noted.

## Where SIMPL Agent already agrees
| Topic (help page) | What the help says | SIMPL Agent |
|---|---|---|
| Signal Types | A signal's type comes from what drives it. Digital signals shouldn't have two drivers, except system inputs (panel presses) and Buffer outputs. | Second digital drivers are refused (LGCMCVT220) except between symbols the library marks shareable: Buffers, and panels through `SymJam`. **Live check:** two XPanels driving one press signal compiled with no warning, as predicted. |
| Naming Signals | `0` (any type) and `1` (digital) are constants. `LOCAL` is reserved. | Built-ins aren't driven or renamed, and `LOCAL` is refused. |
| Disable Compiler Warnings, Special Signal Name `//` | `//`-prefixed signals give no "no source" or "no destination" message. Each plain `//` becomes its own placeholder. | `find_problems` never reports `//` signals. Unused required module pins go on SIMPL's `//__…_reserved__` placeholders. |
| Make Symbol Complete | Devices use "random completeness" (any pin may be empty). Logic symbols and modules use "list completeness" (every pin, except `[bracketed]` ones). Buffers need an output for each input. List parameters can't be filled automatically. | Same rules: `add_symbol` requires every pin, `add_module` fills unused required pins with placeholders, device pins may stay empty, and drop-down parameters must be chosen. |
| Updating an Existing Module's I/O | SIMPL keeps programming "based on I/O position". New pins belong at the end; removed ones become `[~Unused2~]`/`[~Unused3~]`. | Matches the M6 live tests (wires kept by position). `splus_compile` and `find_problems` warn, and the fix is re-placing by name. |
| Data Integrity Error Lookup (129) | A signal not connected to any symbol is an integrity error. | `apply_edits` removes signals an edit leaves unused, as SIMPL does on save. |
| Program Open Error Lookup (143) | Two devices with one handle is an error. | Structural checks refuse any edit that would create duplicate handles or broken references. |
| Compiler Errors 102, 103, 220 | Codes and wording. | Predicted exactly. Checked against SIMPL 4.32 compiles in every round. |

## Fixed today because of the help
- **Signal names** (Naming Signals): `,` `:` `;` and `\` aren't allowed, and SIMPL turns a space into `_`. SIMPL Agent used to accept all of these; now it refuses them. Every signal name in the 380 public programs already fits.
- **Program ID Tag** (Edit Program Header): letters, digits, `-` and `_` only. `set_program_header` now enforces this; all 294 corpus tags fit.
- **GUI extender files** (Importing GUI Extenders; GUI Extender Error Lookup 285/286/313–316): SIMPL opens a program from its own copy of the imported file, `<name>.sgd_` or `<name>.chd_` in the program folder. Without the file, it comments out the panel's extenders.
  - SIMPL Agent now reads that copy first.
  - `find_problems` reports `SA-GUI-FILE-MISSING` (checked live: without the copy, SIMPL reported "Problems Loading Program") and `SA-GUI-FILE-CHANGED` (SIMPL will offer to sync).
- **Module targets** (SIMPL/SIMPL+ Modules Targeting 4-Series; Warning 153): SIMPL only adds a module built for the program's control system, and comments out one that isn't.
  - A compiled SIMPL+ header lists its targets in `Inclusions_CDS` (6 = 3-Series, 7 = 4-Series). That's the same numbering as the processor's `RackClass` in the device library.
  - `add_module` now refuses a mismatch and says which target to recompile for, and `module_details` shows `compiled_for`. All 365 placed SIMPL+ modules in the corpus fit.
- **Panel extenders** (GUI Extenders Data Management; Hierarchy of CH5 Extenders): Smart Graphics objects and CH5 contract components now show their real pin names.

## Gaps: what SIMPL reports that SIMPL Agent doesn't predict
Ordered by how useful a prediction would be.

1. **Parameter values** (Compiler Errors 105–108, 125):
   - escape-sequence mistakes in string parameters (`\x` with one hex digit, a lone `\` at the end, invalid `\` codes);
   - analog values beyond 65535, 100%, FFFFh or 582s.

   `set_parameter` and `add_symbol` take any one-line value today. **Recommendation:** validate parameter values with the same rules. The 2026-11-25 drop-down test hit 107 and 236 from a backslash, so this is real.
2. **Incomplete symbols** (160; Make Symbol Complete): SIMPL refuses to compile, and only reports the symbol once it has saved it (`CF=1`). `find_problems` reports `CF=1` already in the file (`SA-INCOMPLETE`), and SIMPL Agent's own edits never leave pins empty. But it can't predict completeness for symbols edited elsewhere. **Recommendation:** a completeness check (list completeness, brackets optional, Buffer pairs) to name the symbol before SIMPL does.
3. **Module messages** (124, 126, 127, 135, 213): undefined module inputs, signals inside a macro with no source or destination, "module re-sync required", and "symbol definition changed since saved". `SA-MODULE-CHANGED` covers part of 135 and 213 for SIMPL+. Signals inside macros (126/127) are never predicted. **Recommendation:** predict 126/127 by applying the 102/103 rules inside each placed macro; the macro's file is already read for pin names.
4. **Capacity** (130–133): too many digital or analog signals, or too much NVRAM or program size, for the processor. That needs per-processor limits, which the help doesn't give. **Not recommended** without a source for the limits.
5. **Reserved and typed signals** (140, 162, 166, 177, 179): `LOCAL` is already refused. Signals without a definite type (`Recompute Signal Types`) can't arise from SIMPL Agent's edits, since every new signal gets a type. No action needed.
6. **Hardware messages** (113–117, 119, 129, 143, 154, 157, 158, 181–183): IR files, serial settings, RF gateways, CNX front panels, simulated NVRAM and clock. They're outside SIMPL Agent's edits, so no action is needed. IR drivers are already refused.

## Concepts SIMPL Agent doesn't model yet
- **Commented-out symbols** (Commenting Out Symbols): the compiler ignores them, and SIMPL asks "Commented out Symbols and/or Devices" when compiling (`compile_program` answers it). How they're stored isn't known: none of the 380 public programs has one. **Recommendation:** one live test (comment a symbol out, save, diff), then exclude such symbols from `find_problems`.
- **Logic waves and logic solutions** (Definitions: Logic Wave/Logic Solution): each symbol takes one logic wave, except time-based ones (Delay, One Shot). `read_trace` orders a trace's events by line and doesn't reason about waves. That's fine for its evidence-only explanations.
- **Resync and GUI-extender sync dialogs** (Resync Project, Matching Unmatched GUI Extenders): SIMPL Agent never resyncs. It warns (`SA-MODULE-CHANGED`, `SA-GUI-FILE-CHANGED`) and leaves the sync to the user in SIMPL.
- **CH5 extenders only on TSW-xx60** (GUI Extenders Data Management): the help says CH5 GUI extenders are currently supported only on TSW-xx60 touch screens. That matters if contracts are used with an HTML5 XPanel (see CH5 Agent's guidelines report).

## Also found while checking
- **Line endings:** corpus copies made by git have LF line endings, and SIMPL opens them only after a bare "File Error". Copies used for live tests must be converted to CRLF. SIMPL Agent's write gate already requires CRLF.
- **LibraryProgram:** the public Smart Graphics program behind the old `find_problems` gap can't be fully rebuilt from its repo. Its SIMPL# library isn't a valid assembly, so its SIMPL+ module stays incomplete. Its 40/42 messages from the earlier round remain unexplained.
