/* LLMersion-1 — client.
   Audio model: one sentence = one cached clip. Clips are decoded up front and
   scheduled on the Web Audio clock, so playback is gapless and the highlighter
   position is derived from ctx.currentTime rather than from timer guesswork. */

const $ = (id) => document.getElementById(id);
const api = async (url, opt) => {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
};

const S = {
  doc: null,
  blocks: [],         // [{bi, pi, unit0, sents:[...]}]  one audio file each
  units: [],          // [{bi, si, pi, text}]  flat sentence index, for navigation
  audio: new Map(),   // block index -> {buffer, rate, marks}
  inflight: new Map(),
  engine: "",
  voice: "",
  speed: 1,
  cfg: null,
  mt: { backend: "", model: "" },
  compare: new Set(),
};

const P = {
  ctx: null, gain: null,
  playing: false,
  idx: 0,             // sentence (unit) currently sounding
  queueBi: 0,         // next block to schedule
  queueSi: 0,         // sentence to enter that block at
  extra: 0,           // seconds past that sentence's start, for resume
  sources: [],
  nextTime: 0,
};

/* ---------------------------------------------------------------- utils */
let statusTimer;
function say(msg, ms = 2200) {
  const el = $("status");
  el.textContent = msg;
  el.classList.add("on");
  clearTimeout(statusTimer);
  if (ms) statusTimer = setTimeout(() => el.classList.remove("on"), ms);
}

function ctx() {
  if (!P.ctx) {
    P.ctx = new (window.AudioContext || window.webkitAudioContext)();
    P.gain = P.ctx.createGain();
    P.gain.connect(P.ctx.destination);
  }
  return P.ctx;
}

/* ---------------------------------------------------------------- audio */
async function fetchClip(text, engine, voice, speed) {
  const data = await api("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texts: [text],
      engine: engine !== undefined ? engine : S.engine,
      voice: voice !== undefined ? voice : S.voice,
      speed: speed !== undefined ? speed : S.speed,
    }),
  });
  const item = data.items[0];
  if (!item || !item.ok) throw new Error(item ? item.error : "tts failed");
  const buf = await (await fetch(item.url)).arrayBuffer();
  // engines that cannot change rate return one render plus a playbackRate
  return { buffer: await ctx().decodeAudioData(buf), rate: item.rate || 1 };
}

async function fetchBlock(b) {
  const data = await api("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      blocks: [{ text: b.text, sents: b.sents.map((x) => x.text) }],
      engine: S.engine, voice: S.voice, speed: S.speed,
    }),
  });
  const item = data.items[0];
  if (!item || !item.ok) throw new Error(item ? item.error : "tts failed");
  const raw = await (await fetch(item.url)).arrayBuffer();
  return {
    buffer: await ctx().decodeAudioData(raw),
    rate: item.rate || 1,
    marks: item.marks || [[0, 1]],
    method: item.method || "",
  };
}

function ensureAudio(bi) {
  if (bi < 0 || bi >= S.blocks.length) return Promise.resolve(null);
  if (S.audio.has(bi)) return Promise.resolve(S.audio.get(bi));
  if (S.inflight.has(bi)) return S.inflight.get(bi);
  const p = fetchBlock(S.blocks[bi])
    .then((rec) => {
      S.audio.set(bi, rec);
      S.inflight.delete(bi);
      return rec;
    })
    .catch((e) => {
      S.inflight.delete(bi);
      say("朗读失败：" + e.message, 4000);
      return null;
    });
  S.inflight.set(bi, p);
  return p;
}

function prefetch(from, n = 3) {
  for (let bi = from; bi < Math.min(from + n, S.blocks.length); bi++) ensureAudio(bi);
}

function stopAll() {
  P.sources.forEach((s) => {
    s.node.onended = null;
    try { s.node.stop(); } catch (e) { /* already stopped */ }
  });
  P.sources = [];
}

let pumping = false;
async function pump() {
  if (pumping) return;
  pumping = true;
  try {
    while (P.playing && P.sources.length < 2 && P.queueBi < S.blocks.length) {
      const bi = P.queueBi;
      const a = await ensureAudio(bi);
      if (!P.playing) break;
      if (!a) { P.queueBi++; P.queueSi = 0; P.extra = 0; continue; }

      const si = Math.min(P.queueSi, a.marks.length - 1);
      const total = a.buffer.duration;
      const offset = Math.min(total - 0.01, a.marks[si][0] * total + P.extra);
      P.queueSi = 0;
      P.extra = 0;

      const when = Math.max(ctx().currentTime + 0.04, P.nextTime);
      const node = ctx().createBufferSource();
      node.buffer = a.buffer;
      node.playbackRate.value = a.rate;
      node.connect(P.gain);
      node.start(when, offset);

      const rec = { bi, node, start: when, offset, total,
                    rate: a.rate, marks: a.marks,
                    dur: (total - offset) / a.rate };
      node.onended = () => {
        P.sources = P.sources.filter((s) => s !== rec);
        if (P.playing) {
          if (P.queueBi >= S.blocks.length && P.sources.length === 0) setPlaying(false);
          else pump();
        }
      };
      P.sources.push(rec);
      P.nextTime = when + rec.dur;
      P.queueBi = bi + 1;
      prefetch(P.queueBi, 3);
    }
  } finally {
    pumping = false;
  }
}

function startAt(unitIdx) {
  if (!S.units.length) return;
  unitIdx = Math.max(0, Math.min(unitIdx, S.units.length - 1));
  const u = S.units[unitIdx];
  stopAll();
  P.idx = unitIdx;
  P.queueBi = u.bi;
  P.queueSi = u.si;
  P.extra = 0;
  P.nextTime = 0;
  P.playing = true;
  ctx().resume();
  setPlaying(true);
  pump();
  scrollToUnit(unitIdx);
}

