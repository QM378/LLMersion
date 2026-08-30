#!/usr/bin/env python3
"""System benchmark over a folder of real documents (E1 + E2-lite).

Produces the numbers the paper currently states as author claims: parsing
statistics, synthesis real-time factor, boundary-recovery method rates and the
shift waveform recovery applies versus naive proportional estimation,
translation latency, dictionary lookup latency, and resident memory. Prints a
LaTeX-ready block and writes bench_results.json.

Usage (on the machine with the real models):
    python tools/bench.py D:/papers --md D:/papers_distilled \\
        --engine kokoro --voice am_michael --mt ollama --model gemma3:4b

Fast harness check without models:
    PR_DEV=1 python tools/bench.py somedir --engine dev --voice low --skip-mt

Honesty notes, also printed with the results:
* TTS and MT are timed on the first N body paragraphs per document (default
  12/8) to keep a 20-document run under an hour; N is reported.
* The boundary-shift statistic treats waveform-recovered boundaries as the
  better estimate and reports how far proportional estimation deviates from
  them. It is a divergence measure, not accuracy against human annotation.
* Every paragraph is synthesized twice with caching disabled between variants,
  so real-time factors reflect cold synthesis.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, dictionary, loaders, textseg, tts  # noqa: E402


def med_p90(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return float("nan"), float("nan")
    xs = sorted(xs)
    return st.median(xs), xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def audio_seconds(url: str) -> float:
    import soundfile as sf
    path = config.AUDIO_DIR / url.split("/")[-1]
    info = sf.info(str(path))
    return info.frames / info.samplerate


def memory_report(mt_backend: str) -> dict:
    """Account for memory where it actually lives. In-process components show
    up in this process's RSS; a model served by Ollama lives in Ollama's own
    processes; on a GPU the weights are largely in VRAM. Report each, so no
    number needs a footnote explaining what it failed to count."""
    out: dict = {}
    try:
        import psutil
        out["python_rss_gb"] = psutil.Process().memory_info().rss / 2**30
        if mt_backend == "ollama":
            total = 0
            for pr in psutil.process_iter(["name", "memory_info"]):
                try:
                    if "ollama" in (pr.info["name"] or "").lower():
                        total += pr.info["memory_info"].rss
                except Exception:
                    continue
            out["ollama_rss_gb"] = total / 2**30
    except Exception:
        pass
    try:
        import subprocess
        q = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        vals = [int(x) for x in q.stdout.split() if x.strip().isdigit()]
        if vals:
            out["gpu_used_gb"] = max(vals) / 1024
    except Exception:
        pass
    return out


def parse_stats(files: list[Path]) -> tuple[list[dict], dict]:
    docs, times = [], []
    kinds = {"body": 0, "heading": 0, "toc": 0, "other": 0, "cjk": 0}
    bad_chars, words = 0, 0
    for f in files:
        t0 = time.perf_counter()
        try:
            d = loaders.load(f, f.name)
        except Exception as exc:  # noqa: BLE001
            print(f"  PARSE FAILED {f.name}: {exc}")
            continue
        times.append(time.perf_counter() - t0)
        for p in d["paragraphs"]:
            kinds[p.get("kind", "body")] = kinds.get(p.get("kind", "body"), 0) + 1
            bad_chars += p["text"].count("\ufffd")
            words += max(1, len(p["text"].split()))
        docs.append(d)
    total = sum(kinds.values()) or 1
    return docs, {
        "documents": len(docs),
        "paragraphs": total,
        "body_pct": 100 * kinds["body"] / total,
        "filtered_pct": 100 * (kinds["toc"] + kinds["other"] + kinds["cjk"]) / total,
        "unmapped_per_10k_words": 1e4 * bad_chars / max(1, words),
        "parse_s_median": med_p90(times)[0],
    }


def bench_tts(docs: list[dict], engine: str, voice: str, n_per_doc: int) -> dict:
    rtf, shifts_ms = [], []
    methods = {"split": 0, "estimate": 0, "concat": 0}
    for d in docs:
        picked = 0
        for p in [q for q in d["paragraphs"] if q["kind"] == "body"]:
            # loaders emit raw paragraphs; sentence segmentation is the API
            # layer's job, so do it here the same way the server does
            sents = [x["text"] for x in textseg.split_sentences(p["text"])]
            if len(sents) < 2:
                continue
            picked += 1
            if picked > n_per_doc:
                break
            t0 = time.perf_counter()
            try:
                r = tts.render_block(p["text"], sents, engine, voice, 1.0)
            except Exception as exc:  # noqa: BLE001
                print(f"  tts failed: {exc}")
                continue
            dur = audio_seconds(r["url"])
            rtf.append(dur / max(1e-6, time.perf_counter() - t0))
            methods[r["method"]] = methods.get(r["method"], 0) + 1
            if r["method"] == "split":
                # divergence of naive proportional estimation from the
                # waveform-recovered boundaries, in milliseconds of audio
                chars = [len(s) + 1 for s in sents]
                total_c = sum(chars)
                est, acc = [], 0
                for c in chars[:-1]:
                    acc += c
                    est.append(acc / total_c)
                # marks are per-sentence [start, end] fractions; the boundary
                # after sentence i is that sentence's end
                rec = [m[1] for m in r["marks"][:len(est)]]
                shifts_ms += [abs(a - b) * dur * 1000 for a, b in zip(est, rec)]
    n = sum(methods.values()) or 1
    m_rtf = med_p90(rtf)
    m_sh = med_p90(shifts_ms)
    return {"paragraphs": n, "rtf_median": m_rtf[0], "rtf_p90": m_rtf[1],
            "split_pct": 100 * methods["split"] / n,
            "concat_pct": 100 * methods.get("concat", 0) / n,
            "estimate_pct": 100 * methods["estimate"] / n,
            "boundary_shift_ms_median": m_sh[0], "boundary_shift_ms_p90": m_sh[1],
            "boundaries_compared": len(shifts_ms)}


def bench_mt(docs: list[dict], backend: str, model: str, n_per_doc: int) -> dict:
    # call the manager directly, below the cache layer: a rerun must measure
    # cold translation, not cache hits
    from server.mt import MANAGER
    if not backend or not model:
        d_backend, d_model = MANAGER.default()
        backend, model = backend or d_backend, model or d_model
    lat = []
    for d in docs:
        for p in [q for q in d["paragraphs"] if q["kind"] == "body"][:n_per_doc]:
            t0 = time.perf_counter()
            try:
                MANAGER.translate([p["text"]], backend, model)
            except Exception as exc:  # noqa: BLE001
                print(f"  mt failed: {exc}")
                return {"paragraphs": len(lat), "error": str(exc),
                        **dict(zip(("s_median", "s_p90"), med_p90(lat)))}
            lat.append(time.perf_counter() - t0)
    return {"paragraphs": len(lat),
            **dict(zip(("s_median", "s_p90"), med_p90(lat)))}


def bench_lookup(n: int = 200) -> dict:
    if not dictionary.available():
        return {"available": False}
    words = ["study", "efficient", "verifiable", "throughput", "gradient"] * (n // 5)
    t0 = time.perf_counter()
    for w in words:
        dictionary.lookup(w)
    return {"available": True, "ms_mean": 1000 * (time.perf_counter() - t0) / len(words)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", help="folder of PDFs (or any supported format)")
    ap.add_argument("--md", default="", help="folder of distilled .md versions, for the cleanliness comparison")
    ap.add_argument("--engine", default="", help="TTS engine id (default: best available)")
    ap.add_argument("--voice", default="")
    ap.add_argument("--mt", default="", help="translation backend (ollama / hf)")
    ap.add_argument("--model", default="", help="translation model")
    ap.add_argument("--tts-paras", type=int, default=12, help="body paragraphs per doc to synthesize")
    ap.add_argument("--mt-paras", type=int, default=8, help="body paragraphs per doc to translate")
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--skip-mt", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in Path(args.docs).iterdir()
                   if p.suffix.lower() in loaders.EXTENSIONS)
    if not files:
        print(f"no supported documents in {args.docs}")
        return 1
    print(f"benchmarking {len(files)} documents from {args.docs}\n")
    out: dict = {"n_documents": len(files), "tts_unit": config.TTS_UNIT}
    out["gpu_baseline_gb"] = memory_report("").get("gpu_used_gb")

    print("[1/5] parsing …")
    docs, out["parse"] = parse_stats(files)

    if args.md:
        print("[2/5] distilled-md comparison …")
        mds = sorted(p for p in Path(args.md).iterdir() if p.suffix.lower() == ".md")
        _, out["parse_distilled"] = parse_stats(mds)
    else:
        print("[2/5] (no --md folder; skipping distillation comparison)")

    if not args.skip_tts:
        print("[3/5] synthesis + boundary recovery …")
        out["tts"] = bench_tts(docs, args.engine, args.voice, args.tts_paras)
    if not args.skip_mt:
        print("[4/5] translation …")
        out["mt"] = bench_mt(docs, args.mt, args.model, args.mt_paras)
    print("[5/5] lookup + memory …")
    out["lookup"] = bench_lookup()
    out["memory"] = memory_report(args.mt)

    Path("bench_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote bench_results.json\n")

    # ---- LaTeX-ready summary ------------------------------------------
    P = out["parse"]
    print("% ------- paste-ready numbers (medians; p90 in braces) -------")
    print(f"% corpus: {P['documents']} documents, {P['paragraphs']} paragraphs")
    print(f"Body paragraphs kept & {P['body_pct']:.0f}\\% \\\\")
    print(f"Non-prose filtered (toc/other/cjk) & {P['filtered_pct']:.0f}\\% \\\\")
    print(f"Unmapped glyphs per 10k words & {P['unmapped_per_10k_words']:.1f} \\\\")
    if "parse_distilled" in out:
        D = out["parse_distilled"]
        print(f"…after LLM distillation & {D['unmapped_per_10k_words']:.1f} "
              f"(filtered {D['filtered_pct']:.0f}\\%) \\\\")
    if "tts" in out:
        T = out["tts"]
        print(f"Synthesis real-time factor & {T['rtf_median']:.1f}$\\times$ "
              f"({T['rtf_p90']:.1f}$\\times$) \\\\")
        print(f"Boundary recovery: waveform / per-sentence / proportional & "
              f"{T['split_pct']:.0f}\\% / {T['concat_pct']:.0f}\\% / "
              f"{T['estimate_pct']:.0f}\\% \\\\")
        print(f"Estimation shift vs.\\ recovered, per boundary & "
              f"{T['boundary_shift_ms_median']:.0f}\\,ms ({T['boundary_shift_ms_p90']:.0f}\\,ms) "
              f"[n={T['boundaries_compared']}] \\\\")
    if "mt" in out and "s_median" in out["mt"]:
        M = out["mt"]
        print(f"Translation latency per paragraph ({args.mt or 'auto'}:{args.model or 'default'}) & "
              f"{M['s_median']:.2f}\\,s ({M['s_p90']:.2f}\\,s) \\\\")
    if out["lookup"].get("available"):
        print(f"Dictionary lookup & {out['lookup']['ms_mean']:.1f}\\,ms \\\\")
    mem = out.get("memory", {})
    if "python_rss_gb" in mem:
        print(f"Reader-process RSS & {mem['python_rss_gb']:.1f}\\,GB \\\\")
    if "ollama_rss_gb" in mem:
        print(f"Ollama server RSS & {mem['ollama_rss_gb']:.1f}\\,GB \\\\")
    if "gpu_used_gb" in mem:
        base = out.get("gpu_baseline_gb")
        extra = f" (baseline {base:.1f}, delta {mem['gpu_used_gb']-base:.1f})" if base else ""
        print(f"GPU memory in use & {mem['gpu_used_gb']:.1f}\\,GB{extra} \\\\")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
