/* LLMersion-1 · 对话浮动窗口
 *
 * One file, no dependencies, no build step. It builds its own root inside a
 * shadow tree, so it can be dropped into the reader's page later without a
 * single style colliding:
 *
 *     <script src="/talk/panel.js"></script>
 *     <script>mountTalkPanel({ getContext: () => ({doc_id, para}) })</script>
 *
 * and it is the same window either way — which is the point. A conversation
 * about the paragraph you are reading should sit *over* the paragraph, not
 * replace it with a different screen.
 *
 * The window is split the way the practice is: the tutor speaks on the left
 * with captions that follow the voice, and everything that is *yours* is on
 * the right — what you said above, what was wrong with it below. Corrections
 * never interrupt the conversation; they accumulate beside it.
 */
(function () {
  "use strict";

  const CSS = `
:host { all: initial; }
*, *::before, *::after { box-sizing: border-box; }

/* The panes below set display:grid and display:flex, which outrank the
   browser's own [hidden] { display: none }. Without this rule, hiding the
   conversation to show the setup screen silently does nothing and the two
   stack on top of each other. Keep it above every component. */
[hidden] { display: none !important; }

.win {
  --ink:#16202b; --graphite:#5b6b7c; --faint:#8c9aa8;
  --surface:#eaeef2; --card:#fdfdfc; --rule:#d3dae1;
  --marker:#ffd84d; --marker-soft:#ffe98f; --indigo:#2f3a8c; --live:#b4402d;
  --sans:"Instrument Sans",-apple-system,"Segoe UI",Roboto,sans-serif;
  --serif:"Source Serif 4",Georgia,"Times New Roman",serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --han:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;

  position: fixed; z-index: 2147483000;
  display: flex; flex-direction: column;
  width: 780px; height: 580px; min-width: 360px; min-height: 260px;
  background: var(--card); color: var(--ink);
  font-family: var(--sans); font-size: 14px; line-height: 1.5;
  border: 1px solid var(--rule); border-radius: 10px;
  box-shadow: 0 1px 2px rgba(22,32,43,.08), 0 18px 48px rgba(22,32,43,.18);
  overflow: hidden;
}
.win.dark {
  --ink:#dbe3ec; --graphite:#97a6b5; --faint:#6d7d8d;
  --surface:#0f151c; --card:#161e27; --rule:#29343f;
  --marker:#c99a15; --marker-soft:#7a5f11; --indigo:#93a4ff; --live:#e0674c;
  box-shadow: 0 1px 2px rgba(0,0,0,.5), 0 18px 48px rgba(0,0,0,.45);
}
.win.flat { position: relative; width: 100%; height: 100%; border: 0; border-radius: 0; box-shadow: none; }
.win.min { height: auto !important; }
.win.min .main, .win.min .strip, .win.min .compose { display: none; }

button, select, input, textarea { font: inherit; color: inherit; }
button {
  background: transparent; border: 1px solid transparent; border-radius: 6px;
  padding: 3px 8px; cursor: pointer; color: var(--graphite);
}
button:hover { background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--ink); }
button:focus-visible, select:focus-visible, input:focus-visible {
  outline: 2px solid var(--indigo); outline-offset: 1px;
}
button.icon { padding: 3px 6px; font-size: 13px; }
button.primary { background: var(--indigo); color: #fff; border-color: var(--indigo); font-weight: 500; }
button.primary:hover { filter: brightness(1.08); background: var(--indigo); color: #fff; }
button[disabled] { opacity: .45; cursor: default; }
.spacer { flex: 1; }

/* -------------------------------------------------------------- title bar */
.bar {
  display: flex; align-items: center; gap: 8px; flex: none;
  padding: 8px 10px; cursor: grab; user-select: none;
  background: var(--surface); border-bottom: 1px solid var(--rule);
}
.bar:active { cursor: grabbing; }
.win.flat .bar { cursor: default; }
.grip { width: 10px; height: 14px; flex: none; opacity: .45;
  background-image: radial-gradient(currentColor 1px, transparent 1px); background-size: 4px 4px; }
.title { font-weight: 600; font-size: 13px; white-space: nowrap; flex: none; }
.now { font-size: 12px; color: var(--graphite); font-family: var(--han);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); flex: none; }
.dot.on { background: #3f9160; }
.dot.off { background: var(--live); }

/* -------------------------------------------------------------- setup */
.setup { padding: 26px 22px; font-family: var(--han); overflow-y: auto; }
.setup h3 { margin: 0 0 4px; font-size: 16px; font-weight: 600; }
.setup p { margin: 0 0 16px; font-size: 12.5px; color: var(--graphite); line-height: 1.7; }
.modes { display: flex; gap: 7px; margin-bottom: 12px; flex-wrap: wrap; }
.mode {
  padding: 5px 12px; border-radius: 999px; border: 1px solid var(--rule);
  font-size: 13px; color: var(--graphite); cursor: pointer; background: transparent;
}
.mode:hover { border-color: var(--graphite); }
.mode.on { border-color: var(--indigo); color: var(--indigo); font-weight: 500;
  background: color-mix(in srgb, var(--indigo) 8%, transparent); }
.setup .field { margin-bottom: 12px; }
.setup input, .setup select {
  width: 100%; background: var(--card); border: 1px solid var(--rule);
  border-radius: 7px; padding: 7px 9px; font-size: 13px;
}
.setup .why { font-size: 11.5px; color: var(--faint); margin-top: 5px; line-height: 1.6; }
.setup .go { margin-top: 4px; }

/* -------------------------------------------------------------- main split */
.main { flex: 1; min-height: 0; display: grid; grid-template-columns: 1.05fr 1fr; }
.win.narrow .main { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
.pane { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.pane + .pane { border-left: 1px solid var(--rule); }
.win.narrow .pane + .pane { border-left: 0; border-top: 1px solid var(--rule); }

.head {
  flex: none; display: flex; align-items: center; gap: 7px;
  padding: 6px 11px; border-bottom: 1px solid var(--rule);
  font-family: var(--mono); font-size: 10.5px; letter-spacing: .09em;
  text-transform: uppercase; color: var(--faint);
}
.head button { font-family: var(--sans); font-size: 11px; text-transform: none; letter-spacing: 0; }

/* -------------------------------------------------------------- tutor side */
.stage { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 14px 10px; }
.cap {
  font-family: var(--serif); font-size: 19px; line-height: 1.55; margin-bottom: 14px;
}
.cap .s { color: var(--faint); transition: color .15s ease; }
.cap .s.on { color: var(--ink); background: var(--marker-soft); border-radius: 2px; }
.cap .s.done { color: var(--ink); }
.cap.idle .s { color: var(--ink); }
.cap mark { background: var(--marker-soft); color: inherit; border-radius: 2px; padding: 0 1px; }
.past { border-top: 1px dashed var(--rule); padding-top: 10px; }
.past .line {
  font-family: var(--serif); font-size: 13.5px; line-height: 1.6;
  color: var(--graphite); margin-bottom: 9px; cursor: pointer;
}
.past .line:hover { color: var(--ink); }
.thinking { color: var(--faint); font-style: italic; font-family: var(--serif); font-size: 17px; }

/* -------------------------------------------------------------- my side */
.mine { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 13px 8px; }
.said { margin-bottom: 11px; }
.said .txt { font-size: 14px; line-height: 1.6; }
.said .txt mark { background: var(--marker-soft); color: inherit; border-radius: 2px; padding: 0 1px; }
.said.old .txt { color: var(--graphite); font-size: 13px; }
.said .row { display: flex; align-items: center; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
.chip {
  font-family: var(--mono); font-size: 10.5px; padding: 1px 6px; border-radius: 999px;
  border: 1px solid var(--rule); color: var(--graphite); background: var(--card);
}
.chip.good { border-color: #3f9160; color: #3f9160; }
.chip.mid  { border-color: #b08320; color: #b08320; }
.chip.poor { border-color: var(--live); color: var(--live); }
.chip.act { cursor: pointer; }
.chip.act:hover { background: var(--surface); }
.live {
  font-size: 14px; line-height: 1.6; color: var(--faint); font-style: italic;
  border-left: 2px solid var(--live); padding-left: 8px; min-height: 22px;
}
.live.on { color: var(--graphite); }

/* -------------------------------------------------------------- coach */
.fix {
  flex: none; height: 44%; min-height: 96px; border-top: 1px solid var(--rule);
  display: flex; flex-direction: column;
}
.fixbody { flex: 1; min-height: 0; overflow-y: auto; padding: 11px 13px; font-family: var(--han); }
.fixnone { color: var(--faint); font-size: 12px; line-height: 1.7; }
.card { margin-bottom: 13px; }
.card .orig {
  font-family: var(--sans); font-size: 12.5px; color: var(--faint);
  text-decoration: line-through; text-decoration-color: var(--rule); margin-bottom: 3px;
}
.card .new { font-family: var(--sans); font-size: 14px; line-height: 1.55; }
.card .new mark {
  background: var(--marker-soft); color: inherit; border-radius: 2px;
  padding: 0 2px; font-weight: 500;
}
.card .why {
  font-size: 12px; color: var(--graphite); margin-top: 5px;
  border-left: 2px solid var(--marker); padding-left: 8px; line-height: 1.65;
}
.card .phon { margin-top: 5px; font-family: var(--mono); font-size: 11.5px; letter-spacing: .04em; }
.phon .sub { color: var(--live); }
.phon .miss { color: #b08320; text-decoration: line-through; }
.phon .extra { color: var(--indigo); opacity: .8; }
.card.ok .new { color: var(--graphite); font-size: 13px; }

/* -------------------------------------------------------------- word strip */
.strip {
  flex: none; display: flex; gap: 5px; align-items: center;
  padding: 7px 10px; border-top: 1px solid var(--rule);
  overflow-x: auto; scrollbar-width: none;
}
.strip::-webkit-scrollbar { display: none; }
.strip .lab { font-size: 10.5px; color: var(--faint); font-family: var(--han); white-space: nowrap; flex: none; }
.word {
  position: relative; z-index: 0; flex: none; font-size: 12px; padding: 2px 8px;
  border-radius: 999px; border: 1px solid var(--rule); color: var(--faint);
  white-space: nowrap; overflow: hidden; transition: color .2s ease, border-color .2s ease;
}
.word::before {
  content: ""; position: absolute; inset: 0; z-index: -1;
  transform-origin: left center; transform: scaleX(0); background: var(--marker-soft);
}
.word.heard { color: var(--graphite); border-color: var(--marker); }
.word.said { color: var(--ink); border-color: var(--marker); font-weight: 500; }
.word.said::before { animation: sweep .45s cubic-bezier(.4,0,.2,1) forwards; }
@keyframes sweep { to { transform: scaleX(1); } }
@media (prefers-reduced-motion: reduce) {
  .word.said::before { animation: none; transform: scaleX(1); }
}

/* -------------------------------------------------------------- composer */
.compose {
  flex: none; display: flex; align-items: center; gap: 9px;
  padding: 9px 10px; border-top: 1px solid var(--rule); background: var(--surface);
}
.mic {
  flex: none; width: 38px; height: 38px; border-radius: 50%; padding: 0;
  border: 1px solid var(--rule); background: var(--card);
  display: grid; place-items: center; cursor: pointer;
}
.mic:hover { background: var(--card); border-color: var(--graphite); }
.mic .core { width: 13px; height: 13px; border-radius: 50%; background: var(--graphite); }
.mic.live { border-color: var(--live); }
.mic.live .core { background: var(--live); border-radius: 3px; animation: pulse 1.1s ease-in-out infinite; }
@keyframes pulse { 50% { transform: scale(.7); } }
.mic[disabled] { opacity: .4; cursor: default; }
.say {
  flex: 1; min-width: 0; background: var(--card); border: 1px solid var(--rule);
  border-radius: 8px; padding: 7px 9px; font-size: 13px; font-family: var(--han);
}
.hint { font-size: 10.5px; color: var(--faint); font-family: var(--han); white-space: nowrap; }
.hint b { color: var(--graphite); font-weight: 500; }

/* -------------------------------------------------------------- overlays */
.sheet {
  position: absolute; right: 8px; top: 38px; z-index: 5; width: 250px;
  background: var(--card); border: 1px solid var(--rule); border-radius: 9px;
  box-shadow: 0 10px 30px rgba(22,32,43,.18); padding: 10px; font-size: 12px;
  font-family: var(--han);
}
.sheet h4 { margin: 0 0 7px; font-size: 11px; letter-spacing: .07em; text-transform: uppercase;
  color: var(--faint); font-family: var(--mono); font-weight: 500; }
.sheet .r { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.sheet .r .k { color: var(--graphite); flex: 1; }
.sheet .r .v { font-family: var(--mono); font-size: 11px; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 132px; }
.sheet label { display: flex; align-items: center; gap: 6px; cursor: pointer;
  color: var(--graphite); margin-bottom: 5px; }
.sheet hr { border: 0; border-top: 1px solid var(--rule); margin: 9px 0; }
.sheet .acts { display: flex; gap: 6px; }
.sheet .acts button { border-color: var(--rule); font-size: 11.5px; }

.note {
  position: absolute; left: 50%; transform: translateX(-50%); bottom: 64px;
  background: var(--ink); color: var(--card); font-size: 12px; font-family: var(--han);
  padding: 5px 11px; border-radius: 999px; z-index: 6; pointer-events: none;
  opacity: 0; transition: opacity .18s ease; max-width: 80%; text-align: center;
}
.note.on { opacity: .93; }

.grab { position: absolute; right: 0; bottom: 0; width: 15px; height: 15px;
  cursor: nwse-resize; z-index: 4; }
.grab::after { content: ""; position: absolute; right: 3px; bottom: 3px; width: 7px; height: 7px;
  border-right: 1.5px solid var(--faint); border-bottom: 1.5px solid var(--faint); }
.win.flat .grab { display: none; }

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 4px; }
`;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function encodeWav(samples, sampleRate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buf);
    const w = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    w(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE");
    w(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); w(36, "data");
    view.setUint32(40, samples.length * 2, true);
    let off = 44;
    for (let i = 0; i < samples.length; i++, off += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  /* highlight the learner's target words inside a plain string */
  function markWords(text, words) {
    const frag = document.createDocumentFragment();
    if (!words || !words.length) { frag.appendChild(document.createTextNode(text)); return frag; }
    const stems = words.map((w) => (w.endsWith("e") && w.length > 4 ? w.slice(0, -1) : w));
    const re = new RegExp("\\b(" + stems.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")
      + ")(s|es|ed|d|ing|ly|er|ers|ion|ions|al)?\\b", "gi");
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(el("mark", null, m[0]));
      last = m.index + m[0].length;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }

  /* the coach wraps what it changed in *asterisks* */
  function markStars(text) {
    const frag = document.createDocumentFragment();
    const parts = String(text).split(/\*([^*]+)\*/g);
    parts.forEach((p, i) => {
      if (!p) return;
      frag.appendChild(i % 2 ? el("mark", null, p) : document.createTextNode(p));
    });
    return frag;
  }

  window.mountTalkPanel = function mountTalkPanel(opts) {
    opts = opts || {};
    const api = (opts.apiBase || "").replace(/\/$/, "");
    const flat = !!opts.flat;
    const host = opts.host || document.body;

    const holder = el("div");
    holder.style.cssText = flat ? "position:static;height:100%"
      : "position:fixed;inset:0 auto auto 0;width:0;height:0";
    const shadow = holder.attachShadow({ mode: "open" });
    const style = el("style"); style.textContent = CSS; shadow.appendChild(style);

    const win = el("div", "win" + (flat ? " flat" : ""));
    shadow.appendChild(win);
    host.appendChild(holder);

    if (!flat) {
      win.style.left = Math.max(12, Math.round((window.innerWidth - 780) / 2)) + "px";
      win.style.top = Math.max(12, window.innerHeight - 640) + "px";
    }
    if (document.body.getAttribute("data-theme") === "dark"
      || window.matchMedia("(prefers-color-scheme: dark)").matches) win.classList.add("dark");

    // ------------------------------------------------------------ chrome
    const bar = el("div", "bar");
    const title = el("span", "title", "对话");
    const now = el("span", "now", "");
    const dSt = el("span", "dot"); dSt.title = "语音识别";
    const dLl = el("span", "dot"); dLl.title = "对话模型";
    const dTt = el("span", "dot"); dTt.title = "朗读与评分";
    const again = el("button", null, "换话题");
    const gear = el("button", "icon", "⚙"); gear.title = "设置";
    const mini = el("button", "icon", "–"); mini.title = "收起";
    const shut = el("button", "icon", "✕"); shut.title = "关闭";
    bar.append(el("span", "grip"), title, dSt, dLl, dTt, now, el("span", "spacer"), again, gear, mini);
    if (!flat) bar.appendChild(shut);

    // ------------------------------------------------------------ setup
    const setup = el("div", "setup");
    const modes = el("div", "modes");
    const mFree = el("button", "mode on", "自由说");
    const mTopic = el("button", "mode", "指定话题");
    const mDoc = el("button", "mode", "聊这篇文档");
    modes.append(mFree, mTopic, mDoc);
    const fTopic = el("div", "field"); fTopic.hidden = true;
    const topicIn = el("input");
    topicIn.placeholder = "想聊什么？比如 why my experiment keeps failing";
    fTopic.append(topicIn);
    const fDoc = el("div", "field"); fDoc.hidden = true;
    const picker = el("select");
    const docWhy = el("div", "why", "");
    fDoc.append(picker, docWhy);
    const goBtn = el("button", "primary go", "开始");
    setup.append(el("h3", null, "开口之前，选个起点"),
      el("p", null, "不管选哪个，老师都会刻意用你生词本里的词，你说的每句都会顺带评发音、顺带纠错。"),
      modes, fTopic, fDoc, goBtn);

    // ------------------------------------------------------------ main
    const main = el("div", "main"); main.hidden = true;   // setup owns the window first

    const paneT = el("div", "pane");
    const headT = el("div", "head");
    const replay = el("button", null, "▶ 再听");
    headT.append(el("span", null, "老师"), el("span", "spacer"), replay);
    const stage = el("div", "stage");
    const cap = el("div", "cap");
    const past = el("div", "past");
    stage.append(cap, past);
    paneT.append(headT, stage);

    const paneM = el("div", "pane");
    const headM = el("div", "head");
    headM.append(el("span", null, "你说的"));
    const mineWrap = el("div", "mine");
    const live = el("div", "live");
    const fix = el("div", "fix");
    const headF = el("div", "head");
    headF.append(el("span", null, "纠正"));
    const fixBody = el("div", "fixbody");
    fix.append(headF, fixBody);
    paneM.append(headM, mineWrap, fix);

    main.append(paneT, paneM);

    // ------------------------------------------------------------ bottom
    const strip = el("div", "strip");
    const compose = el("div", "compose");
    const mic = el("button", "mic"); mic.innerHTML = '<span class="core"></span>';
    mic.title = "说话（或按住空格）";
    const say = el("input", "say"); say.placeholder = "说不出口就打字，回车发送";
    const hint = el("span", "hint");
    compose.append(mic, say, hint);

    const note = el("div", "note");
    const grab = el("div", "grab");
    win.append(bar, setup, main, strip, compose, note, grab);

    const audio = new Audio();
    // 44 bytes of silence. Playing it during a real click satisfies the
    // browser's autoplay policy, so the tutor's first reply is audible instead
    // of being silently refused.
    const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAA"
      + "B9AAACABAAZGF0YQAAAAA=";
    let unlocked = false;
    function unlockAudio() {
      if (unlocked) return;
      unlocked = true;
      audio.muted = true;
      audio.src = SILENCE;
      const done = () => { audio.muted = false; };
      audio.play().then(() => { audio.pause(); done(); }).catch(done);
    }
    let sheet = null;
    let engaged = flat;   // does this window currently own the keyboard?

    // ------------------------------------------------------------ state
    const S = {
      session: null, mode: "free", topic: "", doc: null, para: null,
      docs: [], targets: [], heard: {}, said: {}, ever: {},
      autoplay: true, score: true, coach: true, interim: true,
      busy: false, health: null, capMarks: null, capSents: [],
    };

    const url = (p) => api + p;

    // Nothing here should be able to leave the window stuck on a spinner. Every
    // request carries its own deadline, and 换话题 cancels whatever is running.
    let flight = null;
    async function ask(path, init, seconds, label) {
      const ac = new AbortController();
      flight = ac;
      const t = setTimeout(() => ac.abort(), seconds * 1000);
      try {
        const r = await fetch(url(path), Object.assign({ signal: ac.signal }, init));
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || `${label}失败（${r.status}）`);
        return d;
      } catch (e) {
        if (e.name === "AbortError") throw new Error(`${label}超过 ${seconds} 秒没回应`);
        throw e;
      } finally {
        clearTimeout(t);
        if (flight === ac) flight = null;
      }
    }
    const toast = (m, ms) => {
      note.textContent = m; note.classList.add("on");
      clearTimeout(toast._t);
      toast._t = setTimeout(() => note.classList.remove("on"), ms || 2600);
    };

    // ------------------------------------------------------------ drag / resize
    if (!flat) {
      let dx = 0, dy = 0, moving = false;
      bar.addEventListener("pointerdown", (e) => {
        if (e.target.closest("button")) return;
        moving = true; bar.setPointerCapture(e.pointerId);
        const r = win.getBoundingClientRect();
        dx = e.clientX - r.left; dy = e.clientY - r.top;
      });
      bar.addEventListener("pointermove", (e) => {
        if (!moving) return;
        win.style.left = Math.min(Math.max(0, e.clientX - dx), window.innerWidth - 80) + "px";
        win.style.top = Math.min(Math.max(0, e.clientY - dy), window.innerHeight - 30) + "px";
      });
      bar.addEventListener("pointerup", () => { moving = false; });

      let rz = false, sx = 0, sy = 0, sw = 0, sh = 0;
      grab.addEventListener("pointerdown", (e) => {
        rz = true; grab.setPointerCapture(e.pointerId);
        sx = e.clientX; sy = e.clientY; sw = win.offsetWidth; sh = win.offsetHeight;
        e.preventDefault();
      });
      grab.addEventListener("pointermove", (e) => {
        if (!rz) return;
        win.style.width = Math.max(360, sw + e.clientX - sx) + "px";
        win.style.height = Math.max(260, sh + e.clientY - sy) + "px";
      });
      grab.addEventListener("pointerup", () => { rz = false; });
    }
    // one column when there is no room for two
    try {
      new ResizeObserver(() => {
        win.classList.toggle("narrow", win.clientWidth < 620);
      }).observe(win);
    } catch (e) { /* old browser: stays two-column */ }

    mini.onclick = () => {
      win.classList.toggle("min");
      mini.textContent = win.classList.contains("min") ? "▢" : "–";
    };
    let hidden = false;
    function hide() {
      hidden = true; engaged = false;
      stopRec(true); audio.pause();
      win.style.display = "none";
    }
    function show() {
      hidden = false; engaged = true;
      win.style.display = "";
    }
    // Closing the window keeps the conversation: reopening from the reader's
    // toolbar should drop you back into the same exchange, not a blank one.
    shut.onclick = hide;
    again.onclick = () => {
      audio.pause(); stopRec(true);
      if (flight) { try { flight.abort(); } catch (e) { } }
      S.busy = false;
      S.session = null; main.hidden = true; setup.hidden = false;
      now.textContent = ""; hint.textContent = "";
      goBtn.textContent = "开始";
    };

    // ------------------------------------------------------------ settings
    gear.onclick = () => {
      if (sheet) { sheet.remove(); sheet = null; return; }
      sheet = el("div", "sheet");
      const h = S.health || {};
      const r = (k, v) => {
        const d = el("div", "r"); d.append(el("span", "k", k), el("span", "v", v)); return d;
      };
      sheet.append(el("h4", null, "本机组件"));
      sheet.append(r("语音识别", h.stt && h.stt.available
        ? `${h.stt.backend} · ${h.stt.model}` : (h.stt ? h.stt.reason : "…")));
      sheet.append(r("对话模型", h.llm && h.llm.available ? h.llm.model : "未运行"));
      sheet.append(r("朗读", h.voice && h.voice.available
        ? `${h.voice.engine} · ${h.voice.via === "reader" ? "共用阅读器" : "本进程"}` : "无"));
      sheet.append(r("发音评分", h.voice && h.voice.gop ? "wav2vec2" : "不可用"));
      sheet.append(document.createElement("hr"));
      const box = (label, key) => {
        const l = el("label"); const c = el("input"); c.type = "checkbox"; c.checked = S[key];
        c.onchange = () => { S[key] = c.checked; };
        l.append(c, document.createTextNode(label)); return l;
      };
      sheet.append(box("回复自动朗读", "autoplay"),
        box("顺带发音评分", "score"),
        box("顺带语法纠正", "coach"),
        box("说话时实时出字", "interim"));
      sheet.append(document.createElement("hr"));
      const acts = el("div", "acts");
      const un = el("button", null, "释放识别显存");
      un.onclick = async () => {
        await fetch(url("/api/talk/stt/unload"), { method: "POST" });
        toast("语音识别模型已卸载"); refreshHealth();
      };
      const rs = el("button", null, "重新检测");
      rs.onclick = () => { refreshHealth(); loadDocs(); toast("已重新检测"); };
      acts.append(un, rs);
      sheet.append(acts);
      win.appendChild(sheet);
    };
    win.addEventListener("pointerdown", (e) => {
      if (sheet && !sheet.contains(e.target) && e.target !== gear) { sheet.remove(); sheet = null; }
    }, true);

    // ------------------------------------------------------------ mode picker
    function setMode(m) {
      S.mode = m;
      [[mFree, "free"], [mTopic, "topic"], [mDoc, "doc"]].forEach(([b, k]) =>
        b.classList.toggle("on", k === m));
      fTopic.hidden = m !== "topic";
      fDoc.hidden = m !== "doc";
      if (m === "topic") topicIn.focus();
    }
    mFree.onclick = () => setMode("free");
    mTopic.onclick = () => setMode("topic");
    mDoc.onclick = () => setMode("doc");
    topicIn.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") start();
    });

    // ------------------------------------------------------------ tutor side
    let capTimer = null;
    function showTutor(t, isNew) {
      // demote whatever was on stage
      if (isNew && cap.textContent.trim()) {
        const old = el("div", "line");
        old.appendChild(markWords(cap.dataset.text || cap.textContent, S.targets));
        if (cap.dataset.audio) {
          const a = cap.dataset.audio, rt = cap.dataset.rate;
          old.title = "点一下再听";
          old.onclick = () => { audio.src = url(a); audio.playbackRate = +rt || 1; audio.play(); };
        }
        past.prepend(old);
      }
      cap.textContent = "";
      cap.className = "cap";
      cap.dataset.text = t.text || "";
      cap.dataset.audio = t.audio || "";
      cap.dataset.rate = t.rate || 1;
      S.capSents = (t.sents && t.sents.length ? t.sents : [t.text || ""]);
      S.capMarks = t.marks || null;
      S.capSents.forEach((s, i) => {
        const sp = el("span", "s");
        sp.appendChild(markWords(s, S.targets));
        cap.appendChild(sp);
        if (i < S.capSents.length - 1) cap.appendChild(document.createTextNode(" "));
      });
      if (!S.capMarks) cap.classList.add("idle");
      stage.scrollTop = 0;
    }

    function showThinking(on) {
      if (!on) return;
      cap.className = "cap idle";
      cap.textContent = "";
      cap.appendChild(el("div", "thinking", "在想…"));
    }

    function followCaption() {
      cancelAnimationFrame(capTimer);
      if (!S.capMarks || !S.capMarks.length) return;
      const step = () => {
        const d = audio.duration;
        if (!d || audio.paused) { return; }
        const f = audio.currentTime / d;
        const spans = cap.querySelectorAll(".s");
        let cur = -1;
        S.capMarks.forEach((m, i) => { if (f >= m[0] && f < m[1]) cur = i; });
        spans.forEach((sp, i) => {
          sp.classList.toggle("on", i === cur);
          sp.classList.toggle("done", cur >= 0 && i < cur);
        });
        capTimer = requestAnimationFrame(step);
      };
      capTimer = requestAnimationFrame(step);
    }
    audio.addEventListener("play", followCaption);
    audio.addEventListener("pause", () => {
      cancelAnimationFrame(capTimer);
      cap.querySelectorAll(".s.on").forEach((s) => s.classList.remove("on"));
    });
    audio.addEventListener("ended", () => {
      cap.querySelectorAll(".s").forEach((s) => { s.classList.remove("on"); s.classList.add("done"); });
    });
    replay.onclick = () => {
      if (!cap.dataset.audio) { toast("这一轮没有声音"); return; }
      audio.src = url(cap.dataset.audio);
      audio.playbackRate = +cap.dataset.rate || 1;
      audio.play();
    };

    let voiceWarned = false;
    function playTurn(t) {
      if (t.voice_error && !voiceWarned) {
        voiceWarned = true;
        toast("这一轮没有声音：" + t.voice_error, 6000);
      }
      if (!S.autoplay || !t.audio) return;
      audio.src = url(t.audio);
      audio.playbackRate = t.rate || 1;
      audio.play().catch((err) => {
        toast(err && err.name === "NotAllowedError"
          ? "浏览器挡了自动播放 — 点一下「再听」，之后就会自己响"
          : "放不出声音：" + (err && err.name || err), 6000);
      });
    }

    // ------------------------------------------------------------ my side
    function scoreClass(n) { return n >= 80 ? "good" : n >= 60 ? "mid" : "poor"; }

    function showSaid(t) {
      mineWrap.querySelectorAll(".said").forEach((n) => n.classList.add("old"));
      const wrap = el("div", "said");
      const txt = el("div", "txt");
      txt.appendChild(markWords(t.text || "", S.targets));
      wrap.append(txt);
      const row = el("div", "row");
      if (typeof t.score === "number") row.append(el("span", "chip " + scoreClass(t.score), "发音 " + t.score));
      if ((t.used || []).length) row.append(el("span", "chip", "用上 " + t.used.length + " 个生词"));
      if (row.childNodes.length) wrap.append(row);
      mineWrap.insertBefore(wrap, live);
      live.textContent = ""; live.classList.remove("on");
      mineWrap.scrollTop = mineWrap.scrollHeight;
    }

    function showFix(t) {
      const card = el("div", "card");
      if (t.fixed) {
        card.append(el("div", "orig", t.text));
        const nw = el("div", "new");
        nw.appendChild(markStars(t.fixed));
        card.append(nw);
        if (t.why) card.append(el("div", "why", t.why));
      } else {
        card.classList.add("ok");
        card.append(el("div", "new", "这句没问题。"));
      }
      if (t.problems && t.problems.length) {
        const ph = el("div", "phon");
        ph.append(el("span", null, "音（已忽略口音差异）："));
        t.problems.forEach((o) => {
          const s = el("span", o.op === "sub" ? "sub" : o.op === "miss" ? "miss" : "extra");
          s.textContent = o.op === "sub" ? `${o.target}→${o.heard} `
            : o.op === "miss" ? `${o.target} ` : `${o.heard} `;
          ph.append(s);
        });
        card.append(ph);
      }
      const none = fixBody.querySelector(".fixnone");
      if (none) none.remove();
      fixBody.prepend(card);
    }

    function resetFix() {
      fixBody.textContent = "";
      fixBody.append(el("div", "fixnone",
        "你说完一句，这里会给出改过的版本和为什么这么改。说得对的时候它会直说没问题——不会为了有话说而挑毛病。"));
    }

    // ------------------------------------------------------------ word strip
    function renderStrip() {
      strip.textContent = "";
      if (!S.targets.length) {
        strip.append(el("span", "lab", "生词本还是空的 · 在阅读器里查几个词，它们会出现在这里"));
        return;
      }
      strip.append(el("span", "lab", "你的词"));
      S.targets.forEach((w) => {
        const c = el("span", "word", w);
        const ever = S.ever[w] ? `（以前说过 ${S.ever[w]} 次）` : "";
        if (S.said[w]) { c.classList.add("said"); c.title = "这轮你说出口了" + ever; }
        else if (S.heard[w]) { c.classList.add("heard"); c.title = "老师用过，还没轮到你" + ever; }
        else c.title = "还没出现" + ever;
        strip.append(c);
      });
    }

    function absorb(role, used) {
      (used || []).forEach((w) => {
        if (role === "learner") S.said[w] = (S.said[w] || 0) + 1;
        else S.heard[w] = (S.heard[w] || 0) + 1;
      });
      renderStrip();
    }

    // ------------------------------------------------------------ network
    async function refreshHealth() {
      try { S.health = await (await fetch(url("/api/talk/health"))).json(); }
      catch (e) { S.health = null; }
      const h = S.health || {};
      dSt.className = "dot " + (h.stt && h.stt.available ? "on" : "off");
      dLl.className = "dot " + (h.llm && h.llm.available ? "on" : "off");
      dTt.className = "dot " + (h.voice && h.voice.available ? "on" : "off");
      if (h.score_default === false) S.score = false;
      if (h.coach_default === false) S.coach = false;
      if (h.interim_default === false) S.interim = false;
      title.textContent = h.dev ? "对话 · dev" : "对话";
      refreshMic();
    }

    async function loadDocs() {
      try { S.docs = (await (await fetch(url("/api/talk/docs"))).json()).items || []; }
      catch (e) { S.docs = []; }
      picker.textContent = "";
      if (!S.docs.length) {
        picker.append(el("option", null, "还没有读过的文档"));
        picker.disabled = true;
        mDoc.disabled = true;
        docWhy.textContent = "在阅读器里打开过的文档才会出现在这里。";
        return;
      }
      picker.disabled = false; mDoc.disabled = false;
      S.docs.forEach((d) => {
        const o = el("option", null, d.title || d.doc_id);
        o.value = d.doc_id;
        picker.append(o);
      });
      syncWhy();
    }
    function syncWhy() {
      const d = S.docs.find((x) => x.doc_id === picker.value);
      docWhy.textContent = d
        ? `从你读到的第 ${((d.progress && d.progress.para) || 0) + 1} 段开始，只聊那附近写着的东西。` : "";
    }
    picker.onchange = syncWhy;

    async function loadWords() {
      try {
        const d = await (await fetch(url("/api/talk/words"))).json();
        S.targets = (d.items || []).slice(0, 12).map((x) => x.word);
        (d.items || []).forEach((x) => { if (x.spoken) S.ever[x.word] = x.spoken; });
        renderStrip();
      } catch (e) { /* strip stays empty */ }
    }

    async function start() {
      const ctx = (S.mode === "doc" && opts.getContext) ? opts.getContext() : null;
      const payload = { mode: S.mode, topic: topicIn.value.trim() };
      if (S.mode === "doc") {
        payload.doc_id = (ctx && ctx.doc_id) || picker.value;
        if (ctx) payload.para = ctx.para;
        if (!payload.doc_id) { toast("先选一份文档"); return; }
      }
      if (S.mode === "topic" && !payload.topic) { toast("写一句想聊什么"); topicIn.focus(); return; }

      goBtn.disabled = true; goBtn.textContent = "在想开场白…";
      try {
        const d = await ask("/api/talk/session", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }, 120, "开场");
        S.session = d.session; S.topic = d.topic;
        S.doc = d.context ? d.context.doc_id : null;
        S.para = d.context ? d.context.para : null;
        S.targets = d.targets || []; S.heard = {}; S.said = {};
        now.textContent = d.context
          ? `${d.context.title} · §${d.context.from + 1}–${d.context.to + 1}`
          : (d.topic || "自由说");
        setup.hidden = true; main.hidden = false;
        past.textContent = ""; mineWrap.textContent = ""; mineWrap.append(live);
        resetFix(); renderStrip();
        showTutor(d.turn, false); absorb("tutor", d.turn.used);
        playTurn(d.turn);
        hint.innerHTML = "按住 <b>空格</b> 说话 · <b>Esc</b> 打断";
      } catch (e) {
        toast(String(e.message || e), 5000);
      }
      goBtn.disabled = false; goBtn.textContent = "开始";
    }
    goBtn.onclick = () => { unlockAudio(); start(); };

    async function send(blob, typed) {
      if (S.busy || !S.session) return;
      S.busy = true; refreshMic();
      audio.pause();
      if (typed) { live.textContent = typed; live.classList.add("on"); }
      showThinking(true);

      const fd = new FormData();
      fd.append("session", S.session);
      fd.append("score", S.score ? "1" : "0");
      fd.append("coach", S.coach ? "1" : "0");
      if (blob) fd.append("file", blob, "turn.wav");
      if (typed) fd.append("text", typed);

      try {
        const d = await ask("/api/talk/turn", { method: "POST", body: fd }, 180, "这一轮");
        if (d.empty) {
          live.textContent = ""; live.classList.remove("on");
          showTutor({ text: cap.dataset.text, audio: cap.dataset.audio, rate: cap.dataset.rate,
            sents: S.capSents, marks: S.capMarks }, false);
          toast(d.message || "没听清", 3500);
          return;
        }
        showSaid(d.learner); absorb("learner", d.learner.used);
        showFix(d.learner);
        showTutor(d.turn, true); absorb("tutor", d.turn.used);
        playTurn(d.turn);
        S.targets = d.targets || S.targets;
        hint.innerHTML = `${d.secs.toFixed(1)}s · 按住 <b>空格</b> · <b>Esc</b> 打断`;
      } catch (e) {
        cap.className = "cap idle";
        cap.textContent = "";
        cap.appendChild(markWords(cap.dataset.text || "", S.targets));
        live.textContent = ""; live.classList.remove("on");
        toast(String(e.message || e), 5000);
      }
      S.busy = false; refreshMic();
    }

    function refreshMic() {
      const h = S.health || {};
      mic.disabled = !(h.stt && h.stt.available) || S.busy || !S.session;
      mic.title = mic.disabled && !(h.stt && h.stt.available)
        ? "没有可用的语音识别 — 可以先打字" : "说话（或按住空格）";
    }

    // ------------------------------------------------------------ microphone
    const REC = { on: false, ctx: null, node: null, stream: null, chunks: [],
      sr: 16000, cap: null, tick: null, busy: false };

    function snapshot() {
      const total = REC.chunks.reduce((n, c) => n + c.length, 0);
      const all = new Float32Array(total);
      let off = 0;
      REC.chunks.forEach((c) => { all.set(c, off); off += c.length; });
      return { blob: encodeWav(all, REC.sr), samples: total };
    }

    async function pushInterim() {
      if (!REC.on || REC.busy || S.busy || !S.interim) return;
      const snap = snapshot();
      if (snap.samples < REC.sr * 0.8) return;
      REC.busy = true;
      try {
        const fd = new FormData();
        fd.append("file", snap.blob, "part.wav");
        const d = await (await fetch(url("/api/talk/interim"), { method: "POST", body: fd })).json();
        if (REC.on && d.text) { live.textContent = d.text; live.classList.add("on"); }
      } catch (e) { /* interim is a nicety; silence is fine */ }
      REC.busy = false;
    }

    async function startRec() {
      if (REC.on || S.busy) return;
      if (!S.session) { toast("先选个起点开始"); return; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        toast("麦克风需要 https 或 localhost — 先打字也行", 5000); return;
      }
      try {
        REC.stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (e) { toast("拿不到麦克风权限", 4000); return; }
      audio.pause();                       // talking over the tutor interrupts it
      if (opts.pauseHost) { try { opts.pauseHost(); } catch (e) { } }
      REC.ctx = new (window.AudioContext || window.webkitAudioContext)();
      REC.sr = REC.ctx.sampleRate;
      REC.chunks = [];
      const src = REC.ctx.createMediaStreamSource(REC.stream);
      REC.node = REC.ctx.createScriptProcessor(4096, 1, 1);
      REC.node.onaudioprocess = (ev) => REC.chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
      src.connect(REC.node);
      REC.node.connect(REC.ctx.destination);
      REC.on = true;
      mic.classList.add("live");
      live.textContent = "…"; live.classList.remove("on");
      hint.innerHTML = "在听 · 松开发送";
      REC.tick = setInterval(pushInterim, 1600);
      // Whisper reads 30 s at a time; past that the tail would vanish silently
      REC.cap = setTimeout(() => {
        if (!REC.on) return;
        const b = stopRec();
        toast("一次说 30 秒以内", 3000);
        if (b) send(b, "");
      }, 30000);
    }

    function stopRec(discard) {
      if (!REC.on) return null;
      REC.on = false;
      clearTimeout(REC.cap); clearInterval(REC.tick);
      mic.classList.remove("live");
      hint.innerHTML = S.session ? "按住 <b>空格</b> 说话 · <b>Esc</b> 打断" : "";
      try { REC.node.disconnect(); } catch (e) { }
      try { REC.stream.getTracks().forEach((t) => t.stop()); } catch (e) { }
      const snap = snapshot();
      try { REC.ctx.close(); } catch (e) { }
      if (discard || snap.samples < REC.sr * 0.4) {
        live.textContent = ""; live.classList.remove("on");
        return null;
      }
      return snap.blob;
    }

    mic.onclick = () => {
      if (REC.on) {
        const b = stopRec();
        if (!b) { toast("太短了，再说一次"); return; }
        send(b, "");
      } else startRec();
    };

    say.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && say.value.trim()) {
        const v = say.value.trim(); say.value = "";
        send(null, v);
      }
    });

    // ------------------------------------------------------------ keys
    // Space is push-to-talk, Esc cuts the tutor off. Both only while this
    // window has the user's attention: it lives over someone else's page, and
    // stealing the space bar from the reader mid-paragraph is the wrong default.
    let held = false;
    win.addEventListener("pointerdown", () => { engaged = true; unlockAudio(); });
    document.addEventListener("pointerdown", (e) => {
      if (!flat && !holder.contains(e.target)) engaged = false;
    }, true);
    const mine = () => engaged || shadow.activeElement || win.matches(":hover");

    window.addEventListener("keydown", (e) => {
      if (hidden || !mine()) return;
      if (shadow.activeElement === say || shadow.activeElement === topicIn) return;
      if (e.code === "Escape") {
        if (!audio.paused) { audio.pause(); toast("打断了"); }
        else if (REC.on) { stopRec(true); toast("取消了这一句"); }
        e.preventDefault(); e.stopPropagation();
        return;
      }
      if (e.code !== "Space" || e.repeat) return;
      e.preventDefault(); e.stopPropagation();
      unlockAudio();
      held = true;
      startRec();
    }, true);

    window.addEventListener("keyup", (e) => {
      if (hidden || e.code !== "Space" || !held) return;
      held = false;
      e.preventDefault(); e.stopPropagation();
      const b = stopRec();
      if (!b) { toast("太短了，按住久一点"); return; }
      send(b, "");
    }, true);

    // follow the reader's position, when hosted inside it
    if (opts.getContext) {
      setInterval(async () => {
        if (!S.session || S.mode !== "doc") return;
        const c = opts.getContext();
        if (!c || c.doc_id !== S.doc || c.para === S.para) return;
        S.para = c.para;
        try {
          const d = await (await fetch(url("/api/talk/anchor"), {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session: S.session, para: c.para }),
          })).json();
          if (d.ok) now.textContent = `${d.context.title} · §${d.context.from + 1}–${d.context.to + 1}`;
        } catch (e) { }
      }, 4000);
    }

    // ------------------------------------------------------------ go
    resetFix();
    renderStrip();
    refreshHealth();
    loadDocs();
    loadWords();
    if (opts.getContext && opts.getContext()) setMode("doc");
    setInterval(refreshHealth, 20000);

    return {
      el: holder,
      start,
      show, hide,
      toggle: () => (hidden ? show() : hide()),
      visible: () => !hidden,
      destroy: () => { stopRec(true); audio.pause(); holder.remove(); },
    };
  };
})();