function resume() {
  if (!S.units.length) return;
  P.nextTime = 0;
  P.playing = true;
  ctx().resume();
  setPlaying(true);
  pump();
}

function setPlaying(on) {
  P.playing = on;
  $("play").textContent = on ? "❚❚" : "▶";
  if (!on) stopAll();
}

function pause() {
  const rec = activeSource();
  if (rec) {
    const at = bufferTime(rec);
    const si = sentenceAt(rec, at / rec.total);
    P.queueBi = rec.bi;
    P.queueSi = si;
    P.extra = Math.max(0, at - rec.marks[si][0] * rec.total);
    P.idx = S.blocks[rec.bi].unit0 + si;
  }
  setPlaying(false);
  saveProgress(true);
}

function toggle() {
  if (P.playing) pause();
  else resume();
}

function activeSource() {
  const now = ctx().currentTime;
  return P.sources.find((s) => now >= s.start && now < s.start + s.dur) || null;
}

/** Position inside the decoded buffer, in buffer seconds. */
function bufferTime(rec) {
  return rec.offset + (ctx().currentTime - rec.start) * rec.rate;
}

function sentenceAt(rec, frac) {
  for (let i = 0; i < rec.marks.length; i++) {
    if (frac < rec.marks[i][1]) return i;
  }
  return rec.marks.length - 1;
}

function duck(on) {
  if (!P.gain) return;
  P.gain.gain.setTargetAtTime(on ? 0.14 : 1.0, ctx().currentTime, 0.06);
}

/* ---------------------------------------------------------------- render */
function unitEl(i) { return document.querySelector(`.sent[data-i="${i}"]`); }

function scrollToUnit(i) {
  const el = unitEl(i);
  if (!el) return;
  const r = el.getBoundingClientRect();
  if (r.top < 90 || r.bottom > window.innerHeight - 140) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function render(doc) {
  S.doc = doc;
  S.units = [];
  S.blocks = [];
  S.audio.clear();
  S.inflight.clear();

  const root = document.createElement("div");
  root.className = "doc";

  doc.paragraphs.forEach((p) => {
    const el = document.createElement("article");
    el.className = "para " + p.kind;
    el.dataset.pi = p.id;

    const en = document.createElement("p");
    en.className = "en";
    if (p.kind === "other" || p.kind === "toc" || p.kind === "cjk") {
      en.textContent = p.text;
    } else {
      const sents = p.sents && p.sents.length
        ? p.sents : [{ start: 0, end: p.text.length, text: p.text }];
      const bi = S.blocks.length;
      S.blocks.push({ bi, pi: p.id, text: p.text, sents, unit0: S.units.length });
      sents.forEach((s, si) => {
        const idx = S.units.length;
        S.units.push({ bi, si, pi: p.id, text: s.text });
        const span = document.createElement("span");
        span.className = "sent";
        span.dataset.i = idx;
        span.textContent = s.text + " ";
        en.appendChild(span);
      });
    }
    el.appendChild(en);

    if (p.kind === "body") {
      const simp = document.createElement("button");
      simp.className = "icon simplify";
      simp.title = "简化这段（本地 LLM 改写为更易读版本）";
      simp.textContent = "简";
      simp.onclick = () => simplifyPara(el, p.text, simp);
      el.appendChild(simp);
    }
    if (p.kind === "body" || p.kind === "heading") {
      const zh = document.createElement("p");
      zh.className = "zh pending";
      zh.dataset.pi = p.id;
      zh.textContent = "…";
      el.appendChild(zh);
    }

    root.appendChild(el);
  });

  const reader = $("reader");
  reader.innerHTML = "";
  reader.appendChild(root);
  $("docTitle").textContent = doc.title;
  $("transport").hidden = false;
  $("counter").textContent = `0 / ${S.units.length}`;

  observeParas();

  const pr = doc.progress || { para: 0, sent: 0 };
  const start = S.units.findIndex((u) => u.pi === pr.para && u.si === pr.sent);
  P.idx = start > 0 ? start : 0;
  P.queueBi = S.units[P.idx] ? S.units[P.idx].bi : 0;
  P.queueSi = S.units[P.idx] ? S.units[P.idx].si : 0;
  P.extra = 0;
  if (P.idx > 0) { scrollToUnit(P.idx); say("已回到上次读到的位置"); }
  prefetch(P.queueBi, 2);
}

/* ---------------------------------------------------------------- translation
   Translation is the slowest thing in the app, so what gets translated matters
   more than how fast one call is. Priority, best first:

     1. the paragraph being read aloud, and the next few after it
     2. paragraphs currently on screen, nearest the reading position first

   A paragraph that scrolls away before its turn simply loses its place in the
   queue instead of holding one; scroll past forty paragraphs and none of them
   are translated, which is the point. */

const ZH = {
  state: new Map(),     // pi -> "busy" | "done"
  visible: new Set(),
  active: 0,
  timer: null,
  io: null,
};

const ZH_AHEAD = 4;     // paragraphs to translate ahead of the voice
const ZH_BATCH = 3;
const ZH_CONCURRENT = 2;

function zhWanted(pi) {
  const p = S.doc && S.doc.paragraphs[pi];
  if (!p) return false;
  if (p.kind !== "body" && p.kind !== "heading") return false;   // contents, formulas, CJK
  return !ZH.state.has(pi);
}

function zhTargets() {
  const here = S.units[P.idx] ? S.units[P.idx].pi : -1;
  const scored = new Map();
  if (here >= 0) {
    for (let k = 0; k <= ZH_AHEAD; k++) {
      if (zhWanted(here + k)) scored.set(here + k, k);
    }
  }
  ZH.visible.forEach((pi) => {
    if (!zhWanted(pi)) return;
    const d = here >= 0 ? Math.abs(pi - here) : pi;
    const score = 100 + d;                       // always after the reading head
    if (!scored.has(pi) || scored.get(pi) > score) scored.set(pi, score);
  });
  return [...scored.entries()].sort((a, b) => a[1] - b[1]).map((e) => e[0]);
}

function scheduleZh(delay = 60) {
  clearTimeout(ZH.timer);
  ZH.timer = setTimeout(runZh, delay);
}

async function runZh() {
  if (!S.doc || ZH.active >= ZH_CONCURRENT) return;
  const batch = zhTargets().slice(0, ZH_BATCH);
  if (!batch.length) return;
  batch.forEach((pi) => ZH.state.set(pi, "busy"));
  ZH.active++;
  if (ZH.active < ZH_CONCURRENT) scheduleZh(20);   // keep the pipe full

  const texts = batch.map((pi) => S.doc.paragraphs[pi].text);
  try {
    const res = await api("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts, backend: S.mt.backend, model: S.mt.model }),
    });
    batch.forEach((pi, k) => {
      const zh = res.items[k] || "";
      ZH.state.set(pi, "done");
      const el = document.querySelector(`.zh[data-pi="${pi}"]`);
      if (!el) return;
      if (zh) {
        el.textContent = zh;
        el.classList.remove("pending");
      } else {
        el.remove();
      }
    });
  } catch (e) {
    batch.forEach((pi) => {
      ZH.state.delete(pi);                        // let it be retried later
      const el = document.querySelector(`.zh[data-pi="${pi}"]`);
      if (el) el.classList.add("pending");
    });
  }
  ZH.active--;
  scheduleZh(40);
}

