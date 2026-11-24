# SIMPL Windows file format: what we've measured

*Built from SIMPL's own saved files only. Every rule below was checked against the corpus with `tools/corpus_check.py`. "Holds" means zero exceptions.*

**Corpus (2026-11-24):**

| Source | Files | Saved by |
|---|---|---|
| Crestron macros installed with SIMPL (`Cresdb\Modules\*.cmc`) | 3,449 | SIMPL 2.00 to 4.30 |
| Public `.smw` programs from GitHub | 380 from 144 repos | SIMPL 1.40 to 4.32; 17 by 4.32 |

The corpus files stay where they are or in `C:\Users\matth\simpl-corpus\`. None are copied into this repo.

## 1. File container (holds for all 3,829 files)
- **Encoding:** latin-1.
- **Records:** each is a line `[`, then `Key=Value` lines, then a line `]`. A value can contain `=`, so split on the first `=` only. A value can be empty.
- **Line endings:** SIMPL writes CRLF; all 3,449 macros use it. 244 of the GitHub files use LF because git converted them. Treat CRLF as the truth.
- **End of file:** 18 macros have no line break after the last `]`.
- **First record:** `Version=1`, with no `ObjTp`.
- **Repeated keys:** a key can appear twice in one record (`Symbol.CDSReleaseStatus`), so keep lines as an ordered list, not a dict.
- **Round trip:** `rawfile.parse(data).to_bytes() == data` for every file.

## 2. Record types
| ObjTp | Meaning | Key fields |
|---|---|---|
| `FSgntr` | File signature | `Sgntr` (`SimplWindow` for a program, `CresMacro` for a macro), `RelVrs`, `SavedBy`, `MinSMWVrs` |
| `Hd` | Header | `CnH` (processor device handle), `CnC` (processor device code), `S0Nd/S1Nd/SLNd`, `PrNm`, `DbVr`, `DvcDbVr`, `PgmNm`, `DlrNm`, `CltNm` |
| `Dv` | Device (processor, cards, slots, IP and Cresnet devices) | `H` (can be a range), `PrH`, `C1..`, `mC`, `Ad`, `DvC`, `SmH`, `SlC` |
| `Sm` | Symbol (logic, device symbols, folders, macros, SIMPL+) | `H`, `SmC`, `Nm`, `PrH`, `C*`, `I*`, `O*`, `P*`, `mI/mO/tO/mP/mC`, `n1I/n2I/n1O`, `DvH`, `Cmn1` |
| `Sg` | Signal | `H`, `Nm`, `SgTp`, sometimes `SgTf` or `Fx` |
| `Symbol` | A macro's own symbol definition (`.cmc` only) | `NumFixedInputs`, `InputCue*`, `OutputCue*`, `ParamCue*` |
| `Dp` | Parameter definitions (`.cmc` only) | `Nt*`, `DV`, `LR/HR` |
| `Bk`, `Bw` | Bookmarks and window positions | Layout only |
| `Et`, `EtU`, `Cs`, `Cm`, `Db`, `SrU`, `CrU` | Ethernet, Cresnet, COM and database details for a device | All have `DvH` |
| `VTP`, `CED`, `CHD`, `Pn`, `Ui`, `FP`, `FusionGUID` | Panel projects, SIMPL# and other extras | Not studied yet |

**Order:** each record type appears in one unbroken run (holds). A program's usual order is `Version FSgntr Hd Dv Cm Db Cs FP Bk Bw Et [VTP] Sm [CED] Sg`.

## 3. Handles
- **Uniqueness:** `Sm.H` and `Sg.H` are integers, unique within their type, and records are sorted by `H` (all hold).
- **Built-in signals:** `S0Nd=1`, `S1Nd=2` and `SLNd=3` (holds). Handles 1, 2 and 3 are the built-in `0`, `1` and `Local` signals and have **no** `Sg` record (holds). Every real signal handle is greater than 3.
- **Device handles:** a `Dv` handle can be a list of ranges, e.g. `7.258` or `515,551.553`. A range is one record covering several empty slots. Expanded, device handles are unique (holds).
- **Gaps:** both symbol and signal handles have gaps, which suggests SIMPL doesn't renumber after a delete.

  | | Symbol-handle gaps | Signal-handle gaps (not counting built-ins 1–3) |
  |---|---|---|
  | Macros (3,449) | 2,055 (60%) | 2,520 (73%) |
  | Programs (380) | 162 (43%) | 238 (63%) |

  **How SIMPL picks a new handle is not yet known.** Use max+1 until a 4.32 re-save shows otherwise.
- **Processor:** `Hd.CnH` is the processor's `Dv` handle and `Hd.CnC` equals that device's `DvC` (both hold). The processor's `PrH` is always `1`, which has no `Dv` record.

## 4. Symbols (`Sm`)
- **Library code:** `SmC` is the symbol's code in `symlib.tio`. Every `SmC` in the corpus exists in the installed library (364,217 of 364,217). Common codes:
  - 20 Buffer;
  - 155 macro;
  - 103 SIMPL+ module;
  - 55 Argument Definition;
  - 156 folder;
  - 157 top-level tree node.
- **Folders:** a folder is `SmC=156`.
  - **The root:** every program has one root `Logic` folder (`Nm=Logic`, no parent), plus four 157 nodes (`Central Control Modules`, `Network Modules`, `Ethernet`, `DefineArguments`). This holds in 3,828 of 3,829 files (`Central Control Modules` in 3,826).
  - **Other folders:** `Nm` is `SUBSYSTEM` or missing. **The folder's name is in `Cmn1`**, sometimes ending in `\`.
  - **Keys:** `ObjTp H SmC [Nm] [ObjVer] [SmVr] PrH CF Cmn1 mC C*`. A folder with no children has no `mC`.
- **Wiring:**
  - `I<n>` and `O<n>` hold signal handles and always resolve to a signal (holds, across 4.3 M references).
  - Pins are **sparse**: a missing `I<n>` means pin n is unconnected.
  - `P<n>` holds literal parameter text such as `5s`, `23d` or empty. Parameter pins run 1..`mP` with no gaps, with 3 exceptions, one in each of three QM-MD7x2 macros.
- **Pin counts:**
  - The highest `I` index is at most `mI` (holds).
  - The highest `O` index is at most **`tO`** (holds). It can be above `mO` (1,101 exceptions), so `tO` is the output count to trust.
  - `tO` and `mO` differ on 0.5% of macro symbols (1,407 of 266,207) and 12.5% of program symbols (4,573 of 36,470).
- **Compiler messages:** the `smpc` test files show SIMPL's two softer categories.
  - A **warning** is a signal on an input that nothing drives.
  - A **notice** is a signal on an output that nothing uses.
- **Simple logic symbols:** these are library symbols with `Smpl-C=1`, `DeviceCode=0` and one pin list (OR, AND, Buffer, One Shot, Toggle, Interlock and others).
  - **Counts:** `n1I == mI`, `n1O == mO` and `mO == tO`, with 118 + 2 exceptions in 254,028 symbols.
  - **Record:**
    ```
    ObjTp=Sm H SmC Nm=<library name> ObjVer=1 [SmVr] PrH CF=2 [n1I] [n1O] [Cmn1..n] [mI I*] [mO tO O*] [mP P*]
    ```
    A count of zero leaves out its keys.
  - **Proof:** `edit.simple_symbol_lines` rebuilds **every one of the 1,360 simple symbols in 4.3x files exactly**. That covers 126 of the 201 simple symbol types in the library; `add_symbol` only builds those 126 (`catalog/verified_simple_codes.json`). 34 of them also carry window-state flags (`OpF`, `PropF`, `HandF`) that new symbols don't need. This is the `test_simple_symbols_regenerate_exactly` corpus test.
- **`SmVr` is per symbol:** a freshly placed symbol gets the header's `SmVr`; older symbols keep an older value or none.
- **`CF` is the "complete" flag:**
  - `2` means complete (99.6% of symbols);
  - `1` means incomplete; its parent folders are marked `1` too;
  - missing on 1,400 symbols (older saves).
  - **Evidence:** the public `smpc` project's `incomplete.smw` test file. In the corpus, `CF=1` only occurs with an empty pin.
  - **Which pins are required depends on the symbol:** 54,716 complete symbols have an empty input (Toggle, One Shot, Interlock and others). New symbols from `add_symbol` are fully wired and get `CF=2`.
- **Comments:** a comment can span several keys (`Cmn1`, `Cmn2`, ...).
- **Tree:** `PrH` and `C*` agree both ways (holds across 345 K links). `C*` runs 1..`mC` with no gaps (holds).
- **Devices:** a symbol's `DvH` resolves to a device, and that device's `SmH` points back to the symbol (holds).
- **Key order:** one consistent order exists. Across every `Sm` and `Sg` record, no pair of keys ever appears in both orders. `Sg` is `ObjTp H Nm [SgTp] [SgTf] [Fx]`.

## 5. Signals (`Sg`)
- **Type (`SgTp`):**
  - missing means digital;
  - `2` is analog;
  - `4` is serial.
  - **Hypothesis: it's a bit mask.** `1` would be digital, `2` analog, `4` serial, `6` = 2|4 (analog or serial) and `31` = all bits ("any type", not yet fixed). `31` mostly sits on pins the library types as `Any`, and `6` on `Serial` or `Analog|Serial` pins, which fits.
  - **Caution:** comparing `SgTp` with the library's per-pin types is noisy, because pin types depend on variable pin lists. The "missing = digital" rule fits the 4.32 samples but isn't proven.
  - `SgTf` and `Fx` are unknown.
- **Names:** unique within a file, ignoring case (holds).
  - **Characters:** printable ASCII only, never starting with a digit or space, no leading or trailing spaces. Lengths go up to about 130.
  - **New names:** SIMPL Agent also refuses names over 100 characters.
- **Placeholders:** names starting with `//` (e.g. `//__digital_reserved__`) can be on many outputs at once.

