---
name: simpl-agent
description: Read, explain and check Crestron SIMPL Windows programs (.smw) and look up SIMPL symbols through the SIMPL Agent MCP server (simpl_agent_status, describe_program, folder_tree, list_folder, show_symbol, find_signals, follow_signal, find_problems, find_library_symbols, library_symbol_details). Use when the user asks about a SIMPL program, how its logic works, why a signal behaves a certain way, what SIMPL's warnings mean, or wants help planning SIMPL logic.
---

# SIMPL Agent

Tools for Crestron SIMPL Windows. At milestone M2 they **read and check** programs; they can't change them yet.

## Ground rules
- **Programs are private client work.** Don't copy them, or parts of them, anywhere outside this conversation: no repos, uploads or web searches with program content.
- **Hands off the files.** Never write to a `.smw`, `.umc` or `.cmc` file with any tool. Editing comes later, through SIMPL Agent only.
- **Never touch a real system.** Don't load to a processor, connect to one, or change Toolbox settings.
- **Don't break protection.** Leave password-protected programs and modules alone.
- **Don't invent anything.** Never make up symbols, pin names, signals, devices or IP IDs. If the program or library doesn't say, ask the user.
- **When unsure, stop and ask.** Do that rather than guess. Stop after two failed tries at the same step.

## How to handle a request
1. **Find the program.** Call `simpl_agent_status`; it shows what SIMPL Windows has open, and whether it has unsaved changes. If that isn't the file the user means, ask for the full path.
2. **Get the overview.** Call `describe_program` for the processor and counts, then `folder_tree` for the layout.
3. **Look closer** with the tool that fits:
   - `list_folder`: what's in a folder, in SIMPL's order (`S-1`, `S-2`… within the folder; that these match SIMPL's own S-numbers is inferred).
   - `show_symbol`: one symbol's pins, with the library's pin names, its signals and its parameters.
   - `find_signals`: signals by name, with how many outputs drive each and how many inputs use it.
   - `follow_signal`: where a signal comes from and where it goes, across folders. Chain calls to trace logic step by step.
   - `find_problems`: SIMPL-style warnings before the user compiles.
4. **Look up symbols** with `find_library_symbols` and `library_symbol_details` for real pin names and rules.
   - Names ending in `#` repeat (`i1`, `i2`…).
   - Names in `[brackets]` seem to be optional pins. That's inferred, so say so.
5. **Answer plainly.** Lead with the answer. Refer to symbols by folder path and name, e.g. "Logic\Room A: One Shot", and give the handle (`#33`) and position as well when it helps.
6. **If the user saves in SIMPL,** re-read before relying on earlier results. SIMPL can renumber symbols when it saves, and the `revision` will differ, so never reuse old handles.

## Reading find_problems
- **Codes that follow SIMPL 4.32's compiler** (checked against a small set of real compiles):
  - `LGCMCVT102`, warning: a signal goes into an input but nothing drives it.
  - `LGCMCVT103`, notice: a signal is driven but goes nowhere.
  - `LGCMCVT220`, warning: a digital signal has a second driving source.
- **Unconfirmed results:** entries marked `unconfirmed` involve SIMPL+ modules or macros, and SIMPL hasn't been seen to report those yet. Results on macro files (`.umc`/`.cmc`) haven't been checked against SIMPL either. Say so.
- **SIMPL Agent's own checks** start with `SA-`: duplicate names, broken references, and symbols SIMPL marked incomplete.
- **Exemptions** (from the corpus, not yet confirmed by a SIMPL compile):
  - The built-in signals `0`, `1` and `Local`, and names starting with `//`, are never reported.
  - Buffers, panels and similar symbols may share an output signal.
  - Analog and serial signals may have several drivers.
- **Compiling:** the user's compile (F12 in SIMPL) is the final word.