function observeParas() {
  if (ZH.io) ZH.io.disconnect();
  ZH.state.clear();
  ZH.visible.clear();
  ZH.io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      const pi = Number(e.target.dataset.pi);
      if (e.isIntersecting) ZH.visible.add(pi);
      else ZH.visible.delete(pi);
    });
    scheduleZh(120);
  }, { rootMargin: "300px 0px" });
  document.querySelectorAll(".para").forEach((el) => ZH.io.observe(el));
  scheduleZh(120);
}

/* ---------------------------------------------------------------- lookup */
let popWord = "";

function hidePop() { $("pop").hidden = true; }

const WORD_CHAR = /[A-Za-z0-9'\u2019\-]/;
const LETTER = /[A-Za-z]/;

/** Grow a partial selection out to whole words, so dragging over "un" in "run"
 *  looks up "run". Only grows when an end actually sits *inside* a word — a
 *  selection that already stopped at a space keeps its boundary instead of
 *  swallowing the next word. Punctuation is trimmed off both ends afterwards,
 *  so "steps." and "(CAT)" arrive as "steps" and "CAT". */
function snapToWords(sel) {
  if (!sel.rangeCount) return;
  const r = sel.getRangeAt(0);
  const sn = r.startContainer, en = r.endContainer;
  if (sn.nodeType !== Node.TEXT_NODE || en.nodeType !== Node.TEXT_NODE) return;
  let so = r.startOffset, eo = r.endOffset;
  const st = sn.textContent, et = en.textContent;

  if (so < st.length && WORD_CHAR.test(st[so])) {
    while (so > 0 && WORD_CHAR.test(st[so - 1])) so--;
  }
  if (eo > 0 && WORD_CHAR.test(et[eo - 1])) {
    while (eo < et.length && WORD_CHAR.test(et[eo])) eo++;
  }
  while (so < st.length && !LETTER.test(st[so])) so++;
  while (eo > 0 && !LETTER.test(et[eo - 1])) eo--;
  if (sn === en && eo <= so) return;

  try {
    const grown = document.createRange();
    grown.setStart(sn, so);
    grown.setEnd(en, eo);
    sel.removeAllRanges();
    sel.addRange(grown);
  } catch (e) { /* the selection moved under us; keep what we had */ }
}

async function lookupSelection() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !sel.toString().trim()) return;
  if (!sel.anchorNode || !$("reader").contains(sel.anchorNode)) return;
  snapToWords(sel);
  const raw = sel.toString().trim();
  if (!raw || raw.length > 60 || !/^[A-Za-z][A-Za-z'’\-\s]*$/.test(raw)) return;
  const words = raw.split(/\s+/);
  if (words.length > 4) return;

  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const pop = $("pop");
  pop.hidden = false;
  pop.style.left = Math.min(window.scrollX + rect.left, window.scrollX + window.innerWidth - 350) + "px";
  pop.style.top = window.scrollY + rect.bottom + 8 + "px";
  $("popWord").textContent = raw;
  $("popPhon").textContent = "";
  $("popZh").textContent = "查询中…";
  $("popDef").textContent = "";
  $("popSrc").textContent = "";
  popWord = raw;

  speakWord(raw);
  try {
    const d = await api("/api/lookup?q=" + encodeURIComponent(raw));
    if (popWord !== raw) return;
    $("popWord").textContent = d.word + (d.lemma_of ? ` ← ${raw}` : "");
    $("popPhon").textContent = d.phonetic ? `/${d.phonetic}/` : "";
    $("popZh").textContent = d.translation || "（未收录）";
    $("popDef").textContent = d.definition || "";
    $("popSrc").textContent = d.source;
    popWord = d.word;                     // remember the base form, not the inflection
    $("popSave").textContent = "已收录 · 移除";
    // every lookup lands in the list, dated; repeats just bump the counter
    await fetch("/api/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        word: d.word,
        zh: d.translation || "",
        phonetic: d.phonetic || "",
        context: S.units[P.idx] ? S.units[P.idx].text : "",
        doc_id: S.doc ? S.doc.doc_id : "",
      }),
    });
    loadVocab();
  } catch (e) {
    $("popZh").textContent = "查询失败";
  }
}

