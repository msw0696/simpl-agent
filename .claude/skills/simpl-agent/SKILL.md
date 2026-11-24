---
name: simpl-agent
description: Read, explain, check and edit Crestron SIMPL Windows programs (.smw) through the SIMPL Agent MCP server (simpl_agent_status, describe_program, folder_tree, list_folder, show_symbol, find_signals, follow_signal, find_problems, apply_edits, edit_history, undo_last_edit, restore_version, wait_for_simpl_save, find_library_symbols, library_symbol_details). Use when the user asks about a SIMPL program, how its logic works, what SIMPL's warnings mean, or wants SIMPL logic added or changed.
---

# SIMPL Agent

Tools for Crestron SIMPL Windows. They read, check and **edit** programs. Every edit is backed up, recorded and can be undone.

## Ground rules
- **Programs are private client work.** Don't copy them, or parts of them, anywhere outside this conversation: no repos, uploads or web searches with program content.
- **Edit only through `apply_edits`.** Never write to a `.smw`, `.umc` or `.cmc` file any other way.
- **Do only what was asked.** Don't rename, rewire, move, delete or tidy anything else, even if it looks wrong. Mention it and let the user decide.
- **Never touch a real system.** Don't load to a processor, connect to one, or change Toolbox settings.
- **Don't break protection.** Leave password-protected programs and modules alone.
- **Don't invent anything.** Never make up symbols, pin names, signals, devices or IP IDs. If the program or library doesn't say, ask the user.
- **When unsure, stop and ask.** Do that rather than guess. Stop after two failed tries at the same step.

## How to handle a request
1. **Find the program.** Call `simpl_agent_status`; it shows what SIMPL Windows has open, and whether it has unsaved changes. If that isn't the file the user means, ask for the full path.
2. **Look before changing anything.**
   - `describe_program` and `folder_tree` for the overview.
   - Then `list_folder`, `show_symbol`, `find_signals` and `follow_signal` for the part the request touches.
   - Match the program's naming style and folder layout.
3. **Look up symbols** with `find_library_symbols` and `library_symbol_details`: real pin names and pin order. Names ending in `#` repeat (`i1`, `i2`…).
4. **Plan in one line** and tell the user, e.g. "Add an OR in Room A that turns on room_a_any when either source is on."
5. **Make ONE `apply_edits` call** with every operation the request needs, a one-line `summary`, and the `revision` from your last read. The call is all or nothing. Use `dry_run: true` first when unsure.
   - **New signals:** they're created automatically when you name them in `inputs`, `outputs` or `connect`. Set `new_signal_type` to `analog` or `serial` when they aren't digital.
   - **Wire every pin.** Use the built-in signals `0` or `1` for constant inputs.
   - **Second drivers:** a digital signal can't get a second driver, except between Buffer-type symbols. Analog and serial signals may have several.
   - **Which symbols:** only simple logic symbols proven in SIMPL 4.3x files can be added (`add_symbol_supported`), and only to files saved by SIMPL 4.3x.
6. **Read the result:** `changes`, `new_problems` (SIMPL-style warnings the edit introduced), and `next_step`. If a new problem is unintended, fix it with another `apply_edits`, or `undo_last_edit`.
7. **Tell the user** what changed, using SIMPL's names: S-number, folder and symbol, e.g. "S-2.3 (Logic\Room A: OR)". Pass on `next_step`, which is usually:
   - in SIMPL, close the program **without saving** and reopen it;
   - then compile with **F12**.

   Saving in SIMPL before reopening would overwrite the edit.
8. **After the user saves in SIMPL,** read the program again before the next edit. SIMPL can renumber symbols, so a stale `revision` is refused. `wait_for_simpl_save` waits for that save.

## History
- **`edit_history`:** what SIMPL Agent changed, and whether the file was changed elsewhere since.
- **`undo_last_edit`:** undoes the last change, but only while the file is exactly as that change left it.
- **`restore_version`:** goes back further. Without `confirm` it only shows what would be lost; show the user and ask before confirming.

## Reading find_problems
- **Codes that follow SIMPL 4.32's compiler** (checked against real compiles, including SIMPL's S-numbers):
  - `LGCMCVT102`, warning: a signal goes into an input but nothing drives it.
  - `LGCMCVT103`, notice: a signal is driven but goes nowhere.
  - `LGCMCVT220`, warning: a digital signal has a second driving source.
- **Unconfirmed results:** entries marked `unconfirmed` involve SIMPL+ modules or macros, which SIMPL hasn't been seen to report yet. Results on macro files haven't been checked either. Say so.
- **SIMPL Agent's own checks** start with `SA-`: duplicate names, broken references, and symbols SIMPL marked incomplete.
- **Exemptions** (confirmed by SIMPL 4.32):
  - The built-in signals and `//` placeholder names are never reported.
  - Buffer-type symbols may share an output.
  - Analog and serial signals may have several drivers.
- **Compiling:** the user's compile (F12 in SIMPL) is the final word.
