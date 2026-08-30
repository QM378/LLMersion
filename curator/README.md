# The Night Curator

A minimal autonomous agent that prepares tomorrow's study material while you
sleep. Each night it picks topics (weighted by your past ratings), fetches
fresh articles from **Wikipedia** and new preprints from **arXiv**, rewrites
them into read-aloud-ready prose with a local LLM, and files them as Markdown
in your library folder. In the morning you drag them into LLMersion-1 like any
other document.

It is **fully decoupled from the reader**: no shared code paths are required,
no server needs to be running, and the only contract is the filesystem — the
curator writes ordinary `.md` files, the reader opens ordinary `.md` files.
Either works without the other.

## The agent loop, honestly described

* **Perceive** — query the public Wikipedia and arXiv APIs for candidates on
  tonight's topics (nothing already prepared is repeated).
* **Decide** — topics are scored by the mean of your 0–5 ratings, shrunk
  toward a neutral prior; most slots go to the best-scoring topics, and with
  probability ε a slot explores a *related* topic harvested from material you
  rated 4+. Among candidate articles for a topic, the winner is the one that
  **re-encounters your saved vocabulary** most densely (read from the reader's
  database, strictly read-only, with per-word saturation) — so tonight's pick
  doubles as spaced repetition of exactly the words you have been looking up.
* **Act** — fetch, rewrite every paragraph for reading aloud (math verbalized,
  citation markers dropped), write Markdown with a provenance header, and
  record the file's content hash.
* **Profile** — nightly, your recently saved words (with their source
  sentences) go to the local LLM for coarse domain grouping — "where do this
  learner's gaps concentrate?" The profile is printed in the log and its top
  domains join the exploration pool, so supply drifts toward your observed
  weak areas. Skipped when Ollama is absent; reads the reader's store
  read-only, like every signal here.
* **Learn** — two channels. Explicit: `python -m curator.feedback` records
  0–5 ratings. Implicit: the reader keys its progress by content hash, so the
  next night the curator checks whether past picks were actually opened — a
  pick you read earns a soft positive, one unopened for three days a soft
  negative, and an explicit rating always overrides an implicit one.

That is the whole policy. There are no engagement metrics, no telemetry, and
no optimization target other than the rating you choose to give. The network
is touched only to fetch public documents; everything else — the LLM, the
ratings, the library — stays on your machine.

## Setup

The curator uses the same environment as the reader — if you ran
`setup-windows.bat` / `setup-mac.command`, there is nothing to install. It
needs [Ollama](https://ollama.com) for the rewrite step; without it, material
is still produced with rule-based cleanup only.

```bash
# from the project root, with the reader's environment active
python -m curator.run --demo    # offline smoke test: writes one sample file
python -m curator.run           # one real night, right now
python -m curator.feedback      # rate what it prepared (0–5)
```

The first run creates `curator/config.json` **in your data directory** (the
reader's startup banner prints where that is). Edit it to set your topics:

```json
{
  "topics": ["machine learning", "distributed systems", "linguistics"],
  "per_night": 2,
  "sources": {"wikipedia": 1.0, "arxiv": 1.0},
  "model": "gemma3:4b",
  "simplify": 0,
  "epsilon": 0.25
}
```

`simplify: 1` allows mild sentence simplification for learners; the default
keeps the original register. `epsilon` is the exploration rate.

## Scheduling it nightly

**Windows** — run `curator\schedule-windows.bat` once. It registers a Task
Scheduler job at 02:30 every night (only runs if the machine is on). Remove
with `schtasks /Delete /TN "ReadingDesk Curator" /F`. The log is at
`%LOCALAPPDATA%\ReadingDesk\curator\night.log`.

**macOS** — run `curator/schedule-mac.command` once. It installs a launchd
agent at 02:30. Remove with
`launchctl unload ~/Library/LaunchAgents/com.linguallm.curator.plist`.
Note a sleeping Mac does not wake for launchd; the job runs at the scheduled
time if awake, or use `pmset repeat wake` to wake it.

**Linux** — `crontab -e` and add:
`30 2 * * * cd /path/to/linguallm && /path/to/python -m curator.run`

## Sources and licenses — read this once

* **Wikipedia** text is **CC BY-SA 4.0**. Every generated file records the
  source URL and an attribution line in its header; if you redistribute
  prepared material, the share-alike condition travels with it.
* **arXiv** abstracts and PDFs are fetched from the official export API with
  the pause arXiv requests from automated clients. Individual papers carry
  their own licenses; the header links the source.
* The curator prepares material **for your own study**. It does not
  redistribute anything by itself.

Video and other media sources are deliberately out of scope: subtitle-bearing
video would fit the reading-while-listening model, but downloading from video
platforms raises terms-of-service questions that a study tool should not
quietly decide for you.

## Files

```
curator/
  run.py                 the nightly loop (also --demo, --no-llm)
  feedback.py            rating CLI; updates topic weights
  select.py              ε-greedy topic policy over your ratings
  refine.py              LLM rewrite + rule-based fallback
  config.py, store.py    config.json + SQLite state, both in your data dir
  sources/
    wikipedia_source.py  search / extract / related (MediaWiki action API)
    arxiv_source.py      Atom API + optional full-PDF via the reader's parser
  nightly-windows.bat    the scheduled runner (activates the env, logs)
  schedule-windows.bat   registers the Task Scheduler job (run once)
  schedule-mac.command   installs the launchd agent (run once)
```