let wordAudio = null;
async function speakWord(text) {
  try {
    duck(true);
    const { buffer, rate } = await fetchClip(text);
    const node = ctx().createBufferSource();
    node.buffer = buffer;
    node.playbackRate.value = rate;
    node.connect(ctx().destination);
    node.onended = () => duck(false);
    if (wordAudio) { try { wordAudio.stop(); } catch (e) {} }
    wordAudio = node;
    node.start();
  } catch (e) {
    duck(false);
  }
}

/* ---------------------------------------------------------------- voices & models */
function applyConfig(cfg) {
  S.cfg = cfg;
  const d = cfg.tts.default;
  if (d && !S.engine) { S.engine = d.engine; S.voice = d.id; }
  const cur = (cfg.tts.voices || []).find((v) => v.engine === S.engine && v.id === S.voice);
  $("voiceNow").textContent = cur ? cur.label : "无可用引擎";
  if (cfg.unit) $("unit").value = cfg.unit;
  const md = cfg.mt.default || {};
  if (!S.mt.backend) S.mt = { backend: md.backend || "", model: md.model || "" };
}

function renderVoicePanel() {
  const cfg = S.cfg;
  const list = $("engineList");
  list.innerHTML = "";
  const usable = cfg.tts.engines.filter((e) => e.available).length;
  $("voiceStat").textContent =
    `${usable}/${cfg.tts.engines.length} 个引擎可用 · 克隆音色目录 ${cfg.tts.voices_dir}`;

  cfg.tts.engines.forEach((e) => {
    const box = document.createElement("div");
    box.className = "eng" + (e.available ? "" : " off");
    const tags = [
      e.cloning ? '<span class="eng-tag clone">可克隆</span>' : "",
      e.network ? '<span class="eng-tag">联网</span>' : '<span class="eng-tag">本地</span>',
      e.speed ? "" : '<span class="eng-tag">变速由前端处理</span>',
      e.loaded ? '<span class="eng-tag">已载入</span>' : "",
    ].join("");
    box.innerHTML = `<div class="eng-head">
        <span class="eng-name">${e.label}</span>${tags}
        <span class="eng-why">${e.available ? e.id : e.reason + " — " + e.notes}</span>
      </div>`;

    if (e.available) {
      const grid = document.createElement("div");
      grid.className = "voice-grid";
      cfg.tts.voices.filter((v) => v.engine === e.id).forEach((v) => {
        const row = document.createElement("label");
        const sel = v.engine === S.engine && v.id === S.voice;
        row.className = "vopt" + (sel ? " sel" : "");
        row.innerHTML = `
          <input type="checkbox" ${S.compare.has(v.key) ? "checked" : ""} title="加入对比">
          <span class="vlab">${v.label}</span>
          <span class="vacc">${v.accent || v.kind}</span>
          <button class="icon" title="设为当前">◉</button>`;
        row.querySelector("input").onchange = (ev) => {
          if (ev.target.checked) S.compare.add(v.key);
          else S.compare.delete(v.key);
          $("abStat").textContent = `已选 ${S.compare.size} 个`;
        };
        row.querySelector("button").onclick = (ev) => {
          ev.preventDefault();
          S.engine = v.engine;
          S.voice = v.id;
          applyConfig(cfg);
          renderVoicePanel();
          resetAudio();
        };
        grid.appendChild(row);
      });
      box.appendChild(grid);
    }
    list.appendChild(box);
  });

  const mt = $("mtList");
  mt.innerHTML = "";
  cfg.mt.backends.forEach((b) => {
    if (!b.available) {
      const row = document.createElement("div");
      row.className = "mopt";
      row.innerHTML = `<span>${b.label}</span><span class="mwhy">${b.reason} — ${b.notes}</span>`;
      mt.appendChild(row);
      return;
    }
    b.models.forEach((m) => {
      const row = document.createElement("div");
      const sel = S.mt.backend === b.id && S.mt.model === m.id;
      row.className = "mopt" + (sel ? " sel" : "");
      row.innerHTML = `<span>${m.label}</span><span class="mwhy">${b.id}</span>`;
      row.onclick = () => {
        S.mt = { backend: b.id, model: m.id };
        renderVoicePanel();
        ZH.state.clear();
        document.querySelectorAll(".zh").forEach((el) => {
          el.textContent = "…";
          el.classList.add("pending");
        });
        scheduleZh(0);
        say("翻译模型已切到 " + m.id + "，正在重译当前可见段落");
      };
      mt.appendChild(row);
    });
  });
}

function resetAudio() {
  S.audio.clear();
  S.inflight.clear();
  const was = P.playing;
  setPlaying(false);
  P.firstOffset = 0;
  if (was) startAt(P.idx);
}

async function openVoicePanel() {
  $("voicePanel").hidden = false;
  try {
    if (!S.cfg) applyConfig(await api("/api/config"));
    $("abText").value = $("abText").value ||
      (S.units[P.idx] ? S.units[P.idx].text : "The quick brown fox jumps over the lazy dog.");
    renderVoicePanel();
  } catch (err) {
    $("engineList").textContent = "读取配置失败：" + (err && err.message ? err.message : err);
    console.error("renderVoicePanel failed", err);
  }
}

