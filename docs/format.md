# SIMPL Windows file format: what we've measured

*Built from SIMPL's own saved files only. Every rule below was checked against the corpus with `tools/corpus_check.py`. "Holds" means zero exceptions.*

**Corpus (2026-11-24):**

| Source | Files | Saved by |
|---|---|---|
| Crestron macros installed with SIMPL (`Cresdb\Modules\*.cmc`) | 3,449 | SIMPL 2.00 to 4.30 |
| Public `.smw` programs from GitHub | 380 from 144 repos | SIMPL 1.40 to 4.32; 17 by 4.32 |

The corpus files stay where they are or in `~/simpl-corpus/` (see `tools/fetch_github_corpus.py`). None are copied into this repo.

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
- **Comments:** a comment can span several keys (`Cmn1`, `Cmn2`, ...). They are **one continuous text**: a two-backslash line break can be split across keys.
  - **Line breaks:** two backslashes (`\\`), found in 21,803 of 36,513 comments.
  - **Suffix:** 161 comments end in `||1` (meaning unknown).
  - **Folder names:** a folder's name is the first line of its comment.
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
- `S-2` is the AND, the second symbol in `Logic`. **SIMPL numbers symbols by path** (confirmed in round 2): `S-2.3` is the 3rd symbol in the folder that is 2nd in `Logic`. It is not the handle. `analysis.simpl_number` computes it.
- `check_program` will use the same codes and wording: LGCMCVT220 for a second driver, LGCMCVT102 for no source, LGCMCVT103 for no destination.

**What SIMPL changes on re-save** (from the `00` control):
- `RelVrs`, `PrNm` (the file name), `DbVr` and `DvcDbVr`.
- Every `SmVr` and `DvVr` is bumped to the running version.
- Nothing else changes, and line endings stay CRLF.
- `SavedBy` stayed 4.30 on the empty program but changed to 4.32 on the PRO3 demo. It may only change when SIMPL alters content.
- **SIMPL can renumber handles on save.** Upgrading the older PRO3 demo (processor `ObjVer` 6 → 7) moved records and renumbered device handles (the `C*` lists changed) and symbol handles. It also dropped one `Db` record and moved a `Cm` record's settings.
  - **Handles are not stable across a SIMPL save.** After SIMPL saves, re-read the file before any further edit, and never replay old handles blindly. `reapply` must find symbols and signals again by name or position.

### F12 round 2 (2026-11-24, `tools/make_f12_round2.py`)
Each file started from the same empty CP4N program. **SIMPL printed exactly the messages `find_problems` predicted**, apart from the S-number in `24`.

| Test | Result |
|---|---|
| `21` two Buffers drive one digital signal | No LGCMCVT220. **Buffers (SymJam=NonExclusive) may share an output.** |
| `22` two Analog Initialize drive one analog signal | No LGCMCVT220. **Analog signals may have several drivers**, even from symbols that don't share outputs. |
| `23` `//spare_out` goes nowhere, `//spare_in` has no source | Neither is reported. **`//` signals are exempt** from LGCMCVT102 and LGCMCVT103. |
| `24` a second driver, 3rd symbol inside folder `Sub` (2nd in Logic) | SIMPL said **S-2.3**, where we predicted S-3. SIMPL numbers by path; this is now fixed. All other messages matched. |

**SIMPL's re-saves of all four** differed from what we wrote only in version stamps. That includes the new folder record from `add_folder` and the Analog Initialize records.

### Round 3: a live edit with SIMPL open (2026-11-24)
The program was a copy of `test01`. Matthew made a change in SIMPL and saved; then SIMPL Agent edited the file while SIMPL had it open. The edit added folder `Room A`, an AND inside it, and renamed `test_or` to `room_a_any`.

- **No unsaved-changes marker.** SIMPL 4.32 shows nothing readable while it has unsaved changes. The title, the child windows and the files on disk don't change, and the File menu's state is only refreshed when the menu opens. So `apply_edits` asks for the user's confirmation that they saved (`user_confirmed_saved`) whenever SIMPL has the file open.
- **"Commenting out" a signal on a pin renames it to `//name`.** SIMPL wrote a new `Sg` record with handle **max+1** (7, not the free 5), re-pointed the pin to it, and **dropped the old signal now that nothing used it**. Both match what the editor does.
- **No lock.** SIMPL doesn't lock an open program, so SIMPL Agent's atomic write succeeded with SIMPL open.
- **SIMPL notices the change and offers to reload.** Matthew clicked Yes. The new folder and AND appeared, and F12 gave exactly the predicted messages:
  ```
  WARNING(LGCMCVT102) ** Signal "test_a" has no driving source.
  NOTICE (LGCMCVT103) ** Signal "room_a_both" has no destination.
  ```
- **After the reload, compile and save, the file was byte-for-byte what SIMPL Agent wrote** (same revision).
- **SIMPL's own backup and archive.** SIMPL keeps `<name>.sm2` (the previous version) and `<name>_archive.zip`. The archive holds only the program's files, not `.simpl-agent/`.

### End-to-end test through Claude (2026-11-24)
A fresh Claude Code session, using only the SIMPL Agent tools and skill, was asked in plain English to explain `live.smw`, check it, and add a One Shot in Room A (triggered by `room_a_both`, a 2-second pulse on `room_a_pulse`).

- **Explanation:** correct, including SIMPL's S-numbers and the commented-out `//test_b`.
- **Check:** matched F12 exactly.
- **Edit:** Claude asked Matthew to save in SIMPL first. Its dry run was refused for empty optional pins; it fixed that by wiring them to `0` and the second output to a `//` placeholder. Then it wrote the One Shot at S-2.2.
- **SIMPL's result:** SIMPL offered to reload, and F12 gave exactly the predicted 1 warning and 1 notice.

**New SIMPL fact: autosave.** SIMPL writes `<name>.smw.ASV`, an autosave of its in-memory copy. Here it held the version from before the edit. An `.ASV` newer than the `.smw` and different from it may show unsaved work in SIMPL. That isn't used yet; it needs checking.

