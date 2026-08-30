# Install

## The short version

**Windows:** double-click **`setup-windows.bat`**, then **`start-windows.bat`**.
**macOS / Linux:** double-click **`setup-mac.command`**, then **`start-mac.command`**
(or run them from a terminal).

That is the whole installation. The setup script will:

* find conda and create an environment called `reader` with Python 3.12 — or, if
  conda is not installed, build a local `.venv` with whatever Python you have
* detect the machine and install the matching PyTorch: CUDA on an NVIDIA box
  (cu130 or cu128 depending on your driver), Metal on Apple silicon, CPU
  otherwise
* install the reader, Kokoro for the voice, and a small translation model
* run a check that actually launches a GPU kernel, rather than just importing

Then the start script activates the environment, starts the server and
opens the browser. Nothing goes on your PATH and you never need to `cd`.

If setup fails it stops at the failing step and prints why.

## Layout

```
setup-windows.bat / setup-mac.command    run once
start-windows.bat / start-mac.command    run every time
README.md                                what this is and how it works
docs/        INSTALL.md, DEPLOY.md, voices.md
requirements/core.txt, voice.txt, translate.txt
server/      the Python service
web/         the browser UI
tools/       build_ecdict.py
```

Nothing else is written here — caches, vocabulary and voice packs live in a
per-user directory that the startup banner prints.

## Prerequisites

Only Python. Either install
[Miniconda](https://docs.conda.io/en/latest/miniconda.html) (recommended — the
setup script will use it) or [Python 3.12](https://www.python.org/downloads/)
with **"Add python.exe to PATH"** ticked on the first installer screen.

On Windows, run setup from a **new** terminal after installing Python, or from
the Start menu shortcut. A terminal opened earlier will not see the new PATH.

## What you get by default

| | |
|---|---|
| voice | Kokoro 82M, Apache-2.0, twelve English voices |
| translation | `Helsinki-NLP/opus-mt-en-zh`, 77 M parameters, near-instant |
| pronunciation scoring | wav2vec2 phoneme model, downloads on first use |
| dictionary | none — see below |

Both models download themselves the first time they are used, so the first
paragraph you play and the first one you translate are slower than the rest.

## Optional: better Chinese

opus-mt is fast and small, and on ordinary prose it is fine. On dense academic
writing an instruct LLM is noticeably better — it keeps terminology consistent
and untangles long subordinate clauses instead of translating them piecewise.

Install [Ollama](https://ollama.com), then pull a model sized for your machine:

```bash
ollama pull gemma3:4b     # ~3 GB, good default, fits 16 GB of RAM
ollama pull gemma3:27b    # ~17 GB, clearly better, wants 24 GB+ of VRAM
```

Restart the reader and pick the model in the 语音 panel. Both backends stay
available, their caches are separate, and you can switch mid-document.

## Optional: offline dictionary

Without it, word lookup falls back to the translation model — usable, but you
lose phonetics, part of speech and inflection resolution ("studies" → "study").

Download `stardict.csv` from
[ECDICT](https://github.com/skywind3000/ECDICT), then, with the environment
active:

```bash
python tools/build_ecdict.py path/to/stardict.csv <data-dir>/ecdict.db
```

The startup banner prints your data directory.

## Reading the startup banner

```
  ok Kokoro 82M             12 voices
  -- Chatterbox (clone)     missing chatterbox
                            pip install chatterbox-tts  (+ torch)
  ------------------------------------------------------------
  voice      Michael · General American (kokoro)
  translate  Helsinki-NLP/opus-mt-en-zh via hf
  dictionary NONE — run tools/build_ecdict.py
  data       C:\Users\you\AppData\Local\ReadingDesk
```

`ok` means ready, `--` means not installed, with the command that would fix it.
Engines you do not want can stay `--` forever; the app only needs one.

## Where your data lives

Everything that matters — vocabulary, reading positions, the audio and
translation caches, voice packs — lives in the directory the banner prints, not
in the project folder. Replacing or deleting the project costs you nothing.

Model weights are separate again: Kokoro and the pronunciation model live in the
HuggingFace cache (`~/.cache/huggingface`), Ollama keeps its own. Neither is
touched by reinstalling.

## If something breaks

**`python` opens the Microsoft Store** — Windows ships a placeholder. Install
real Python from python.org, or turn the stub off in Settings → Apps → Advanced
app settings → App execution aliases.

**Setup says the kernel check failed on an NVIDIA card** — the driver is older
than the PyTorch build. `nvidia-smi` shows your CUDA version; update the driver,
or edit `setup-windows.bat` to force `set "IDX=cu128"`.

**macOS says the .command file is from an unidentified developer** — Gatekeeper
quarantines anything downloaded. Right-click the file and choose Open, or run
`xattr -d com.apple.quarantine setup-mac.command start-mac.command`.

**The voice sounds broken or crashes on Apple silicon** — some PyTorch/macOS
combinations have incomplete Metal kernels. The engine drops to CPU by itself
and prints why; to skip the attempt entirely, add `export PR_DEVICE=cpu` to
`start-mac.command`. An 82M model is fast enough on CPU.

**Kokoro complains about espeak** — `pip install "misaki[en]"`. On macOS,
`brew install espeak-ng`; on Windows, install it from
[espeak-ng releases](https://github.com/espeak-ng/espeak-ng/releases) and put it
on PATH.

**"No selectable text found"** — the PDF is a scan with no text layer. Run
`ocrmypdf in.pdf out.pdf` and open the result.

**Port 8848 already in use** — an older instance is still running. Close its
window, or add `set PR_PORT=8850` to the start script.

**The first paragraph is slow** — that is synthesis and translation running.
Both are cached, so a second pass through the same paper is instant.