async function comparePlay() {
  const keys = [...S.compare];
  if (!keys.length) { say("先勾选两个以上音色"); return; }
  const text = $("abText").value.trim();
  if (!text) return;
  const wasPlaying = P.playing;
  if (wasPlaying) pause();

  for (const key of keys) {
    const [engine, voice] = key.split("|");
    const v = S.cfg.tts.voices.find((x) => x.key === key);
    $("abStat").textContent = `正在播放：${v ? v.label : key}`;
    try {
      const { buffer, rate } = await fetchClip(text, engine, voice, S.speed);
      await new Promise((done) => {
        const node = ctx().createBufferSource();
        node.buffer = buffer;
        node.playbackRate.value = rate;
        node.connect(ctx().destination);
        node.onended = () => setTimeout(done, 350);
        node.start();
      });
    } catch (e) {
      $("abStat").textContent = `${key} 失败：${e.message}`;
      await new Promise((r) => setTimeout(r, 1200));
    }
  }
  $("abStat").textContent = `已播完 ${keys.length} 个`;
}

/* ---------------------------------------------------------------- vocabulary */
const V = { items: [], flash: null };

async function loadVocab() {
  const r = await api("/api/vocab");
  V.items = r.items || [];
  $("vocabCount").textContent = V.items.length;
  return V.items;
}

function dayKey(ts) {
  const d = new Date((ts || 0) * 1000);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "02-digit" });
}

function renderVocab() {
  const list = $("vocabList");
  list.innerHTML = "";
  const known = V.items.filter((x) => x.known).length;
  $("vocabStat").textContent = `${V.items.length} 词 · 已掌握 ${known}`;

  const days = new Map();
  V.items.forEach((it) => {
    const k = dayKey(it.ts);
    if (!days.has(k)) days.set(k, []);
    days.get(k).push(it);
  });

  if (!days.size) {
    list.innerHTML = '<p class="vocab-date" style="text-align:center;border:0">还没有查过词</p>';
    return;
  }

  days.forEach((items, date) => {
    const sec = document.createElement("section");
    sec.className = "vocab-day";
    const h = document.createElement("div");
    h.className = "vocab-date";
    h.textContent = `${date} · ${items.length}`;
    sec.appendChild(h);

    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "vrow" + (it.known ? " known" : "");
      row.innerHTML = `
        <div class="vword">${it.word}${it.phonetic ? `<span>/${it.phonetic}/</span>` : ""}${
        (it.hits || 1) > 1 ? `<span>×${it.hits}</span>` : ""}${
        it.best ? `<span>${it.best}分</span>` : ""}</div>
        <div class="vzh"></div>
        <div class="vact">
          <button class="icon" data-act="say" title="发音">▶</button>
          <button class="icon" data-act="known" title="标记认识">${it.known ? "↺" : "✓"}</button>
          <button class="icon" data-act="del" title="删除">✕</button>
        </div>`;
      row.querySelector(".vzh").textContent = (it.zh || "").replace(/\n/g, " / ");
      row.querySelector(".vact").onclick = async (e) => {
        const act = e.target.dataset.act;
        if (!act) return;
        if (act === "say") speakWord(it.word);
        if (act === "known") {
          await fetch("/api/vocab/known", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ word: it.word, known: it.known ? 0 : 1 }),
          });
          await loadVocab(); renderVocab();
        }
        if (act === "del") {
          await fetch("/api/vocab/" + encodeURIComponent(it.word), { method: "DELETE" });
          await loadVocab(); renderVocab();
        }
      };
      sec.appendChild(row);
    });
    list.appendChild(sec);
  });
}

async function openVocab() {
  // show the panel before rendering into it: a render error used to leave the
  // button looking dead, with the exception swallowed by the async call
  $("vocabPanel").hidden = false;
  $("vocabStat").textContent = "";
  $("vocabList").innerHTML = '<p class="vocab-date" style="border:0">读取中…</p>';
  try {
    await loadVocab();
    renderVocab();
  } catch (err) {
    $("vocabList").innerHTML = "";
    $("vocabList").textContent = "生词本打不开：" + (err && err.message ? err.message : err);
    console.error("renderVocab failed", err);
  }
}

async function mergeVocab() {
  say("正在合并…", 0);
  const r = await api("/api/vocab/merge", { method: "POST" });
  await loadVocab();
  renderVocab();
  say(`合并 ${r.groups} 组，删掉 ${r.removed} 个重复，现有 ${r.total} 词`, 3500);
}

/* ---------------------------------------------------------------- flashcards */
function flashPool() {
  const only = $("onlyUnknown").checked;
  return V.items.filter((x) => (only ? !x.known : true));
}

function openFlash() {
  const pool = flashPool();
  if (!pool.length) { say("没有可练的词"); return; }
  V.flash = { list: pool, i: 0, zh: false };
  $("flash").hidden = false;
  paintFlash();
}

function closeFlash() {
  V.flash = null;
  $("flash").hidden = true;
  loadVocab().then(renderVocab);
}

async function paintFlash() {
  const f = V.flash;
  if (!f) return;
  const it = f.list[f.i];
  $("flashWord").textContent = it.word;
  $("flashPhon").textContent = it.phonetic ? `/${it.phonetic}/` : "";
  const badges = [it.known ? "已掌握" : "", it.best ? `最好 ${it.best} 分` : ""]
    .filter(Boolean).join(" · ");
  $("flashCount").textContent = `${f.i + 1} / ${f.list.length}${badges ? " · " + badges : ""}`;
  $("flashRail").style.width = ((f.i + 1) / f.list.length) * 100 + "%";

  $("flashScore").hidden = true;
  if (REC.on) stopRec();
  const zhEl = $("flashZh");
  const ctxEl = $("flashCtx");
  zhEl.hidden = !f.zh;
  ctxEl.hidden = !f.zh || !it.context;
  if (!f.zh) return;

  ctxEl.textContent = it.context || "";
  if (it.zh) { zhEl.textContent = it.zh; return; }
  zhEl.textContent = "查询中…";
  try {
    const d = await api("/api/lookup?q=" + encodeURIComponent(it.word));
    it.zh = d.translation || d.definition || "（未收录）";
    it.phonetic = it.phonetic || d.phonetic;
    if (V.flash && V.flash.list[V.flash.i] === it && V.flash.zh) {
      zhEl.textContent = it.zh;
      $("flashPhon").textContent = it.phonetic ? `/${it.phonetic}/` : "";
    }
  } catch (e) {
    zhEl.textContent = "查询失败";
  }
}