### Real job: a public DMPS3-4K-150-C classroom program (2026-11-24)
The program is `bernasbtcnj/crestron` `gpc/dmps3_4k_150_standard.smw`: SIMPL 4.32, 478 logic symbols, 14 macros, 2 SIMPL+ modules, a SIMPL# library and a TSW-760 panel. It was a local test copy only.

- **F12 failed to build modules.** It gave `ERROR (LGCMCVT277)`: Microsoft .NET Compact Framework v3.5 is required, but isn't installed (Crestron Online Help article 1001084). Without it SIMPL can't build the SIMPL# library, so the modules using it (all seven CCI JSON macros), and the program's two SIMPL+ modules, are left out.
- **That error explains every other message.**
  - All 50 LGCMCVT102 warnings were signals driven only by those modules (24 by `CCI JSON DigitalRead`, 16 by `SerialRead`, 3 by `AnalogRead`, 5 by `tcnj_inactivity_timer`, 2 by `tcnj_log`).
  - All 12 LGCMCVT103 notices were signals going only into them.
  - **A compile error makes module pins vanish.** Compare F12 with `find_problems` only after a clean compile.
- **No LGCMCVT220 appeared.** `find_problems` had predicted 9, all involving the Lumens camera macros. **Not settled:** it needs a clean compile, after installing .NET Compact Framework 3.5.
- **Settled the same day.** After installing .NET Compact Framework 3.5 (Microsoft's signed `NETCFSetupv35.msi`, 3.5.7283; Microsoft now offers only localized editions), SIMPL built every SIMPL+ module and **compiled the program with no errors, warnings or notices**. So SIMPL doesn't report LGCMCVT220 when a macro or SIMPL+ module is one of the drivers, and `find_problems` now skips that case. With the fix it reports nothing for this program, matching SIMPL. It's a corpus test (`test_real_job_compiles_clean_like_simpl`).
- **An edit on the real job passed (2026-11-24).** On a copy, one `apply_edits` call made three changes:
  - added folder `Projectors\Status`;
  - added an OR (S-6.29.1) combining both projectors' warming/cooling feedback into a new `Projectors.Any.Busy`;
  - changed the Show Logo pulse (S-3.2.5) from `1d` to `2s`.

  F12 gave exactly the one predicted notice (`Projectors.Any.Busy` has no destination). SIMPL's re-save kept every edited record as written. It only updated version stamps across the whole program, because the job had been saved with an older database (`SmVr` 1244 -> 1247 on 535 symbols, `DvVr` on 169 devices, and new `DbVr`/`DvcDbVr`).
- **The desktop .NET Framework 3.5 is a different product.** The `KB…` package doesn't provide the Compact Framework.
- **The two missing Crestron macros weren't mentioned.** `HD-MD4x1-4K-E v1.0.cmc` and `HD-MD6x2-4K-E v1.1.cmc` aren't in this PC's database, and SIMPL didn't report them in this compile.
- **Module pin names now come from the modules' own files** (`analysis.module_definition`):
  - a macro's `.umc` (or a Crestron `.cmc` in `Cresdb\Modules`) holds a `Symbol` record;
  - a SIMPL+ module's `.ush` header (`.tio` format) holds its pin names;
  - pins past the first list (`n1I`/`n1O`) use the `InputList2Cue`/`OutputList2Cue` names.
- **A pin name can end in `#`.** Module files can have ordinary pin names like that, so a pin's own name must win over the "`#` repeats" rule.
- **User macros (`.umc`)** carry the signature `Sgntr=UserMacro`; Crestron's `.cmc` macros carry `CresMacro`.

### Modules: macros and SIMPL+ (2026-11-24)
How SIMPL 4.3x stores a placed module, measured on every placed module with its definition available (299 macros, 377 SIMPL+), then proven by rebuilding them byte-for-byte (`test_placed_modules_rebuild_exactly`):

- **Key order and stamps:**
  - Key order is `ObjTp H SmC Nm ObjVer PrH CF [n1I] [n2I] [n1O] [n2O] [Cmn…] [mI I…] [mO tO O…] [mP P…]`.
  - There's **no `SmVr`**.
  - `Nm` is the module file name.
  - `CF=2` always, even with empty pins.
- **Macros (`.umc`, `.cmc`):** the counts come from the definition's `NumFixedInputs`, `NumFixedOutputs` and `NumFixedParams`. The definition's pin-name lists can be longer, padded with placeholders like `o1`/`p1`.
- **SIMPL+ (`.ush` header):** each list's size is chosen within `MinVariable…` to `MaxVariable…` (the minimum by default, in 289 of 367). Parameters are `NumFixedParams` + `MinVariableParams`. **`n2O` is never stored**, although list-2 outputs count in `mO`/`tO`. Untyped first-list pins are digital (1,698 of 1,698).
- **Which pins must be wired:**
  - every pin with a **plain name** is wired, in 9,963 of 9,963 cases;
  - `[bracketed]` pins are optional;
  - `[~UNUSED~]` slots are always empty.

  Unused required pins carry SIMPL's placeholders `//__digital_reserved__`, `//__analog_reserved__` and `//__serial_reserved__` (one each, shared). **A module with an unwired required pin stops the compile** ("Incomplete Symbols"; seen in round 4).
- **Parameters:** placeholder slots (`[~UNUSED~]`, `[Reference Name]`) are always empty, and real parameters are always set (2,151 against 1).
- **Pin groups:** modules whose pins are grouped (`[~BeginGroup~]`) get per-pin `GrpStI`/`GrpStO` when SIMPL saves them (13 of 13). This is display state: a Philips Hue Bridge placed without it compiled with 0 errors.
- **Drop-down parameters (SIMPL+, checked 2026-11-25):**
  - **Where the options live:** `propList` compiles to a `Dp` record per parameter in the `.ush`: `H=n` is parameter n (`H=1` is the Reference Name), `DV` is the default, and `VN`, `Val<i>` and `Lbl<i>` are the options. This holds for 37 of 37 placed list parameters in the corpus. The parameter's cue carries its values (`ParamCue2=Mode,0d,1d,2d`, `ParamSigType2=List`), so the name is the part before the first comma.
  - **What SIMPL stores:** `P<n>` holds the option's value. `Plb<n>`, right after it, holds its label (14 of 14).
  - **`Plb` is optional:** 4.3 saves have both forms (19 placed modules without, 2 with it on every list parameter, defaults included). SIMPL 4.32 re-saved a module placed **without** `Plb` byte for byte, and one **with** `Plb` byte for byte, and compiled both with 0 errors. So SIMPL neither adds nor drops it. `add_module` writes it, which is the form that shows the label in SIMPL.
  - **Stale labels:** a label can be out of date when the module was recompiled after placing (Date v1.0's `Plb10`). SIMPL keeps the old label.
  - **Macros** (`.umc`/`.cmc`) have `Dp` records with options too, but their `H` doesn't map to `P<n>` the same way (a File Reader's `P3` holds a file name against a list of file types). They're placed as before, with the value only and no label.
  - **Changed modules (2026-11-25):** the placed record stores no pin names, only positions. On load SIMPL 4.32 never renumbers or rewires it. Tested with a module wired on every pin, one change per program:
    - **Unchanged (just recompiled):** compiles as before.
    - **Pin added (inserted or appended), or a pin's type changed:** "Problems Loading Program", then "Incomplete Symbols" with no compile. A save writes `CF=1` on the module and on every folder above it, and changes nothing else.
    - **Pin removed:** compiles with notice 202, "Number of inputs on symbol [... : S-1 : X.usp] needed adjustment". The list is cut from its end: the removed pin's signal stays on its position (now the next pin) and the last signal of that list is dropped. A save writes nothing new.
    - **Swapped or renamed:** compiles with no message; the save is byte-identical.
  - **Re-placing:** `remove_symbol` + `add_module` (wired by name) in one edit compiled as predicted and re-saved byte for byte. That held from the incomplete state (insert), the silent one (swap), and the full loop for a removed pin (`splus_compile`'s `re_place_with` applied as given).
  - **Detecting it:** a placed copy whose per-list pin counts fall outside the `.ush`'s `MinVariable…`..`MaxVariable…` (plus `NumFixedParams`), or which has a wired signal of another type than its pin, gets `SA-MODULE-CHANGED`. 0 of 365 placed SIMPL+ modules with headers in the corpus are flagged. Swaps and renames leave no trace, so `splus_compile` compares the pin lists of the old and new `.ush` instead.
    - **Folder marks:** SIMPL clears a folder's `CF=1` once nothing incomplete is left inside it. No corpus folder (0 of 7,547) is marked without an incomplete symbol inside it, and 18 of 18 marked folders have one.
  - **Backslashes in string values:** the test module's list value `\user\` drew SIMPL warning LGCMCVT236 ("Illegal unicode constant") and notice LGCMCVT107, because SIMPL reads `\u` in a parameter string as an escape. That comes from the module's text, not from placing it.

### F12 round 4: automatic compiling (2026-11-24)
Compiles now run unattended. `smpc` v0.2.0 (MIT, Norgate-AV/smpc; checksum verified; source reviewed: no network, no registry, only closes the SIMPL it starts) runs from an elevated scheduled task, `\SIMPL Agent\Compile`, installed once under `C:\Program Files\SimplAgent`. The task only compiles a `.smw` under the allowed folders. `compile_program` uses it. A compile takes about 40 to 70 s.

- **`42-classroom`:** the classroom copy, plus the `tcnj_wolfvision_v1` macro and the `PTZCameraCalMod` SIMPL+ module placed by `add_module`, with unused required pins on placeholders. **0 errors, exactly the 3 warnings and 4 notices predicted.**
- **`40/41-hue`:** the public Philips Hue program shipped without `.ush` headers. SIMPL+ files can be compiled without administrator rights by `SPlusCC.exe \rebuild <file.usp> \target series4`, which writes the `.ush`. But the recompiled modules changed pin counts against the macros' saved instances, so SIMPL warns "Number of inputs ... needed adjustment" (codes 202/205) and reports signals inside the macros. Not a clean comparison. The Bridge placed without `GrpSt` compiled with 0 errors.
- **A compile doesn't save** the file unless SIMPL asks, so the revision stays the same.

### Adding a device (M4, 2026-11-24)
Decoded from a SIMPL 4.32 save of an empty CP4N (`tests/data/dev-step0.smw`), then a TSW-1070 at IP ID 03 (`dev-step1`), then an EISC at 04 (`dev-step2`). `add_device` (`smw/device_edit.py`) rebuilds both saves byte for byte. Only the header's `PrNm`, the file name, differs.

- **One record holds every free address.** All free slots of a type on a network share one record, gaps and all (`Nm=P4Ethernet H=264,266.275,277.513`; 259 of 259 corpus networks). The slot at the chosen address leaves it, keeps its handle and gets `mC=1 C1=<device>`. Dv records stay sorted by first handle (holds in every corpus file), so taking the first free address moves the free record below the used one.
- **Round 6 (SIMPL 4.32 re-saves):** SIMPL opened, accepted and re-saved our files. `dev-a` has panels at 03 and 10 and EISCs at 05 and FE; a public program had a gapped range plus an EISC at 0A. Our first version split the leftover free addresses into several records; SIMPL merged them back into one, which led to the rule above. With that fixed, both rebuilds match SIMPL's re-saves byte for byte, apart from `PrNm` and one `Pin=True` display key that SIMPL keeps or drops on its own. Container child order and handle numbers are as written and kept on re-save; their rule comes from the corpus. **Compiles:** `dev-a` 0/0/0; LibraryProgram gave the same 0 errors, 40 warnings and 42 notices with and without the added EISC.
- **The device's Dv record:** handle max+1, `Nm`/`DvC` and `ObjVer` (default 1) from iodev, `DvVr` like its slot, `Ad`, `SmH`, `RelStat` = `CDSReleaseStatus` (default `Release`), `ProdLine` = `CDSProdLine` if any, then `DbH`, `EtH` and `mC/C*`. A device directly on a network slot has no `SlC`; a device in a fixed slot carries its slot's `SlC`.
- **Fixed children** (`Expand<n>=FixedSlot`, `Fixed<n>=<device>`): a `FixedSlot` record (`SlC=144`, `Ad=01`), then the child device, with consecutive handles after the parent.
- **Companions:** `Db` (`Whc=3 Mnf=Crestron Mdl=<name>`) for the device on the network. `Et` (`IPM=255.255.255.0 IPA=<DefaultIP>`) only when iodev gives a `DefaultIP` (the TSW has one; the EISC doesn't). Record-type order in the corpus: `Dv, Cm, Db, Cs, Bk, Bw, Et, VTP, Sm, Sg`.
- **Logic symbols:** one per device (`SymbolCode`), `Nm` = the symbol library's `Name`, `ObjVer` from there (default 1), `SmVr` from the header, `Cmn1` = the device's name. The network's symbol (e.g. `CP4N Ethernet Devices`) lists them in address order (1,729 of 1,732 corpus containers). A fixed child's symbol sits under its parent's.
- **Pin counts:** each of the three pin lists is `MinVariable<Inputs|Outputs><List2|List3>` if given, else `Expand_by` when the list exists. Only `n1I`, `n2I` and `n1O` are stored (zeros left out); `mI` is every input, `mO` is output lists 1+2, and `tO` is every output. The same rule reproduces every list-sized built-in symbol of the CP4N (System Monitor 28/42/3 in, 25/44/3 out gives mI=73, mO=69, tO=72). A `PermanentStringSize` parameter defaults to `255d`.
- **Names:** a placed device is named by iodev `InstanceName` if it has one, else `Name` (`Dv Nm` and its symbol's `Cmn1`; 3,389 of 3,395 corpus devices with an `InstanceName`). `Db Mdl` keeps `Name`.
- **Which devices:** any device on an Ethernet IP ID or Cresnet ID (`P4/P3/MC3Ethernet`, `P4/P3Cresnet`) with its own logic symbol, only fixed child slots, a symbol with `CheckCnx=random` (no required pins), list sizes from `MinVariable*`/`Expand_by`, and only `PermanentStringSize` parameters. `tools/prove_devices.py` rebuilds every such device in the 380 public programs from today's libraries: 719 device types match wherever they appear. In files saved since SmVr 1200, the only differences are fields users set later (location, serial number, IP address) and Crestron logic modules a user attached (`Db Whc=1`, `LSymH`). Older files lack `RelStat`/`ProdLine`, which older SIMPL didn't write.
- **Devices with their own slots (frames):** slot position *n* has type `Expand<n>`; a missing *n* repeats the previous type and its fixed device (an ST-IO's relays fill 5-12), up to `MaxSlots`. `Fixed<n>` names a device SIMPL puts there itself, recursively (`FixedSlot`, `Fixed`, `LoPwrRlySlot`...). Handles go depth first: the device, then each position's slot followed by its fixed device's subtree (later additions take max+1). Empty slots of a type share one record, at most 501 slots (39 of 39), then another. Slot addresses are decimal (`01`, `10`, `1000`) unless the slot type's `AddressFormat` is `HEX`. IR and power slots carry `SlF=Ex` (182 of 182). A device in a slot carries the slot's `SlC`. Devices without a `SymbolCode` (relays, ports) get no symbol and no `SmH`; symbols go under the nearest ancestor's symbol. `tools/prove_frames.py` rebuilds every untouched frame on a network in modern public files: 47 identical; the 4 others differ only by a handle gap typical of an edited device.
- **Cards and other devices a user puts into a frame's slot:** whether the device gets the slot's `SlC` or a `Db` record depends on the device type, not the slot (a DMC-4KZ-C gets a `Db` record; the "DM Outputs" holder in a DM-MD8x8 output slot gets `SlC`). `tools/build_slot_rules.py` measures it per device code in modern public files and keeps the codes every instance agrees on (seen at least twice) in `catalog/slot_device_rules.json`. DM input cards, DM endpoints, HDBT receivers and the like are consistent; COM and IR drivers are not (they change with what users pick later). Rebuilt with these rules, 238 of 239 untouched corpus cards match exactly (the other has a `Db` record a user added to its sub-device). The `Db` record is written without `Tpe`, as SIMPL 4.32 (SmVr 1247) did on all 4 of its records; files from SmVr 1244 are split 41/39.
- **`Name` parameter:** a device symbol's `Name` parameter starts as the device's own name (17 of 17 devices not renamed since; renamed devices keep the original in the parameter).
- **Round 8 in SIMPL itself (2026-11-24).** SIMPL Agent drove SIMPL Windows' own window (`tools/simpl_gui.py`; SIMPL started with `__COMPAT_LAYER=RunAsInvoker` runs without admin rights, so a normal program can screenshot and click it). Four Save As steps from an empty CP4N; `add_device` now rebuilds each step byte for byte (`tests/data/frames-step*.smw`, local only). What SIMPL showed:
  - `DefDev<n>` names a device SIMPL drops into slot *n* by default, like `Fixed<n>` (a DM-MD8x8's "DM Outputs" in slots 17 and 21; an NVX's and a CEN-IO-COM-102's COM ports get a COM 2-Way Serial Driver).
  - Slot records carry the slot type's own `ObjVer` (`DM_Input_Card` is 4).
  - A device with `RequiresOverrides=True` adds `LabelOverrideStatus=2` at the end of the header (3 of 3 corpus programs with one, 0 of 63 without), and on a network its `Db` record gets `Tpe=<Hint>` (25 of 25). Cards in a frame don't get `Tpe`.
  - A symbol's `Nm` is the device's library `Name` (`DM-NVX-36x Stream Transmit`, `DM-MD8x8` where the symbol library says `DM-MD8X8`); `Cmn1` and the device's `Nm` are its `InstanceName`.
  - A built-in part's `Name` parameter is its owner's name (`DMC-4KZ-C Advanced` gets `DMC-4KZ-C`).
  - COM drivers get a `Cm` record with the port's defaults from the slot type's `Property` list: `Ptl Tis=1 BRt Pty SBt DBt [hHs] sHs` (hHs only when the port has hardware handshaking; key order holds in all 198 modern corpus records). Serial-driver symbols (`Expand=expand_parameters_with_total_inputs_and_outputs`) have their fixed pins plus one variable input and output, and a blank parameter for each fixed one and each variable pin.
  - `mO` is written, even as 0, whenever there are outputs (20 of 20).
  - Some devices have a symbol per processor family: `SymbolCode6` (3- and 4-Series) or `SymbolCode5` (2-Series), else `SymbolCode`.
  - SIMPL marks the Virtual Communication Port and TCP/IP Client incomplete (`CF=1`, and every folder above) as soon as they're placed; they can't compile until wired, so `add_device` refuses them. The CEN-RGBHV8x4 is complete.
- **Removing a device (SIMPL's Delete, f12-round8 steps 5 and 6):** the device's whole subtree goes, with its `Db`/`Et`/`Cm` records and symbols; its slot loses `mC/C1` and merges back into the free record of its type under the same owner, which moves to the first handle's place; the owner symbol's child list is renumbered; no other handle changes. `remove_device` matches both saves byte for byte (a panel on an IP ID, a card in a frame).
- **New programs (SIMPL's File > New SIMPL program, f12-round8):** SIMPL made new programs for a CP4N, CP3N, RMC4, MC4 and DMPS3-4K-150-C; `new_program` rebuilds the first four byte for byte. The file is `Version`, `FSgntr` (`RelVrs`/`SavedBy` from smpwin.exe's version, `MinSMWVrs` = the processor's `SMWRev`, `MinTIOVrs` = its `TIORev`), `Hd` (`CnC`/`CnH=2`, `DbVr`/`DvcDbVr` from the registry keys `Crestron Database`/`Device Database`, the system name as `CltNm`, `SmVr`/`DvVr` = the libraries' `RelVrs`), the processor's whole device tree from the builder (processor at handle 2, `Ad=00`, `Db` 1), its `Cm` records, `FP`, `Bk`, then symbols 1-5 (Central Control Modules, Network Modules, Ethernet, Logic, DefineArguments) and the device symbols from 6. New rules it showed: a device gets a `Cm` record exactly when it has the `Serial-Dlg` configuration dialog (209 of 209 in the corpus, 0 of 3,130 without), off a COM port just `Tis=1`; `SbObjRev` is copied from the library (8 of 8); `AddressFormat=None` slots have `Ad=None`; `HEXM1` addresses count from 00. Not yet: the DMPS3, whose DM inputs have read-only string parameters SIMPL fills with text not in the libraries ('HDBaseT Receiver').
- **Program header (real-job test, 2026-11-25):** File > New leaves `PIT=` (Program ID Tag) blank, and SIMPL's compile stops with "The Program ID Tag is not set". Setting `PIT` (after `ZeroOnIoOk`) and `PgmNm` (after `DvcDbVr`) compiled clean, and SIMPL re-saved the program byte for byte (TSW-1070, a folder, a Set/Reset Latch, two Serial Sends into COM 1's TX$, panel joins).
- **Output cards and handle reuse (f12-round8 'outs'):** a single output card (DMC-4K-HDO) goes into a "DM Outputs" holder's own slots; a full output card (DMCO-22) replaces the holder after it's deleted. All three steps rebuild byte for byte. SIMPL gives new devices and symbols the **lowest unused handle**, so gaps left by deletes fill before the maximum grows (the DMCO-22 got the freed 607-609 and symbol 22, then max+1); `Db` records took max+1. Symbol records stay in handle order. A built-in part's Name parameter is its own `InstanceName` if it has one (passed on to its parts), else its owner's.
- **Incomplete on placement = a parameter without a value:** the TCP/IP Client is marked incomplete only because its Port is blank; with Port set and no pins wired it compiled cleanly (compiled through SIMPL itself, 2026-11-24). Pins are optional.
- **Drivers on COM ports** are written like SIMPL's default drivers (the port's `SlC`, a `Cm` record, no `Db`). `Db`, `Et` and `Cm` records, like devices and symbols, take the lowest unused handle; with that, removing the CP4N's COM 1 driver and adding one back gives the original file byte for byte.
- **Compiling by message:** in a SIMPL without admin rights, Project > Convert/Compile by its menu ID compiles even with the screen locked. "Compiling...", then "Program Compilation" (a ListBox of `SEVERITY	(CODE)` / `	** message` lines, read with `LB_GETTEXT`) and "Compile Complete" (an Edit with the summary and `Transfer Program?` Yes/No, always answered No). "Incomplete Symbols" comes as an OK box instead. `compile_program` now uses this, falling back to the elevated smpc task only when it must.
- **Live link without admin rights:** SIMPL started with `__COMPAT_LAYER=RunAsInvoker` takes window messages from a normal program, even while the screen is locked: `WM_COMMAND` with File > Save's menu ID saves; after the file changes on disk, `WM_ACTIVATEAPP` makes SIMPL check it and show a "Crestron SIMPL Windows" Yes/No box, and `BM_CLICK` on Yes reloads. Closing with `WM_CLOSE` can show the same kind of box. Typing and mouse input need an unlocked screen. An elevated SIMPL (its default) blocks all of this.
- **SIMPL+ from the command line:** `SPlusCC.exe 
ebuild <file.usp> 	arget series3 series4` (one command-line string; no window, no admin) writes the `.ush` and `SPlsWork` beside the `.usp` and prints, per target, `Compiling for 4-Series Output: ...`, then `[file] Error 1001 (Line 9) - Undefined variable: 'X'` or `[file] * WARNING  * (Line 50) - ...` (the code is optional), then `Total Error(s)` / `Total Warning(s)`; the exit code is non-zero on errors. A SIMPL# library (`.clz`) must sit beside the module. Line numbers are the compiler's own count (a 6-line test file reported line 9).
- **Joins on panels and EISCs:** a panel-style device symbol (`Expand=expand_inputs_with_outputs`, `Expand_by`, list 2/3 cues) numbers its pins straight through three lists: inputs digital `I1..n1I`, analog `I n1I+1..n1I+n2I`, serial after that; outputs the same with `n1O` and `n2O = mO - n1O`. All 5,045 wired pins on such symbols in modern corpus files fit. A list's inputs and outputs have the same length (93 of 101), and lengths needn't be multiples of 32 (46, 196, 269 ...). Growing a list moves every pin of the lists after it. Key order: `... CF n1I n2I n1O Cmn1 [mC C*] mI I* mO tO O* [mP P*]`. SIMPL 4.32 opened a TSW-1070 grown to 40/35/32 with seven joins wired and re-saved it byte for byte (f12-round8); it compiled with exactly the predicted messages.
- **Round 8 cards compile:** a DM-MD8x8 with a DMC-4KZ-C in slot 1 and a DMC-4KZ-HD in slot 2, plus a DM-TX-201-C, compiled 0/0/0.
- **Round 8 compile:** a DM-MD8x8 (empty card slots), a DM-NVX-36x (23 devices inside) and an ST-IO in one CP4N compiled 0/0/0.
- **Round 7 (automatic compiles):** 18 device types in one CP4N gave "Incomplete Symbols". The three without `CheckCnx=random` (CEN-RGBHV8x4, CEN-RGBHV16x16, Virtual Communication Port) have required pins; without them, 15 types (13 Ethernet including XPanels, TSW-760/1050/1060, TPMC-12, packed and 3-Series EISCs, e-control, e-server, SW-WMC; 2 Cresnet: CNX-B8, TPMC-9) compiled with 0 errors, 0 warnings and 0 notices.

### SIMPL+ modules end to end (M6, 2026-11-25)

A module written for the conference-room test program (`DisplayFeedback.usp`: `BUFFER_INPUT Rx$`, two digital outputs) went the whole way: `splus_compile`, `add_module` (COM 1's `rx$` to the module, its outputs to panel joins 3 and 4), then a compile in SIMPL with 0 errors, warnings and notices. A freshly started SIMPL re-saved the program byte for byte.

- **Line endings:** SPlusCC (4.06) needs CRLF. With bare LF, a `//` comment runs on to the next CR, so everything after the first one is dropped and the module "compiles" clean with no pins or code. A BOM, UTF-8 text, CR-only and comment-free LF files were fine. `splus_compile` converts the file to CRLF first.
- **The `.ush`** SPlusCC writes beside the `.usp` holds the module's `Symbol` record: `Name` (from `#SYMBOL_NAME`), `SymbolTree` (from `#CATEGORY`), cues and `MinVariable*` per list (digital first list; analog and serial in list 2; here `Rx$` is `InputList2`), and `ParamCue1=[Reference Name]`. A placed module with a blank `P1` and `CF=2` is normal (1,028 of 1,103 placed SIMPL+ modules in the public corpus).
- **SIMPL keeps a module build:** a SIMPL that read a module's earlier (empty) build kept it after the `.ush` was rewritten and after reloading the program: it marked the corrected module incomplete (`CF=1` on it and its folders when saved) and refused to compile. A freshly started SIMPL compiled the same file clean. `compile_program` therefore saves and restarts a SIMPL started before any of the program's `.ush` files were written.
- **`#CATEGORY` IDs** are the symbol library's `SymbolTree` codes (6 Lighting, 32 Miscellaneous, 46 Custom ...); an unknown ID falls back to Miscellaneous (per the SIMPL+ help).
- **Program ID Tags:** SIMPL's Edit Program Header suggests the names in `Cresdb\Programming\ProgramIDTags.ini` (Audio_Distribution, AV, HVAC, Lighting, Main, Security, Theater, Video_Distribution).
- **Reference:** `Simpl+lr.chm` (the SIMPL+ Language Reference) unpacks with `hh.exe -decompile` (which fails silently on paths with spaces) into 526 pages: functions, declarations, directives, events, and one page per compiler error and warning; the pages are cp1252.

## 8. Still to learn
**From the F12 test set (`tools/make_f12_samples.py`):**
- Whether SIMPL 4.32 loads and compiles our records without complaint (files 01, 02, 11).
- What SIMPL changes when it re-saves a file we wrote. Both bases were saved by 4.30, so a 4.32 save rewrites version fields everywhere. Compare re-saved `01` with re-saved `00`, and `11` with `10`, not with `_as_written`.
- The two-drivers question.

**Still unknown:**
- `ObjVer` (always `1` on simple symbols), `n2I`, `SgTf`, `Fx`, and `SgTp` 1, 6 and 31.
- Which pins each symbol requires (what makes `CF=1`).
- How SIMPL adds devices other than the proven ones (Cresnet, cards, configurable slots).
- Why SIMPL reports 40 LGCMCVT102 and 42 LGCMCVT103 on signals wired to Smart Graphics list extenders (`.ced`, SmC 2942, under an XPanel) in the public LibraryProgram, which `find_problems` doesn't predict. The same messages appear before and after adding a device, so they're a `find_problems` gap, not a device one.

## Touch-panel joins against a join map (M7, 2026-11-25)
- **Reading joins back:** a panel-style symbol's pin p is digital join p up to the digital list's size, then analog join p - n1, then serial join p - n1 - n2, for inputs (with `n1I`, `n2I`) and outputs (with `n1O`, `n2O = mO - n1O`) separately. Every wired pin on the panel symbols in the SIMPL 4.3x corpus files reads back as exactly one join.
- **Lists of unequal length exist:** a public TSW-760 has 32 serial inputs but 18 serial outputs (`tO - mO`). A list only grows on the side whose join is past its end; rewiring every corpus panel from its own joins leaves the file byte for byte.
- **XPanel 3.0 Crestron HTML5** placed by `add_device` gets lists of 32 per type (its `Expand_by`), so serial join 1's output is O65.
- **Unused signals:** SIMPL drops a signal nothing uses on its next save. After a join was rewired from `Level_Fb` back to `Level`, SIMPL 4.32's re-save removed `Level_Fb` and changed nothing else. `apply_edits` now removes such signals at the end of the edit (not straight away, so a pin can be disconnected and reconnected to the same signal in one call).
- **Live check:** an RMC3 program with an XPanel 3.0 at IP ID 03 was wired from a CH5 Agent `joins.json` (two digital, one analog and one serial join, both directions). It compiled with exactly the predicted warning and notices, and SIMPL re-saved it byte for byte, also after joins were broken and restored.

## SIMPL Debugger logs (M8, 2026-11-25; inferred, no real log seen yet)
- **Where they come from:** Toolbox's SIMPL Debugger saves the Trace window to text (Logging > Save Current, or Start Logging while tracing), by default in `Documents\Crestron\Toolbox\SIMPL Debugger Logs`. File names follow `%s - %s.txt` / `%s - %s - %s.txt` (from the binary). It's written as ANSI text (`wt+`).
- **Line templates** (strings in `SIMPL Debugger.ocx`):
  - `$time: $signame -> $sigvalue`;
  - `$time: [$type] : $msg`, with types Console Data, SIMPL+ Trace, User Stimulus and Signal Monitor Status;
  - `%s: *** Timestamp %d`.

  A `$sigtype` placeholder also exists, unused in these templates.
- **Time formats:**
  - time of day `%H:%M:%S - %m-%d-%Y` (also the shape in the example comment of rdriscoll/CrestronToolboxSIMPLDebuggerLogParser, MIT, 2017: `HH:MM:SS - MM-DD-YYYY: <signal> -> <value>`);
  - `%02d:%02d:%02d.%03d`;
  - `%d days, %02d:%02d:%02d.%03d`;
  - `%d ms` (relative to the previous event).
- **Values:**
  - digital `0`/`1` (help screenshots of the Trace window and its clipboard copy);
  - analog in the chosen display format (`%04Xh`, `%2.3f%%`, signed or unsigned decimal, or a time);
  - serial with non-printables as `\x%02X` (or `.` in ASCII mode).
- **Names:** module signals are prefixed `::` (help: Include Module Signals). The clipboard copy is tab-separated time, value, name.

## Pin types on multi-list devices (2026-11-25)
- **The rule:** device symbols with several pin lists (panels, XPanels, EISCs, dimmers...) number their pins through list 1, then list 2, then list 3, using the placed record's sizes (`n1I`, `n2I`; `n1O`, `mO - n1O`).
- **A pin's type:**
  - it takes its own list's type from the library (`InputSigType`, `InputList2SigType`, `InputList3SigType`, and the `Output` ones), using the nearest entry at or before it;
  - an untyped list is digital, analog and serial for lists 1, 2 and 3.
- **Evidence:** this held for all 64,525 wired pins of such devices in the SIMPL 4.x corpus, with 0 exceptions. It's why a DIN-1DIM4 placed with no list-1 pins has an analog pin 1 although `InputSigType1` says Digital.
- **Live check:** `connect` put new analog and serial signals on an XPanel 3.0's analog and serial joins with no type given. It compiled with exactly the predicted messages, and SIMPL re-saved it byte for byte.
- **The slim index** now keeps every list-2/3 type (about 0.7 MB). It gives the same pin types as the full library on all 155,914 device pins in the corpus.

## Panel extenders: Smart Graphics and CH5 contracts (2026-11-27)
- **The file:** a panel device's `VtpH` points to a `VTP` record: `GuiExtType=1` with a VT Pro-e `.sgd` (Smart Graphics), or `GuiExtType=2` with a CH5 `.chd` (contract) plus `ContractID`. `SGDFile` is the path, usually relative to the program. The corpus has 55 `.sgd` and 17 `.chd` references, 9 `.sgd` with no `GuiExtType`, and 24 VTP records with no file.
- **Its format:** both files use the bracket record format of `.smw`/`.umc`, with `;` comment lines.
  - Each object is a `Symbol` with per-list Min/Max counts and `InputCue`/`InputList2Cue`/`InputList3Cue` (and output) names. Its `Hint` gives the ID: "(Smart Object ID=10)" or "(Control Join Id 1)".
  - A `.chd` also has `CHD` records (`ChdCode`, `ParentChdFolder`) and `Dp` parameter records. Its signature is `Sgntr=CHD`.
- **Placed objects:** each is an `Sm` record with `SmC=2942` under the panel's logic symbol, directly or inside contract folders (`SmC=6774`, e.g. "Keypad Attributes"). It has `Nm` = the object's name, `P1` = its Smart Object ID, and `ChdH` on contract components. Pins run through the digital, analog and serial lists with the record's sizes; a serial-only component has no `n1I`.
- **Matching a placed object to its definition:** by Smart Object ID (`P1` against the Hint), else by name.
  - 195 corpus extenders match both ways and 12 match only by ID (panels that copied another panel's objects). 3 match neither: their program is newer than the file in its repo.
  - All 207 that match fit their definition's pin counts.
  - The files came from the programs' own GitHub repos (`tools/fetch_panel_files.py`), saved beside the corpus copies.
- **Open:** SIMPL compiled a public program with a Smart Graphics XPanel (LibraryProgram) with 40 warnings and 42 notices that `find_problems` doesn't predict. A re-test from a fresh copy, with and without its `.sgd`, stopped at "Incomplete Symbols" instead, and `find_problems` sees nothing incomplete. Corpus copies keep git's LF line endings, which SIMPL rejects with a bare "File Error" until they're converted to CRLF.

## Parameter values (2026-11-27)
- **Source:** SIMPL's help, Compiler Errors 105-108 and 125, checked against every placed parameter value in the 380 public programs (`tests/test_params.py`, corpus test).
- **Escapes:** SIMPL reads every backslash in a parameter as an escape: `\a \b \f \n \r \t \v \\` and `\x` with exactly two hex digits.
  - Wrong forms: `\x` cut off by the end of the value (105), any other `\` code (106), a lone `\` at the end (107), `\x` with fewer than two hex digits (125). `\u` drew warning LGCMCVT236 in SIMPL 4.32.
  - The corpus uses only `\xHH` (5,735), `\n`, `\r` and `\\`, and no value breaks the rules.
  - It applies to SIMPL+ string parameters too (`\\USER\\` in a public program; `\user\` drew 236 and 107 live).
- **The parameter's type** is `ParamSigType<n>`, else the nearest one before it (a variable parameter list shares the first's type). `UI_RO_String` is device text SIMPL writes, so it isn't checked.
- **Numeric types** (`Constant`, `Percent`, `Time`, `HexAddress`): every corpus value is one of `10d`, `-5d`, `0`, `50%`, `0.25%`, `2s`, `.01s`, `1t`, `1Fh`, `'2'` or a long time `07.50.00.00s` / `5.00.00s` (units in either case).
- **Ranges aren't checked:** the help's single-precision limits (65535, 100%, FFFFh, 582s) don't hold for every symbol. The corpus has Numeric Keypad `99999d`, Hosted BACnet Device `562036d`, Oscillator `655.35s` and Retriggerable One Shot `660s`. Which parameters are single precision isn't in the library fields SIMPL Agent reads.
- **What SIMPL Agent does:** `add_symbol`, `add_module`, `add_device` and `set_parameter` refuse a bad value, naming SIMPL's code. `find_problems` reports existing ones (`LGCMCVT105`-`107`, `125`, `236`, and `SA-PARAM-FORM` for a numeric value in no known form).

## Signals inside macros, and commented-out symbols (2026-11-27)
- **Live evidence:** SIMPL 4.32 compiles (never transferred) of test copies of two public programs, compared with `find_problems` message for message. All five match exactly.

  | Test copy | What it tests | SIMPL's messages |
  |---|---|---|
  | ZowieTest (RMC3), its macro's 3 SIMPL+ modules removed | a macro with dangling signals | 59 |
  | the same, plus Crestron's `udsrly_int.cmc` placed | an installed Crestron macro | 64 |
  | the same, plus a top-level Retriggerable One Shot | whether a One Shot output counts | 66 |
  | NCSD Program 1c_1 (CP2E, 2-Series), as published | commented-out symbols | 0 |
  | the same, plus a probe OR | that the logic checks run | 2 |

  - As published, ZowieTest's SIMPL+ modules don't compile in this SIMPL, and the messages were the same with them removed: SIMPL leaves a failed SIMPL+ module out of the circuit.
  - The old rule judged each level on its own and treated macro pins as real drivers and destinations. It matched only 5 of the 59 messages and predicted 75 that SIMPL didn't report.
  - A real DMPS3 classroom program with 23 placed macros and commented-out symbols also compiled with 0 messages, and `find_problems` predicts 0.
- **One circuit:** SIMPL's compiler treats a placed macro as part of the program.
  - A signal on a macro pin and the macro's own signal on that pin (through the Argument Definition, pin n to pin n) are one net.
  - The net is judged as a whole: 102 when something reads it and nothing drives it, 103 when something drives it and nothing reads it. A net that's only on macro pins is neither.
  - It's reported once, by the outer name. Example: `Zowie_ndi_1_name$` leaves the macro, is read inside by Make String Permanent and is driven by nothing, so SIMPL reported 102, not 103.
- **Wholly inside a macro:** LGCMCVT126 (a warning, though the help calls it a notice) or LGCMCVT127 (notice), once per placed copy: `Signal "x" in S-2 (Module name <path of the .umc>) has no driving source.`
- **Crestron's `.cmc` macros:** SIMPL reports nothing wholly inside them. A placed `udsrly_int.cmc` has two One Shot outputs that nothing reads, and SIMPL said nothing, though a top-level One Shot in the same state drew 103. Their signals still join the outer circuit.
- **Not destinations:** inputs of Digital, Analog and Serial Force (471, 472, 470), which only fix a signal's type, and of Virtual Device for Module Connection (286).
  - A macro signal on a Serial Force alone drew no message.
  - A signal with a driver and only a Serial Force drew 103.
  - A Crestron macro's relay outputs, read inside only by a Virtual Device for Module Connection, drew 103.
- **Commented out = `OpF=0`** on the symbol's record. The compiler ignores such symbols.
  - Evidence: SIMPL asked "Commented out Symbols and/or Devices" for NCSD, and its 12 signals driven only by `OpF=0` symbols drew no message.
  - In the corpus, 1,304 symbols in 94 programs have it, and all 1,059 symbols inside commented-out folders carry it too.
  - `find_problems` leaves them out of every check: signals, second drivers, parameters, incomplete symbols and changed modules.
- **2-Series codes:** a CP2E program's messages read `RLCMCVT102`/`103` where 3- and 4-Series read `LGCMCVT`. `compile_program` compares them as the same.
- **Inferred, not yet seen:**
  - An undriven outer signal into a macro pin that nothing reads inside gives no message.
  - An unwired macro input counts as held at 0: SIMPL's help gives warning 124 for it, not 126.
  - The symbol number SIMPL gives a macro inside a macro. Those messages are marked unconfirmed.
- **Corpus effect, against the old rule:**
  - Programs without macros are unchanged, apart from the type-only symbols and commented-out symbols.
  - In programs with macros, most changes are signals read or driven inside a macro.
  - Two test programs gain 28 notices each, for signals read only by a Serial Force (the rule above).
- **Parameter values inside macro files** aren't checked. There they may name the macro's own parameters (`#Name`, or `\[#Name\]` inside a string) for SIMPL to fill in when the macro is placed: more than 37,000 such values in the corpus's and SIMPL's installed macros. Values placed in programs are checked; none in the 380 public programs is flagged.
