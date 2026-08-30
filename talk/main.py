"""Run the conversation window beside the reader.

    python -m talk.main          normal
    python -m talk.main dev      canned tutor and canned transcript, no models

The reader keeps its port; this takes the next one. Nothing in `server/` is
touched, and the window borrows the reader's voice over loopback rather than
loading a second copy of it.
"""
from __future__ import annotations

import os
import sys


def _dev_flag() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        os.environ["PR_TALK_DEV"] = "1"


_dev_flag()

from fastapi import FastAPI                                    # noqa: E402
from fastapi.middleware.cors import CORSMiddleware             # noqa: E402
from fastapi.responses import RedirectResponse                 # noqa: E402
from fastapi.staticfiles import StaticFiles                    # noqa: E402

from . import api, bridge, config, dialogue, stt               # noqa: E402
from server import config as rc                                # noqa: E402

app = FastAPI(title="LLMersion-1 · Talk")
app.include_router(api.router)

# The panel is designed to be pulled into the reader's page later, which means
# it will be fetched from a different origin until that happens. Loopback only.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
)

WEB = rc.ROOT / "talk" / "web"
if WEB.exists():
    app.mount("/talk", StaticFiles(directory=WEB, html=True), name="talk")


@app.get("/")
def home():
    return RedirectResponse("/talk/")


def banner() -> None:
    print("\n  LLMersion-1 · 对话")
    print(f"  {'-' * 58}")
    s = stt.info()
    print(f"  {'ok ' if s['available'] else '-- '}"
          f"{'speech in':<12} {s['backend'] or 'none'}"
          f"{'  ' + s['model'] if s['available'] else '  ' + s['reason']}")
    lm = dialogue.llm_info()
    print(f"  {'ok ' if lm['available'] else '-- '}{'tutor':<12} "
          f"{lm['model'] if lm['available'] else lm['reason']}")
    v = bridge.voice_info()
    detail = f"{v['label']} ({v['engine']}) via {v['via']}" if v["available"] else "none"
    print(f"  {'ok ' if v['available'] else '-- '}{'speech out':<12} {detail}")
    print(f"  {'ok ' if v.get('gop') else '-- '}{'scoring':<12} "
          f"{'wav2vec2 phoneme alignment' if v.get('gop') else 'unavailable'}")
    print(f"  {'-' * 58}")
    if not bridge.reader_alive():
        print(f"  reader     not answering at {config.READER_URL}")
        print("             the window still works; voice and scoring load locally")
    else:
        print(f"  reader     {config.READER_URL}  (sharing its voice and scorer)")
    print(f"  data       {config.DB_PATH}")
    print(f"  {'-' * 58}")
    print(f"  http://127.0.0.1:{config.PORT}/talk/\n")


def main() -> None:
    import threading
    import uvicorn
    import webbrowser

    banner()
    if os.environ.get("PR_NO_OPEN") != "1":
        url = f"http://127.0.0.1:{config.PORT}/talk/"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=config.HOST, port=config.PORT,
                log_level=os.environ.get("PR_LOG", "warning"))


if __name__ == "__main__":
    main()