function flashStep(d) {
  const f = V.flash;
  f.i = (f.i + d + f.list.length) % f.list.length;
  f.zh = false;
  paintFlash();
}

async function flashKnown() {
  const it = V.flash.list[V.flash.i];
  it.known = 1;
  await fetch("/api/vocab/known", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: it.word, known: 1 }),
  });
  flashStep(1);
}

/* ------------------------------------------------------------ recording
   MediaRecorder hands back webm/opus, which the server would need ffmpeg to
   open. Capturing raw samples and writing the WAV header here keeps the server
   dependency-free — soundfile reads it directly. */
const REC = { stream: null, ctx: null, node: null, chunks: [], sr: 48000, on: false };

function encodeWav(samples, sr) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buf);
  const str = (off, t) => { for (let i = 0; i < t.length; i++) view.setUint8(off + i, t.charCodeAt(i)); };
  str(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sr, true);
  view.setUint32(28, sr * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, "data"); view.setUint32(40, samples.length * 2, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++, off += 2) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

async function startRec() {
  if (REC.on) return;
  // getUserMedia only exists in a secure context: https, or a localhost origin.
  // Over plain http to a remote box the API is simply absent.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    say("麦克风需要 HTTPS 或 localhost — 用 SSH 端口转发访问即可", 7000);
    return;
  }
  try {
    REC.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) {
    say("拿不到麦克风权限", 4000);
    return;
  }
  REC.ctx = new (window.AudioContext || window.webkitAudioContext)();
  REC.sr = REC.ctx.sampleRate;
  REC.chunks = [];
  const src = REC.ctx.createMediaStreamSource(REC.stream);
  REC.node = REC.ctx.createScriptProcessor(4096, 1, 1);
  REC.node.onaudioprocess = (ev) => {
    REC.chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
  };
  src.connect(REC.node);
  REC.node.connect(REC.ctx.destination);
  REC.on = true;
  document.body.classList.add("recording");
  $("recLabel").textContent = "结束并评分";
}

function stopRec() {
  if (!REC.on) return null;
  REC.on = false;
  document.body.classList.remove("recording");
  $("recLabel").textContent = "跟读评分";
  try { REC.node.disconnect(); } catch (e) {}
  REC.stream.getTracks().forEach((t) => t.stop());
  const total = REC.chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let off = 0;
  REC.chunks.forEach((c) => { all.set(c, off); off += c.length; });
  const sr = REC.sr;
  REC.ctx.close();
  if (total < sr * 0.15) return null;
  return encodeWav(all, sr);
}

async function scoreRecording() {
  const blob = stopRec();
  const it = V.flash ? V.flash.list[V.flash.i] : null;
  if (!blob || !it) { say("录得太短了", 3000); return; }

  const box = $("flashScore");
  box.hidden = false;
  $("scoreNum").textContent = "…";
  $("scoreNum").className = "score-num";
  $("scoreNote").textContent = "正在评分";
  $("scorePhon").innerHTML = "";

  const fd = new FormData();
  fd.append("file", blob, "rec.wav");
  fd.append("word", it.word);
  fd.append("engine", S.engine);
  fd.append("voice", S.voice);
  try {
    const r = await fetch("/api/pronounce", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok || !d.ok) {
      $("scoreNum").textContent = "–";
      $("scoreNote").textContent = d.error || d.detail || "评分失败";
      return;
    }
    it.best = Math.max(it.best || 0, d.score);
    $("scoreNum").textContent = d.score;
    $("scoreNum").className = "score-num " +
      (d.score >= 85 ? "good" : d.score >= 60 ? "mid" : "poor");
    $("scoreNote").textContent = d.problems.length
      ? `${d.problems.length} 个音不对`
      : "全部对上了";
    $("scorePhon").innerHTML = d.ops.map((o) => {
      if (o.op === "ok") return `<span class="ph ok">${o.target}</span>`;
      if (o.op === "sub") return `<span class="ph sub">${o.target}<small>→${o.heard}</small></span>`;
      if (o.op === "miss") return `<span class="ph miss">${o.target}</span>`;
      return `<span class="ph extra">${o.heard}</span>`;
    }).join("");
  } catch (e) {
    $("scoreNum").textContent = "–";
    $("scoreNote").textContent = "评分失败：" + e.message;
  }
}

async function flashDelete() {
  const f = V.flash;
  const it = f.list[f.i];
  await fetch("/api/vocab/" + encodeURIComponent(it.word), { method: "DELETE" });
  f.list.splice(f.i, 1);
  V.items = V.items.filter((x) => x.word !== it.word);
  $("vocabCount").textContent = V.items.length;
  say(`已删除 ${it.word}`, 1800);
  if (!f.list.length) { closeFlash(); return; }
  if (f.i >= f.list.length) f.i = 0;
  f.zh = false;
  paintFlash();
}

function flashKey(e) {
  const f = V.flash;
  if (!f) return false;
  switch (e.key) {
    case "ArrowUp":
      speakWord(f.list[f.i].word);
      $("flash").classList.remove("spoke");
      void $("flash").offsetWidth;
      $("flash").classList.add("spoke");
      break;
    case "ArrowDown": f.zh = !f.zh; paintFlash(); break;
    case " ": flashDelete(); break;
    case "r": case "R":
      if (REC.on) scoreRecording();
      else startRec();
      break;
    case "ArrowRight": flashStep(1); break;
    case "ArrowLeft": flashStep(-1); break;
    case "Enter": flashKnown(); break;
    case "Escape": closeFlash(); break;
    default: return false;
  }
  e.preventDefault();
  return true;
}