## 6. "Driven by more than one output": an open question
A simple rule ("each signal has at most one driver") is wrong. It flags most valid files. After the exemptions below, these remain:

| Source | Signals with SIMPL+ or a macro among the drivers | Signals with plain symbols only |
|---|---|---|
| GitHub programs | 2,062 | 230 |
| Installed macros | 5,064 | 1,510 |

**Exemptions applied:**
- the built-in signals;
- `//` placeholders;
- analog and serial signals (SIMPL lets these have several drivers);
- outputs of Argument Definition (SmC 55);
- symbols that `symlib.tio` marks `SymJam=NonExclusive` (Buffer, touch panels, Analog Equate and others).

**What's left:**
- Mixes of SIMPL+ and Buffer.
- Macros and panels together.
- `Interlock` on its own.
- `Logic Wave Pulse` with `Multiple One Shots`.
- Two `OR` gates.

**Measured so far:**
- In 1,739 of 1,740 plain cases the drivers are **different** symbols.
- Their `CF` and `ObjVer` look like everyone else's.
- Treating `CF != 2` (or a folder with `CF != 2`) as disabled clears only 186 cases. So "disabled symbols" is not the explanation.

**Settled by SIMPL 4.32 (2026-11-24, test file `03-two-drivers`):** an OR and an AND both driving `test_out` loads and compiles with **0 errors**. SIMPL gives 3 warnings (`test_a`, `test_b`, `test_out`) and 1 notice. Two drivers on a digital signal is a **warning**, not an error. `check_program` reports it as a warning, and `edit_program` still refuses to create one unless asked.

