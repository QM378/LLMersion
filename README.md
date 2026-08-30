# LLMersion-1

> **Status: newly launched (August 2026). This project is under active, continuous development; interfaces and documentation will keep evolving.**

**A teacher's voice, for everyone, on the machine you already own.**

Many people learn to read English yet cannot speak it, because solitary
reading severs the sounds of a language from its text. In natural
acquisition a person supplies the missing link: a teacher who reads the
text aloud, discusses it with you, listens to you speak, and corrects what
you write. That provision has always been rationed by cost. LLMersion-1
performs those four roles for any document you choose, entirely on your
own computer, offline after a one-time model download, for roughly the
cost of electricity.

LLMersion-1 is the open-source reference implementation of the
**LLMersion scheme** described in the accompanying paper:

> *LLMersion: An AI Agent Solution for Education, Ultra-Low-Cost Home
> Language Acquisition toward Educational Equity, Grounded in a Survey of
> Needs, Costs, and Hardware* (arXiv link: TODO after announcement)

The scheme rests on four principles, and this codebase implements all of
them: (P1) a web interface backed entirely by local, free, open-weight
models chosen for minimum hardware demand; (P2) the complete
listening-reading-speaking-writing loop, played in the teacher's order;
(P3) your own documents and your self-built vocabulary as first-class
input, not a fixed curriculum; (P4) a codebase that is AI-written,
AI-understood, and AI-updated, so customization is a conversation with a
model rather than a contract with a vendor.

## What it does

**Listen and read.** Any PDF, EPUB, HTML, Markdown, or text file becomes a
synchronized read-along session: whole paragraphs are synthesized so the
voice carries natural cross-sentence intonation, a highlighter tracks the
spoken sentence, and a parallel Chinese rendering appears beneath each
paragraph. Tap any word to hear it, see IPA and bilingual glosses, and
file it into a self-building vocabulary with flashcard review.

**Speak.** A conversation module closes the rarest loop: someone to talk
to about what you read. Sessions start from free talk, a chosen topic, or
the document currently open. Hold a key to speak; your words appear as you
say them; the tutor replies in the same voice as the reader with
sentence-synchronized captions. Each turn also returns, in parallel, a
grammar-correction card with a one-sentence rule explanation in Chinese
and segmental pronunciation feedback that folds accent-level allophone
differences so they are not scored as errors. Stored vocabulary lights up
as the tutor uses it and again when you say it yourself.

**Write.** Retell what you studied in a writing panel; the local model
returns a corrected version with changes marked, notes on the most
instructive errors, and a check of which saved words you used.

**Stay supplied.** An optional night curator fetches fresh material on
topics you rate well, ranks candidates partly by how densely they
re-encounter your saved vocabulary, rewrites them for read-aloud delivery,
and leaves ordinary Markdown files for the reader to pick up. It is
strictly decoupled: deleting it removes a convenience, never a capability.

## Quick start

Two commands on any platform. The first run downloads models (a few GB);
after that, no network is needed.

**Windows**
```
setup-windows.bat
start-windows.bat
```

**macOS**
```
./setup-mac.command
./start-mac.command
```

**Linux**: see `docs/INSTALL.md`.

Then open the printed local address in your browser. Your data (library,
vocabulary, progress) lives in a per-user data directory and survives
updates; for backward compatibility this directory is still named
`ReadingDesk` on existing installs.

## Hardware requirements

The design target is the cheapest hardware households actually have. CPU
only is fine; a GPU is used when present but never required.

| Tier | Memory | Experience |
|---|---|---|
| Floor | 8 GB | 1B tutor; full four-skill loop; scorer loads on demand |
| Comfortable | 16 GB | 3B tutor resident alongside everything else |
| Workstation | 24 GB+ | optional larger local tutors (4B-27B) |

The complete default stack (tutor LLM, voice, ear, translation) occupies
under 4 GB of memory; the worst case with the pronunciation scorer
resident is about 5 GB. See the paper's feasibility and deployment
sections for the full arithmetic.

## Models and licenses

All models are free and open-weight, and every category is a plug-in
registry, so each component can be replaced by editing one small file.
Licenses below are as published on the upstream model cards; verify
before redistributing weights.

| Role | Default model | Params | License (per model card) |
|---|---|---|---|
| Tutor | Llama 3.2 / Qwen (via Ollama) | 1-4B | Llama 3.2 Community License / Apache-2.0 |
| Voice | Kokoro | 82M | Apache-2.0 |
| Ear | Whisper (faster-whisper) | 74-244M | MIT |
| Translation | opus-mt-en-zh | 77M | CC-BY-4.0 |
| Pronunciation | wav2vec2 phoneme CTC | 0.3B | see model card |

Pedagogical behavior (tutor persona, correction policy, curator rewriting
style) lives in editable prompt files, not compiled logic. Voices,
recognizers, translators, dictionaries, and document loaders are plug-in
folders with one declared interface each: this is principle P4 in
practice, and it is also how this codebase was built and is maintained.

## Privacy

Everything runs locally. No account, no telemetry, no audio or text ever
leaves your machine. The optional curator touches the network only to
fetch public articles you asked it to look for.

## Repository layout

```
server/     reader, conversation, writing (FastAPI + vanilla JS)
talk/       conversation module (merges into the reader at startup)
curator/    optional night agent (separate process, own database)
web/        reader interface
docs/       INSTALL, DEPLOY, voices, research notes
tools/      document distiller, benchmark harnesses
```

## Evaluation status, honestly

This release claims no learning outcomes. The repository ships a designed
but not yet administered 24-item self-report instrument (see the paper's
appendix) with pre-stated expectations, and the system logs objective
traces locally (reading throughput, pronunciation trajectories, vocabulary
growth) that a future study will pair with it. The prototype is under
active development; as feedback accumulates we will upgrade it and report
findings of value.

## Citing

```bibtex
@misc{llmersion2026,
  title  = {LLMersion: An AI Agent Solution for Education, Ultra-Low-Cost
            Home Language Acquisition toward Educational Equity, Grounded
            in a Survey of Needs, Costs, and Hardware},
  author = {TODO},
  year   = {2026},
  note   = {arXiv: TODO}
}
```

## License

MIT (code). Model weights carry their own licenses; see the table above.