/* ---------------------------------------------------------------- loop */
function frame() {
  requestAnimationFrame(frame);
  if (!S.units.length) return;
  const rec = activeSource();
  if (rec) {
    const frac = bufferTime(rec) / rec.total;
    const si = sentenceAt(rec, frac);
    const idx = S.blocks[rec.bi].unit0 + si;
    if (idx !== P.idx) {
      const paraChanged = !S.units[P.idx] || S.units[P.idx].pi !== S.units[idx].pi;
      P.idx = idx;
      scrollToUnit(idx);
      saveProgress();
      if (paraChanged) scheduleZh(0);
    }
    const [m0, m1] = rec.marks[si];
    paint(idx, Math.max(0, Math.min(1, (frac - m0) / Math.max(1e-6, m1 - m0))));
  } else {
    paint(P.idx, P.playing ? 0 : -1);
  }
  const f = S.units.length > 1 ? P.idx / (S.units.length - 1) : 0;
  $("trackFill").style.width = f * 100 + "%";
  $("trackKnob").style.left = f * 100 + "%";
  $("counter").textContent = `${P.idx + 1} / ${S.units.length}`;
}

let lastSaved = 0;
function saveProgress(force = false) {
  const u = S.units[P.idx];
  if (!u || !S.doc) return;
  const now = Date.now();
  if (!force && now - lastSaved < 3000) return;
  lastSaved = now;
  const body = JSON.stringify({ doc_id: S.doc.doc_id, para: u.pi, sent: u.si });
  // on the way out fetch() gets cancelled with the page; sendBeacon survives it
  if (force && navigator.sendBeacon) {
    navigator.sendBeacon("/api/progress",
      new Blob([body], { type: "application/json" }));
    return;
  }
  fetch("/api/progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  }).catch(() => {});
}

let painted = -1;
function paint(i, t) {
  if (painted !== i) {
    document.querySelectorAll(".sent.speaking").forEach((el) => {
      el.classList.remove("speaking");
      el.classList.add("done");
    });
    const el = unitEl(i);
    if (el) {
      el.classList.add("speaking");
      el.classList.remove("done");
      document.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active"));
      el.closest(".para").classList.add("active");
    }
    painted = i;
  }
  const el = unitEl(i);
  if (el && t >= 0) el.style.setProperty("--fill", t);
}

/* ---------------------------------------------------------------- nav */
function stepSent(d) { startAt(P.idx + d); }

function stepPara(d) {
  const cur = S.units[P.idx];
  if (!cur) return;
  // already partway into a block: "previous" means the top of this one
  const atTop = cur.si === 0;
  const bi = Math.max(0, Math.min(S.blocks.length - 1,
    cur.bi + (d < 0 && !atTop ? 0 : d)));
  startAt(S.blocks[bi].unit0);
}

/* ---------------------------------------------------------------- boot */
/** Windows reports an empty MIME type when no app is registered for .pdf,
 *  so trust the extension too — and never fail silently. */
function acceptFile(file) {
  if (!file) { say("没读到文件", 4000); return; }
  const exts = (S.cfg && S.cfg.formats) || [".pdf", ".txt", ".md", ".html", ".epub"];
  const name = file.name || "";
  const ok = exts.some((e) => name.toLowerCase().endsWith(e)) ||
             file.type === "application/pdf";
  if (!ok) {
    say(`读不了「${name || "未知文件"}」，支持 ${exts.join(" ")}`, 5000);
    return;
  }
  openFile(file);
}

async function openFile(file) {
  say("正在解析 PDF…", 0);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const doc = await api("/api/open", { method: "POST", body: fd });
    render(doc);
    say(`${doc.pages} 页 · ${doc.paragraphs.length} 段 · ${S.units.length} 句`);
  } catch (e) {
    say("打不开：" + e.message, 6000);
  }
}

