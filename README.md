<img src="assets/icon.svg" width="64" height="64" alt="">

# SIMPL Agent

MCP tools so Claude can read, check and edit Crestron SIMPL Windows (`.smw`) programs. Personal project.

The plan lives in `C:\Users\matth\OneDrive\Documents\SIMPL\PLAN.md`. What we know about the file format is in [docs/format.md](docs/format.md).

## Status: M0 (format proof)
- Lossless reader and writer (`src/simpl_agent/smw/rawfile.py`) are byte-identical on 3,829 corpus files.
- A read-only semantic model (`smw/model.py`) covers signals, symbols and devices.
- A symbol library reader (`catalog/symlib.py`) reads SIMPL's installed `symlib.tio`.
- `tools/corpus_check.py` measures each format rule across the corpus.
- First edits (`smw/edit.py`): rename a signal, add a signal, add a simple logic symbol to a folder, set a comment. Each is all-or-nothing, and `smw/save.py` backs up before writing.
- `tools/make_f12_samples.py` builds the test set for the SIMPL 4.32 reload and compile check.

## Set-up
```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest            # unit tests
.venv\Scripts\python -m pytest -m corpus  # slow tests over the local corpus
python -I tools/fetch_github_corpus.py    # download public samples (outside the repo)
python -I tools/corpus_check.py           # measure format rules
```

## Rules
- Real client programs are never copied into this repo or pushed. `.gitignore` blocks SIMPL file types.
- Crestron data (symbol and device libraries, macros) is read from the local install at run time, never copied.
- Never compile, connect to or load a processor.
