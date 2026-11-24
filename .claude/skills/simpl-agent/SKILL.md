---
name: simpl-agent
description: Read and explain Crestron SIMPL Windows programs (.smw) and look up SIMPL symbols through the SIMPL Agent MCP server (tools simpl_agent_status, describe_program, find_library_symbols, library_symbol_details). Use when the user asks about a SIMPL program, a Crestron logic symbol, or wants help planning SIMPL logic.
---

# SIMPL Agent

Tools for Crestron SIMPL Windows. At milestone M1 they are **read-only**: they can describe a program and look up SIMPL's installed symbol library, but they can't change a program yet.

## Ground rules
- **Programs are private client work.** Don't copy them, or parts of them, anywhere outside this conversation: no repos, uploads or web searches with program content.
- **Hands off the files.** Never write to a `.smw`, `.umc` or `.cmc` file with any tool. Editing comes in a later milestone, through SIMPL Agent only.
- **Never touch a real system.** Don't load to a processor, connect to one, or change Toolbox settings.
- **Don't break protection.** Leave password-protected programs and modules alone.
- **Don't invent anything.** Never make up symbols, pin names, devices or IP IDs. If the library or the program doesn't say, ask the user.
- **When unsure, stop and ask.** Do that rather than guess. Stop after two failed tries at the same step.

## How to handle a request
1. **Find the program.** Call `simpl_agent_status`; it shows what SIMPL Windows has open, and whether it has unsaved changes. If that isn't the file the user means, ask for the full path.
2. **Read before answering.** Call `describe_program` for the processor, counts and the top of the Logic folder. Note its `revision`.
3. **For symbol questions,** use `find_library_symbols`, then `library_symbol_details`, for real pin names and rules.
   - Names ending in `#` repeat (`i1`, `i2`…).
   - Names in `[brackets]` seem to be optional pins. That's inferred, so say so.
4. **Answer plainly.** Lead with the answer. Name folders and symbols the way SIMPL shows them.
5. **If the user saves in SIMPL,** read the program again before relying on earlier results. SIMPL can renumber symbols and devices when it saves, and the `revision` will differ.

## SIMPL facts worth knowing
- **Built-in signals:** `0`, `1` and `Local`.
- **Signal names** are unique, ignoring case. They use printable ASCII and never start with a digit.
- **Signal types:** digital, analog and serial.
  - Several outputs may drive one analog or serial signal.
  - A second driver on a digital signal gives a warning.
- **SIMPL 4.32 compiler messages:**
  - `WARNING(LGCMCVT102)`: a signal has no driving source.
  - `NOTICE (LGCMCVT103)`: a signal has no destination.
  - `WARNING(LGCMCVT220)`: a signal has a previously defined driving source.
- **Sharing outputs:** Buffers, panels and some other symbols may share an output signal; `library_symbol_details` shows this as `outputs_may_share_a_signal`.
- **Compiling:** only the user compiles, with F12 in SIMPL. The compiler is the final check on any plan.