async function boot() {
  document.body.classList.toggle("hide-zh", false);

  try {
    applyConfig(await api("/api/config"));
    if (!S.cfg.tts.default) say("没有可用的朗读引擎 — 点「语音」看每个引擎缺什么", 9000);
    else if (!S.mt.model) say("朗读已就绪，但没有翻译后端 — 点「语音」挑一个", 6000);
  } catch (e) {
    say("连不上后端服务", 6000);
  }

  $("fileInput").addEventListener("change", (e) => {
    if (e.target.files[0]) acceptFile(e.target.files[0]);
    e.target.value = "";                  // allow re-opening the same file
  });
  $("empty").addEventListener("click", () => $("fileInput").click());

  let dragDepth = 0;
  document.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth++;
    document.body.classList.add("dragging");
  });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("dragleave", () => {
    if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); }
  });
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("dragging");
    const dt = e.dataTransfer;
    if (!dt || !dt.files || !dt.files.length) {
      say("没收到文件 — 从资源管理器里拖，不要从压缩包里拖", 5000);
      return;
    }
    acceptFile(dt.files[0]);
  });

  $("play").onclick = toggle;
  $("prevSent").onclick = () => stepSent(-1);
  $("nextSent").onclick = () => stepSent(1);
  $("prevPara").onclick = () => stepPara(-1);
  $("nextPara").onclick = () => stepPara(1);

  const seek = (e) => {
    const r = $("track").getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    startAt(Math.round(f * (S.units.length - 1)));
  };
  $("track").addEventListener("pointerdown", (e) => {
    seek(e);
    const move = (ev) => seek(ev);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });

  // a double-click is the natural "look this word up" gesture, but its first
  // click would otherwise start playback — hold the play action briefly and
  // cancel it if a second click arrives
  let clickTimer = null;
  $("reader").addEventListener("click", (e) => {
    const s = e.target.closest(".sent");
    if (!s || window.getSelection().toString().trim() !== "") return;
    clearTimeout(clickTimer);
    const i = Number(s.dataset.i);
    clickTimer = setTimeout(() => startAt(i), 220);
  });
  $("reader").addEventListener("dblclick", () => {
    clearTimeout(clickTimer);
    setTimeout(lookupSelection, 10);
  });
  $("reader").addEventListener("mouseup", (e) => {
    if (e.detail > 1) return;                     // the dblclick handler has it
    setTimeout(lookupSelection, 10);
  });
  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest("#pop")) hidePop();
  });

  $("popPlay").onclick = () => speakWord(popWord);
  $("popSave").onclick = async (e) => {
    await fetch("/api/vocab/" + encodeURIComponent(popWord), { method: "DELETE" });
    e.target.textContent = "已移除";
    loadVocab();
  };

  $("voiceBtn").onclick = openVoicePanel;
  $("closeVoice").onclick = () => { $("voicePanel").hidden = true; };
  $("abPlay").onclick = comparePlay;
  $("rescanBtn").onclick = async () => {
    applyConfig(await api("/api/rescan", { method: "POST" }));
    renderVoicePanel();
    say("已重新扫描 models/ 目录");
  };
  $("unloadBtn").onclick = async () => {
    await fetch("/api/tts/unload", { method: "POST" });
    applyConfig(await api("/api/config"));
    renderVoicePanel();
    say("引擎已卸载，显存释放");
  };

  $("vocabBtn").onclick = openVocab;
  $("closeVocab").onclick = () => { $("vocabPanel").hidden = true; };
  $("mergeBtn").onclick = mergeVocab;
  $("flashBtn").onclick = openFlash;
  $("flashClose").onclick = closeFlash;
  loadVocab();

  $("zhToggle").onclick = (e) => {
    const on = document.body.classList.toggle("hide-zh");
    e.target.setAttribute("aria-pressed", String(!on));
  };
  $("themeToggle").onclick = () => {
    const cur = document.body.dataset.theme;
    document.body.dataset.theme = cur === "dark" ? "light" : "dark";
  };

  $("speed").onchange = (e) => { S.speed = parseFloat(e.target.value); resetAudio(); };
  $("unit").onchange = (e) => {
    fetch("/api/unit", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit: e.target.value }) })
      .then(() => { resetAudio(); say(e.target.value === "paragraph"
        ? "整段合成：跨句语调连贯" : "逐句合成：起播更快"); });
  };

  document.addEventListener("keydown", (e) => {
    if (flashKey(e)) return;
    if (!$("writePanel").hidden) {
      // Escape must work even while typing in the textarea
      if (e.key === "Escape") $("writePanel").hidden = true;
      if (e.target.tagName !== "TEXTAREA" || e.key === "Escape") return;
    }
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT" ||
        e.target.tagName === "TEXTAREA" || e.target.isContentEditable) return;
    if (!$("voicePanel").hidden) {
      if (e.key === "Escape") $("voicePanel").hidden = true;
      return;
    }
    if (!$("vocabPanel").hidden) {
      if (e.key === "Escape") $("vocabPanel").hidden = true;
      if (e.key === "Enter") openFlash();
      return;
    }
    const k = e.key.toLowerCase();
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); stepSent(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); stepSent(-1); }
    else if (k === "k") stepPara(-1);
    else if (k === "j") stepPara(1);
    else if (k === "t") $("zhToggle").click();
    else if (e.key === "Escape") hidePop();
  });

  // the reading position is worth more than the 3-second throttle saves
  window.addEventListener("pagehide", () => saveProgress(true));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveProgress(true);
  });

  // a swallowed exception used to look like a dead button
  window.addEventListener("error", (e) => {
    say("出错了：" + (e.message || "unknown") + "（F12 控制台有详情）", 6000);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    say("出错了：" + ((r && r.message) || r || "unknown"), 6000);
  });

  requestAnimationFrame(frame);
}

boot();


/* ---------- LLM learning features: writing practice & simplify ---------- */
function mdLite(t) {
  const esc = t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}

async function simplifyPara(el, text, btn) {
  const old = el.querySelector(".simplified");
  if (old) { old.remove(); btn.classList.remove("on"); return; }
  btn.disabled = true; btn.textContent = "…";
  try {
    const r = await fetch("/api/simplify", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }) });
    const d = await r.json();
    const box = document.createElement("p");
    box.className = "simplified";
    box.textContent = d.error ? ("⚠ " + d.error) : d.text;
    el.appendChild(box);
    btn.classList.add("on");
  } catch (e) {
    status("简化失败: " + e);
  } finally { btn.disabled = false; btn.textContent = "简"; }
}

(function initWriting() {
  const panel = $("writePanel");
  if (!panel) return;
  $("writeBtn").onclick = () => { panel.hidden = !panel.hidden;
    if (!panel.hidden) $("writeText").focus(); };
  $("writeClose").onclick = () => { panel.hidden = true; };
  $("writeGo").onclick = async () => {
    const text = $("writeText").value.trim();
    const st = $("writeStatus"), out = $("writeOut");
    st.textContent = "本地 LLM 批改中…"; out.hidden = true;
    $("writeGo").disabled = true;
    try {
      const r = await fetch("/api/writing", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }) });
      const d = await r.json();
      if (d.error) { st.textContent = "⚠ " + d.error; return; }
      out.innerHTML = mdLite(d.feedback);
      out.hidden = false; st.textContent = "";
    } catch (e) { st.textContent = "请求失败: " + e; }
    finally { $("writeGo").disabled = false; }
  };
})();
