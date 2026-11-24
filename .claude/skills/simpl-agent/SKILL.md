---
name: simpl-agent
description: Read, explain, check, edit and compile Crestron SIMPL Windows programs (.smw) through the SIMPL Agent MCP server (simpl_agent_status, describe_program, folder_tree, list_folder, show_symbol, find_signals, follow_signal, find_problems, apply_edits, module_details, compile_program, edit_history, undo_last_edit, restore_version, wait_for_simpl_save, find_library_symbols, library_symbol_details). Use when the user asks about a SIMPL program, how its logic works, what SIMPL's warnings mean, or wants SIMPL logic added or changed.
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
1. **Find the program.** Call `simpl_agent_status`; it shows which program SIMPL Windows has open. It can't see unsaved changes in SIMPL. If that isn't the file the user means, ask for the full path.
2. **Look before changing anything.**
   - `describe_program` and `folder_tree` for the overview.
   - Then `list_folder`, `show_symbol`, `find_signals` and `follow_signal` for the part the request touches.
   - Match the program's naming style and folder layout.
3. **Look up symbols** with `find_library_symbols` and `library_symbol_details`: real pin names and pin order. Names ending in `#` repeat (`i1`, `i2`…).
   - **Modules:** for a macro (`.umc`, or Crestron `.cmc`) or SIMPL+ module (`.usp`) beside the program, use `module_details` for its pin names, types and required parameters.
4. **Plan in one line** and tell the user, e.g. "Add an OR in Room A that turns on room_a_any when either source is on."
5. **If SIMPL has the program open, ask the user to save it there first** (Ctrl+S) and wait for their OK. After the edit, SIMPL offers to reload, and reloading discards anything unsaved. Then read the program again, and pass `user_confirmed_saved: true`.
6. **Make ONE `apply_edits` call** with every operation the request needs, a one-line `summary`, and the `revision` from your last read. The call is all or nothing. Use `dry_run: true` first when unsure.
   - **New signals:** they're created automatically when you name them in `inputs`, `outputs` or `connect`. Set `new_signal_type` to `analog` or `serial` when they aren't digital.
   - **Wire every pin.** Use the built-in signals `0` or `1` for constant inputs.
   - **Second drivers:** a digital signal can't get a second driver, except between Buffer-type symbols. Analog and serial signals may have several.
   - **Which symbols:** only simple logic symbols proven in SIMPL 4.3x files can be added (`add_symbol_supported`), and only to files saved by SIMPL 4.3x.
   - **Modules (`add_module`):** wire pins by name in `connect`. SIMPL requires every pin with a plain name; ones you don't connect go on SIMPL's standard placeholders (`//__digital_reserved__` and so on), and the result says how many. `[bracketed]` pins are optional. Every listed parameter needs a value.
     - **Pins that take any type** must be connected explicitly.
     - **SIMPL+ modules** need their compiled `.ush` beside the program; modules with drop-down parameters aren't supported yet.
   - **Devices (`add_device`):** `device_tree` and `free_ids` show what's there. Ask the user which IP ID to use; never pick one yourself. Give the device's exact library name or code and the `address` (hex, e.g. `03`). Devices go on an Ethernet IP ID or a Cresnet ID (4-Series, 3-Series, MC3). Touch panels, XPanels, EISCs, DM frames, NVX endpoints and other devices whose pins are all optional work; SIMPL's built-in sub-devices and empty card slots come with them. To put a card into a frame (e.g. a DMC-4KZ-C into a DM-MD8x8), give `network` as the frame ('#handle' from `device_tree`) and `address` as the slot number; only card types SIMPL writes consistently are allowed (DM input cards, DM endpoints and similar), not COM or IR drivers yet. Devices with required pins or parameters without a known default are refused with the reason. Use `network` (e.g. 'Cresnet Devices') when the ID exists on more than one network. The device's symbol appears under the network's symbol with its pins unwired; connect them afterwards with `connect`.
7. **Read the result:** `changes`, `new_problems` (SIMPL-style warnings the edit introduced), and `next_step`. If a new problem is unintended, fix it with another `apply_edits`, or `undo_last_edit`.
8. **Tell the user** what changed, using SIMPL's names: S-number, folder and symbol, e.g. "S-2.3 (Logic\Room A: OR)". Pass on `next_step`, which is usually:
   - switch to SIMPL, which says the file changed and offers to reload: click **Yes**;
   - then compile with **F12**.

   Saving in SIMPL without reloading would overwrite the edit.
   - **If SIMPL is closed, compile it yourself** with `compile_program`. It takes about a minute; SIMPL opens and closes on its own, so warn the user not to type in it meanwhile. Report SIMPL's errors, warnings and notices. If `matches_find_problems` is false, say so: it points at a SIMPL Agent rule to fix.
9. **After the user saves in SIMPL,** read the program again before the next edit. SIMPL can renumber symbols, so a stale `revision` is refused. `wait_for_simpl_save` waits for that save.

## History
- **`edit_history`:** what SIMPL Agent changed, and whether the file was changed elsewhere since.
- **`undo_last_edit`:** undoes the last change, but only while the file is exactly as that change left it.
- **`restore_version`:** goes back further. Without `confirm` it only shows what would be lost; show the user and ask before confirming.

## Reading find_problems
- **Codes that follow SIMPL 4.32's compiler** (checked against real compiles, including SIMPL's S-numbers):
  - `LGCMCVT102`, warning: a signal goes into an input but nothing drives it.
  - `LGCMCVT103`, notice: a signal is driven but goes nowhere.
  - `LGCMCVT220`, warning: a digital signal has a second driving source.
- **Macro files:** results on macro files (`.umc`/`.cmc`) themselves haven't been checked against SIMPL yet. Say so if you check one.
- **SIMPL Agent's own checks** start with `SA-`: duplicate names, broken references, and symbols SIMPL marked incomplete.
- **Exemptions** (confirmed by SIMPL 4.32):
  - The built-in signals and `//` placeholder names are never reported.
  - Buffer-type symbols may share an output.
  - Analog and serial signals may have several drivers.
  - A second driver isn't reported when a macro or SIMPL+ module is one of the drivers.
- **Compiling:** the user's compile (F12 in SIMPL) is the final word.
- **SIMPL+ on 3-Series:** programs with SIMPL+ need Microsoft .NET Compact Framework 3.5 to compile. Without it, SIMPL shows error LGCMCVT277 and a flood of LGCMCVT102/103 messages for every signal wired to a module. Those aren't real problems in the program.