## 7. SIMPL 4.32 reload and compile results (2026-11-24)
| Test | Result |
|---|---|
| `00` control (empty CP4N) | 0 errors, as predicted. |
| `01` add OR plus 3 signals | 0 errors, 2 warnings, 1 notice, as predicted. **SIMPL's re-save wrote our new records back byte-for-byte**, apart from bumping `SmVr` 1230 → 1247, which it does to every symbol. |
| `02` rename | Same messages as 01, with the new name, as predicted. |
| `03` two drivers | 0 errors, 3 warnings, 1 notice (see section 6). |
| `10` control (public PRO3 demo) | 0 warnings and 0 notices. |
| `11` rename a signal in `10` | 0 warnings and 0 notices, as predicted. After both are re-saved, **the only differences from `10` are the new name and the file name.** |

**The M0 gate is passed:** all six files behaved as predicted. Every edited file, once re-saved by SIMPL, differs from its re-saved control only by the intended change.

**SIMPL's compiler messages, word for word (from `03`):**
```
WARNING(LGCMCVT220) ** Signal "test_out" on symbol S-2 has a previously defined driving source.
WARNING(LGCMCVT102) ** Signal "test_a" has no driving source.
NOTICE (LGCMCVT103) ** Signal "test_out" has no destination.
```
- `S-2` is the AND, the second symbol in `Logic`. "S-n" seems to be the symbol's position in its folder, not its handle (#22).
- `check_program` will use the same codes and wording: LGCMCVT220 for a second driver, LGCMCVT102 for no source, LGCMCVT103 for no destination.

**What SIMPL changes on re-save** (from the `00` control):
- `RelVrs`, `PrNm` (the file name), `DbVr` and `DvcDbVr`.
- Every `SmVr` and `DvVr` is bumped to the running version.
- Nothing else changes, and line endings stay CRLF.
- `SavedBy` stayed 4.30 on the empty program but changed to 4.32 on the PRO3 demo. It may only change when SIMPL alters content.
- **SIMPL can renumber handles on save.** Upgrading the older PRO3 demo (processor `ObjVer` 6 → 7) moved records and renumbered device handles (the `C*` lists changed) and symbol handles. It also dropped one `Db` record and moved a `Cm` record's settings.
  - **Handles are not stable across a SIMPL save.** After SIMPL saves, re-read the file before any further edit, and never replay old handles blindly. `reapply` must find symbols and signals again by name or position.

## 8. Still to learn
**From the F12 test set (`tools/make_f12_samples.py`):**
- Whether SIMPL 4.32 loads and compiles our records without complaint (files 01, 02, 11).
- What SIMPL changes when it re-saves a file we wrote. Both bases were saved by 4.30, so a 4.32 save rewrites version fields everywhere. Compare re-saved `01` with re-saved `00`, and `11` with `10`, not with `_as_written`.
- The two-drivers question.

**Still unknown:**
- `ObjVer` (always `1` on simple symbols), `n2I`, `SgTf`, `Fx`, and `SgTp` 1, 6 and 31.
- Which pins each symbol requires (what makes `CF=1`).
- How devices are added (M4).
