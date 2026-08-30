#!/usr/bin/env python3
"""Turn-latency benchmark for the conversation module.

Produces the numbers the paper needs about conversation practice: recognition,
reply, correction and pronunciation-scoring latency, the end-to-end turn, and
the margin the parallel schedule actually buys (sum of the parts against wall
clock). Prints a LaTeX-ready block and writes talkbench_results.json.

Usage (on the machine with the real models):
    python tools/talkbench.py --n 20 --model gemma3:4b --stt base.en

Fast harness check without models:
    PR_TALK_DEV=1 python tools/talkbench.py --n 3

Honesty notes, also printed with the results:
* The "learner" audio is synthesized by the system's own voice, not recorded
  from a person. That is legitimate for LATENCY, which depends on duration and
  sample rate, and says NOTHING about recognition accuracy or score validity.
  No accuracy number may be taken from this harness.
* Utterance lengths are drawn to span short and long turns, since recognition
  cost scales with audio duration and reply cost with context length.
* Each turn runs against a fresh session, so no history accumulates; a long
  conversation is slower than these numbers by the cost of its own transcript.
* The parallel margin is measured, not asserted: the three post-recognition
  jobs are also run once in sequence for comparison.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, tts  # noqa: E402
from talk import bridge, dialogue, stt as stt_mod, store  # noqa: E402
from talk import config as tconfig  # noqa: E402

# Spoken-register sentences of increasing length: what a learner actually says
# to a tutor, not read-aloud prose.
UTTERANCES = [
    "I think so.",
    "The method is not clear to me.",
    "I read the section twice but the second part still confuses me.",
    "It says the weights come from a compatibility function, so I assume the "
    "model can look at any position directly.",
    "My understanding is that they removed the recurrent path because it "
    "forces computation to happen in order, and that is the thing they wanted "
    "to avoid for long sequences.",
]


def med_p90(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    xs = sorted(xs)
    return st.median(xs), xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def learner_audio(text: str) -> tuple[bytes, float]:
    """Synthesize one utterance and hand back the bytes a browser would post."""
    out = tts.render(text)
    path = config.AUDIO_DIR / out["url"].rsplit("/", 1)[-1]
    data = path.read_bytes()
    import soundfile as sf
    import io
    info = sf.info(io.BytesIO(data))
    return data, float(info.frames) / float(info.samplerate)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20, help="turns to time")
    ap.add_argument("--model", default="", help="override PR_TALK_MODEL")
    ap.add_argument("--stt", default="", help="override PR_STT_MODEL")
    ap.add_argument("--no-score", action="store_true", help="skip pronunciation scoring")
    ap.add_argument("--no-coach", action="store_true", help="skip correction")
    args = ap.parse_args()

    if args.model:
        tconfig.LLM_MODEL = args.model
    if args.stt:
        tconfig.STT_MODEL = args.stt

    info = stt_mod.info()
    print(f"  recogniser : {info['backend']} {info['model']} "
          f"({'ready' if info['available'] else info['reason']})")
    print(f"  tutor      : {tconfig.LLM_MODEL}")
    print(f"  voice      : {bridge.voice_info().get('engine', 'none')}")
    print(f"  scoring    : {'yes' if bridge.voice_info().get('gop') else 'unavailable'}")
    print()

    words = dialogue.target_words() or ["method", "compatibility", "boundary"]
    rec, rep, coa, sco, spk, e2e, dur = [], [], [], [], [], [], []
    seq_total: list[float] = []

    for i in range(args.n):
        text = UTTERANCES[i % len(UTTERANCES)]
        wav, seconds = learner_audio(text)
        dur.append(seconds)

        t0 = time.time()
        said = stt_mod.transcribe(wav)["text"] if info["available"] else text
        t_rec = time.time() - t0
        rec.append(t_rec)

        # --- the three post-recognition jobs, timed individually ---
        t = time.time()
        reply = dialogue.reply("free", None, "", words, [], said)
        t_rep = time.time() - t
        rep.append(t_rep)

        t_coa = 0.0
        if not args.no_coach:
            t = time.time()
            dialogue.coach(said)
            t_coa = time.time() - t
            coa.append(t_coa)

        t_sco = 0.0
        if not args.no_score:
            t = time.time()
            bridge.score(wav, said)
            t_sco = time.time() - t
            sco.append(t_sco)

        t = time.time()
        bridge.speak_block(reply)
        t_spk = time.time() - t
        spk.append(t_spk)

        # what a strictly sequential server would have taken
        seq_total.append(t_rec + t_rep + t_coa + t_sco + t_spk)
        # what the parallel schedule costs: recognition, then the slowest of the
        # three, then speaking the reply
        e2e.append(t_rec + max(t_rep, t_coa, t_sco) + t_spk)

        print(f"  [{i + 1:>3}/{args.n}] {seconds:4.1f}s audio  "
              f"rec {t_rec:5.2f}  reply {t_rep:5.2f}  coach {t_coa:5.2f}  "
              f"score {t_sco:5.2f}  speak {t_spk:5.2f}")

    def block(xs):
        m, p = med_p90(xs)
        return {"median": round(m, 3), "p90": round(p, 3), "n": len(xs)}

    out = {
        "backend": info["backend"], "stt_model": info["model"],
        "llm": tconfig.LLM_MODEL, "turns": args.n,
        "audio_seconds": block(dur),
        "recognition": block(rec), "reply": block(rep),
        "correction": block(coa), "scoring": block(sco), "synthesis": block(spk),
        "turn_parallel": block(e2e), "turn_sequential": block(seq_total),
    }
    saved = med_p90(seq_total)[0] - med_p90(e2e)[0]
    out["parallel_saving_s"] = round(saved, 3)
    Path("talkbench_results.json").write_text(json.dumps(out, indent=2))

    print()
    print("% ------- paste-ready numbers (medians; p90 in braces) -------")
    for label, key in (("Recognition (Whisper %s)" % info["model"], "recognition"),
                       ("Tutor reply", "reply"),
                       ("Correction pass", "correction"),
                       ("Pronunciation scoring", "scoring"),
                       ("Reply synthesis", "synthesis")):
        b = out[key]
        if not b["n"]:
            continue
        print(f"{label} & {b['median']:.2f}\\,s ({b['p90']:.2f}\\,s) \\\\")
    tp, ts = out["turn_parallel"], out["turn_sequential"]
    print(f"Turn, parallel schedule & {tp['median']:.2f}\\,s ({tp['p90']:.2f}\\,s) \\\\")
    print(f"Turn, if run sequentially & {ts['median']:.2f}\\,s ({ts['p90']:.2f}\\,s) \\\\")
    print()
    print("% Honesty: the learner audio is synthesized, so these are LATENCY")
    print("% numbers only. Nothing here measures recognition accuracy or the")
    print("% validity of the pronunciation score.")
    print(f"% Median audio duration timed: {out['audio_seconds']['median']:.1f}s")
    print("\nwrote talkbench_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
