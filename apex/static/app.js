// ApexOptions dashboard.
// Ticks arrive straight from the shared table (/ws/ticks) and are written to the
// page the moment they land; the engine's view arrives ~4 times a second
// (/ws/state). The Triangle is drawn every animation frame from both.
"use strict";

const $ = (id) => document.getElementById(id);
const nil = (x) => x === null || x === undefined || Number.isNaN(x);
const fmt = (x, d = 2) => nil(x) ? "—" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (x, d = 2) => nil(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d);
const inr = (x) => nil(x) ? "—" : (x < 0 ? "−" : "") + "₹" + Math.round(Math.abs(x)).toLocaleString("en-IN");
const tone = (x) => x > 0 ? "up" : x < 0 ? "down" : "";
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = { up: css("--up"), down: css("--down"), beacon: css("--beacon"), ink: css("--ink"), mist: css("--mist"),
            shelf: css("--shelf"), line: css("--line"), deep: css("--deep"), refill: css("--refill") };
const NUMF = '"Chakra Petch", "Segoe UI", sans-serif';

let INST = {}, REGV = -1, loading = false;
let S = null;
const last = {};            // id -> last ltp
const legs = {};            // id -> {el, px}
let heroSig = "";
const ages = [];
let sound = false, actx = null, lastEvKey = "", flashAt = -1e9, flashDir = 1;
const futBuf = [];          // [t_s, fut] from state, virtual clock
const pnlBuf = [];          // [t_s, pts] for the open position
let posKey = "";

// ── data in ─────────────────────────────────────────────────────────────────
async function loadInstruments() {
  try {
    const d = await (await fetch("/api/instruments")).json();
    INST = {}; for (const it of d.items) INST[it.id] = it;
    REGV = d.version;
  } catch (e) { /* retried on next version change */ }
}

function connectTicks() {
  const ws = new WebSocket(`ws://${location.host}/ws/ticks`);
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.v !== REGV && !loading) { loading = true; loadInstruments().finally(() => { loading = false; }); }
    for (const r of d.r) onTick(r);
  };
  ws.onclose = () => setTimeout(connectTicks, 1000);
}

function onTick([id, ltp, bid, ask, bq, aq, ttq, oi, age]) {
  ages.push(age); if (ages.length > 500) ages.shift();
  if (ltp === null) return;
  const prev = last[id]; last[id] = ltp;
  const it = INST[id];
  if (it && it.key === "NIFTY|FUT") paintPx($("fut"), ltp, prev);
  const L = legs[id];
  if (L) {
    paintPx(L.px, ltp, prev, true);
    L.ba.textContent = `${fmt(bid)} / ${fmt(ask)}`;
  }
  if (S && S.pos && S.pos.id === id) livePos(ltp);
}

function paintPx(el, v, prev, small) {
  el.firstChild ? (el.firstChild.nodeValue = fmt(v)) : (el.textContent = fmt(v));
  if (prev === undefined || v === prev) return;
  el.classList.remove("flash-up", "flash-down"); void el.offsetWidth;
  el.classList.add(v > prev ? "flash-up" : "flash-down");
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("flash-up", "flash-down"), 320);
}

function connectState() {
  const ws = new WebSocket(`ws://${location.host}/ws/state`);
  ws.onmessage = (m) => { try { S = JSON.parse(m.data); render(S); } catch (e) { console.log(e); } };
  ws.onclose = () => setTimeout(connectState, 1000);
}

setInterval(() => {
  const el = $("lat"), dot = $("dot");
  if (!ages.length) { el.textContent = "no ticks"; dot.className = S && S.feed === "LIVE" ? "warn" : ""; return; }
  const a = [...ages].sort((x, y) => x - y); ages.length = 0;
  const p50 = a[a.length >> 1], mx = a[a.length - 1];
  el.textContent = `tick age ${fmt(p50, 0)} ms, worst ${fmt(mx, 0)} ms`;
  dot.className = mx > 3000 ? "bad" : p50 > 800 ? "warn" : "live";
}, 1000);

// ── state → page ───────────────────────────────────────────────────────────
const clockSecs = (s) => { const t = (s || "").slice(11).split(":").map(Number); return t.length === 3 ? t[0] * 3600 + t[1] * 60 + t[2] : 0; };

function render(s) {
  const now = clockSecs(s.now);
  $("mode").textContent = s.mode === "live" ? "paper · live data" : s.mode === "sim" ? "paper · simulated market" : "paper · replay";
  $("clock").textContent = (s.now || "").slice(11);
  $("feed").textContent = { LIVE: "Live", SIM: "Simulated", REPLAY: "Replay", RECONNECTING: "Reconnecting", DEAD: "Feed down", CONNECTING: "Connecting", DONE: "Session over" }[s.feed] || s.feed;
  $("spot").textContent = fmt(s.spot);
  $("vix").textContent = fmt(s.vix);
  $("atmiv").innerHTML = nil(s.atm_iv) ? "—" : `${fmt(s.atm_iv)} <small class="${tone(s.iv5)}">${s.iv5 === null ? "" : sgn(s.iv5) + " in 5m"}</small>`;
  if (!nil(s.fut) && last[idOf("NIFTY|FUT")] === undefined) $("fut").textContent = fmt(s.fut);
  if (!nil(s.fut_prev) && !nil(s.fut)) { const c = s.fut - s.fut_prev; $("futchg").textContent = `${sgn(c)} (${sgn(c / s.fut_prev * 100)}%)`; $("futchg").className = "q-chg " + tone(c); }
  if (s.book) {
    $("cap").textContent = inr(s.book.capital);
    const d = $("daypnl"); d.textContent = `${inr(s.book.pnl_rs)} today, ${sgn(s.book.pnl_pts)} points`; d.className = tone(s.book.pnl_rs);
  }
  if (!nil(s.fut)) { futBuf.push([now, s.fut]); while (futBuf.length && now - futBuf[0][0] > 300) futBuf.shift(); }
  renderVerdict(s); renderLadder(s); renderPos(s, now); drawTrace(s); drawOI(s);
  renderStraddle(s, now); renderHeavy(s); renderTrades(s); renderBooks(s); renderTape(s);
}

const idOf = (key) => { for (const id in INST) if (INST[id].key === key) return +id; return -1; };

function corners(s) {
  const d0 = s.domino || {}, p = s.params || { m_star: 2, s_star: .5 };
  const ep = s.episode;
  const dir = ep ? ep.dir : (d0.dir || 1);
  const push = Math.max(0, (d0.z || 0) * dir) / p.m_star;
  const crowd = (dir > 0 ? d0.S_up : d0.S_dn) / p.s_star || 0;
  let fresh = 0.35;                                   // no move under way
  if (ep && !nil(s.late)) fresh = s.late < 1 ? 1 + 0.25 * (1 - s.late) : Math.max(0, 2 - s.late);
  return { dir, push, crowd, fresh, ep: !!ep, closed: push >= 1 && crowd >= 1 && ep && fresh >= 1 };
}

function humanReason(r, s) {
  const p = s.params || {};
  let m;
  if (!r) return "Waiting for data";
  if (r === "no episode") return "Calm. Waiting for a move to start.";
  if (r === "in position") return "In a trade.";
  if (r === "outside entry window") return "Outside entry hours (9:25 to 15:15).";
  if (r === "already traded this episode") return "Already traded this move. Waiting for the next one.";
  if (r === "impulse against the episode") return "Futures are pushing against the move that started.";
  if ((m = r.match(/^impulse z (-?[\d.]+) < ([\d.]+)/))) return `Push is ${m[1]} of the ${m[2]} needed.`;
  if ((m = r.match(/^synchrony ([\d.]+) < ([\d.]+)/))) return `${Math.round(m[1] * 100)}% of heavyweight weight is moving together; ${Math.round(m[2] * 100)}% needed.`;
  if ((m = r.match(/^LATE: futures already (\d+) pts/))) return `Too late: futures already ran ${m[1]} points since the move began.`;
  if ((m = r.match(/^LATE: ATM IV \+([\d.]+)/))) return `Too late: option IV already up ${m[1]} points since the move began.`;
  if ((m = r.match(/^gate (\w+): (.*)/))) return `Blocked by a learned rule (${ADV[m[1]] || m[1]}): ${m[2]}.`;
  if (/^no (CE|PE) in delta band/.test(r)) return "No contract in the right delta band right now.";
  if (/move (UP|DOWN)/.test(r)) return "All three corners met. Entering.";
  return r;
}

const ADV = { iv_late: "IV not stretched", room: "Room to the next wall", coherence: "Hero contracts agree",
              force: "Level not holding firm", episode: "Basket led the move", book: "Orders on the contract",
              premium: "Premium being bought", quiet: "Market awake", bank: "Bank Nifty agrees", event: "No event today",
              gamma_leg: "Straddle leg agrees", gex_room: "Dealer gamma allows it" };

function renderVerdict(s) {
  const v = $("verdict"), c = corners(s);
  if (s.pos) {
    const pts = (last[s.pos.id] ?? s.pos.last) - s.pos.entry;
    v.innerHTML = `Holding ${s.pos.strike} ${s.pos.rr}, <span class="${tone(pts)}">${sgn(pts)} points</span>`;
    v.className = "verdict";
  } else {
    v.textContent = humanReason(s.reason, s);
    v.className = "verdict" + (c.closed ? " fire" : "");
  }
  const ep = s.episode;
  $("episode").innerHTML = ep
    ? `Move <b class="${ep.dir > 0 ? "up" : "down"}">${ep.dir > 0 ? "up" : "down"}</b>, ${fmt(ep.age, 0)} s old. ${{ "BASKET-LED": "Heavyweights moved first", "FUTURES-LED": "Futures moved first", "SINGLE-NAME": "One stock is doing it alone", "CO-FIRST": "Heavyweights and futures moved together", "FORMING": "Still forming" }[ep.type] || ep.type}${ep.first ? `, first was <b>${ep.first}</b>` : ""}; ${ep.n_cross} ${ep.n_cross === 1 ? "name" : "names"} joined. IV ${s.iv_rise === null ? "—" : sgn(s.iv_rise)} since it began.`
    : "No move under way.";
  const a = s.advisors || {}, gates = s.gates || [];
  $("advisors").innerHTML = Object.keys(ADV).map(k => {
    const x = a[k];
    const cls = !x ? "idle" : x.veto ? "veto" : "";
    return `<li class="${cls}${gates.includes(k) ? " gate" : ""}" title="${x ? x.why.replace(/"/g, "'") : "waits for a move"}">${ADV[k]}${gates.includes(k) ? " (rule)" : ""}${x && x.veto ? ": no" : ""}</li>`;
  }).join("");
  const p = s.params || {};
  $("champ").textContent = `Lead book ${s.champion}: push ≥ ${p.m_star}, together ≥ ${Math.round((p.s_star || 0) * 100)}%, stop ${p.d_star} futures points. ${gates.length ? "Learned rules: " + gates.map(g => ADV[g]).join(", ") + "." : "No learned rules yet."}`;
}

function renderLadder(s) {
  const hs = s.heroes || [];
  const sig = hs.map(h => h.id).join(",") + "|" + s.atm;
  const by = {};
  for (const h of hs) (by[h.strike] = by[h.strike] || {})[h.rr] = h;
  const ks = Object.keys(by).map(Number).sort((a, b) => b - a);
  if (sig !== heroSig) {
    heroSig = sig;
    const box = $("lad"); box.innerHTML = "";
    for (const k in legs) delete legs[k];
    for (const k of ks) {
      for (const side of ["CE", "K", "PE"]) {
        const el = document.createElement("div");
        if (side === "K") { el.className = "k" + (k === s.atm ? " atm" : ""); el.textContent = k; box.appendChild(el); continue; }
        const h = by[k][side];
        el.className = "leg " + side.toLowerCase();
        el.innerHTML = `<div class="px">—<small></small></div><div class="tug"><i></i></div><div class="meta"></div><div class="meta ord"></div>`;
        box.appendChild(el);
        if (h) {
          const px = el.querySelector(".px");
          legs[h.id] = { el, px, ba: px.querySelector("small"), tug: el.querySelector(".tug i"), meta: el.querySelector(".meta"), ord: el.querySelector(".ord") };
          if (last[h.id] !== undefined) px.firstChild.nodeValue = fmt(last[h.id]);
        }
      }
    }
  }
  for (const h of hs) {
    const L = legs[h.id]; if (!L) continue;
    const b = h.sb || 0, a = h.ss || 0;
    L.tug.style.width = (b + a > 0 ? b / (b + a) * 100 : 50) + "%";
    L.meta.innerHTML = `<span>Δ <b>${fmt(h.delta, 2)}</b> IV <b>${fmt(h.iv, 1)}</b></span><span>${nil(h.vol_s) ? "—" : fmt(h.vol_s / 1000, 1) + "k/s"}</span><span>OI <b class="${tone(h.oi_chg)}">${nil(h.oi_chg) ? "—" : sgn(h.oi_chg / 1000, 0) + "k"}</b></span><span class="c-${h.cls_s}" title="sellers: ${h.cls_s}">${SH[h.cls_s] || "—"}</span>`;
    const oppO = h.rr === "CE" ? h.cls_so : h.cls_bo, oppOrd = h.rr === "CE" ? h.sso : h.sbo, forOrd = h.rr === "CE" ? h.sbo : h.sso;
    const leadCls = h.lead >= 0.3 ? "up" : h.lead <= -0.3 ? "down" : "mist";
    L.ord.innerHTML = `<span title="resting orders: buyers vs sellers">orders <b>${fmt(forOrd, 0)}</b> v <b>${fmt(oppOrd, 0)}</b></span><span class="c-${oppO}" title="opposing side's order count">${h.rr === "CE" ? "seller" : "buyer"} orders ${SH[oppO] || "—"}</span><span class="${leadCls}" title="does this contract's book lead its price? (−1 to +1)">book→px ${sgn(h.lead, 2)}</span>`;
    L.el.classList.toggle("hot", (h.run_up || 0) >= 0.3);
    L.el.classList.toggle("held", !!(s.pos && s.pos.id === h.id));
  }
  const st = s.straddle || {};
  $("expiry").innerHTML = `expiry ${s.w0 || "—"}, ATM ${s.atm ?? "—"} · straddle <b>${fmt(st.px, 1)}</b>${st.vwap ? ` vs VWAP ${fmt(st.vwap, 1)} <b class="${/EXPAND|ABOVE/.test(st.state) ? "up" : "down"}">${(st.state || "").toLowerCase()}</b>` : ""} · together up ${pct(s.K_up)} down ${pct(s.K_dn)}`;
}
const SH = { "REFILLING": "refill", "HOLDING": "hold", "DRAIN-SLOW": "drain", "DRAIN-FAST": "drain fast", "PULLED": "pulled" };
const pct = (x) => nil(x) ? "—" : Math.round(x * 100) + "%";

function renderPos(s, now) {
  const p = s.pos, box = $("pos");
  if (!p) {
    posKey = ""; pnlBuf.length = 0;
    const b = s.book || {};
    box.innerHTML = `<div class="flat">Flat<small>${b.trades ? `${b.trades} trades today, ${b.wins} won. Next trade uses ${inr(b.capital)}.` : `₹1,00,000 ready. Every trade goes all in; profits roll into the next.`}</small></div>`;
    $("poshint").textContent = "";
    drawPosLine();
    return;
  }
  const key = p.key + p.time_in;
  if (key !== posKey) { posKey = key; pnlBuf.length = 0; box.innerHTML = ""; }
  const ltp = last[p.id] ?? p.last;
  pnlBuf.push([now, ltp - p.entry]);
  if (pnlBuf.length > 3000) pnlBuf.splice(0, pnlBuf.length - 3000);
  if (!box.firstChild) {
    box.innerHTML = `<div class="what ${p.rr === "CE" ? "up" : "down"}">Long ${p.lots} lots Nifty ${p.strike} ${p.rr}</div>
      <div class="big" id="pospnl">—</div>
      <div class="row"><span>Bought at <b>${fmt(p.entry)}</b></span><span>Now <b id="poslast">—</b></span><span>Best <b id="pospeak">—</b></span></div>
      <div class="row"><span>Futures in <b>${fmt(p.fut_in, 1)}</b></span><span>Stop at futures <b id="posstop">—</b></span><span id="postrail"></span></div>`;
  }
  $("posstop").textContent = fmt(p.stop_fut, 1);
  $("postrail").textContent = p.trail ? "Trailing" : "";
  $("pospeak").textContent = sgn(p.peak_pts);
  $("poshint").textContent = `${p.expiry}, in at ${p.time_in}`;
  livePos(ltp);
}

function livePos(ltp) {
  const p = S && S.pos; if (!p || !$("pospnl")) return;
  const pts = ltp - p.entry;
  const el = $("pospnl"); el.textContent = `${inr(pts * p.qty)}  ${sgn(pts)} pts`; el.className = "big " + tone(pts);
  $("poslast").textContent = fmt(ltp);
  $("verdict").innerHTML = `Holding ${p.strike} ${p.rr}, <span class="${tone(pts)}">${sgn(pts)} points</span>`;
  drawPosLine();
}

// ── canvases ───────────────────────────────────────────────────────────────
function fit(cv) {
  const r = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight || +cv.getAttribute("height");
  if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) { cv.width = Math.round(w * r); cv.height = Math.round(h * r); }
  const g = cv.getContext("2d"); g.setTransform(r, 0, 0, r, 0, 0); return [g, w, h];
}
function alpha(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }

function drawPosLine() {
  const cv = $("posline"); const [g, w, h] = fit(cv); g.clearRect(0, 0, w, h);
  if (pnlBuf.length < 2) return;
  const t0 = pnlBuf[0][0], t1 = pnlBuf[pnlBuf.length - 1][0] || t0 + 1;
  let mx = 1; for (const x of pnlBuf) if (Math.abs(x[1]) > mx) mx = Math.abs(x[1]);
  const X = (t) => (t - t0) / Math.max(t1 - t0, 1) * (w - 4) + 2, Y = (v) => h / 2 - v / mx * (h / 2 - 4);
  g.strokeStyle = C.line; g.beginPath(); g.moveTo(0, h / 2); g.lineTo(w, h / 2); g.stroke();
  const lastV = pnlBuf[pnlBuf.length - 1][1];
  g.beginPath(); pnlBuf.forEach(([t, v], i) => i ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v)));
  g.strokeStyle = lastV >= 0 ? C.up : C.down; g.lineWidth = 2; g.stroke();
  g.lineTo(X(t1), h / 2); g.lineTo(X(t0), h / 2); g.closePath(); g.fillStyle = alpha(lastV >= 0 ? C.up : C.down, .12); g.fill();
}

function drawTrace(s) {
  const cv = $("futline"); const [g, w, h] = fit(cv); g.clearRect(0, 0, w, h);
  if (futBuf.length < 2) { $("tracehint").textContent = ""; return; }
  const t1 = futBuf[futBuf.length - 1][0], t0 = t1 - 300;
  const lv = [];
  if (s.episode) lv.push([s.episode.fut0, C.beacon, "move began"]);
  if (s.pos) { lv.push([s.pos.fut_in, C.ink, "entry"]); if (!nil(s.pos.stop_fut)) lv.push([s.pos.stop_fut, C.down, "stop"]); }
  const ys = futBuf.map(x => x[1]).concat(lv.map(x => x[0]));
  let lo = Math.min(...ys), hi = Math.max(...ys); const pad = Math.max(2, (hi - lo) * .12); lo -= pad; hi += pad;
  const X = (t) => (t - t0) / 300 * (w - 84), Y = (v) => h - 14 - (v - lo) / (hi - lo) * (h - 24);
  if (s.episode) { const ta = t1 - s.episode.age; g.fillStyle = alpha(s.episode.dir > 0 ? C.up : C.down, .08); g.fillRect(X(ta), 0, X(t1) - X(ta), h - 12); }
  g.font = `12px ${NUMF}`;
  for (const [v, col, name] of lv) {
    g.strokeStyle = col; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(0, Y(v)); g.lineTo(w - 84, Y(v)); g.stroke(); g.setLineDash([]);
    g.fillStyle = col; g.fillText(name, w - 80, Y(v) + 4);
  }
  g.beginPath(); futBuf.forEach(([t, v], i) => i ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v)));
  g.strokeStyle = C.ink; g.lineWidth = 1.6; g.stroke();
  const [tl, vl] = futBuf[futBuf.length - 1];
  g.fillStyle = C.ink; g.beginPath(); g.arc(X(tl), Y(vl), 3, 0, 7); g.fill();
  g.fillStyle = C.mist; g.fillText(fmt(hi, 0), w - 80, 12); g.fillText(fmt(lo, 0), w - 80, h - 16);
  const d = s.domino || {}, fb = s.fut_book || {}, lg = s.lag || {}, bk = s.bank || {};
  $("tracehint").textContent = `15-s move ${sgn(d.r15, 1)} pts, normal ${fmt(d.sigma15, 1)} · Bank Nifty z ${sgn(bk.z, 1)} · lag today ${lg.median === null || lg.median === undefined ? "—" : fmt(lg.median, 1) + " s (" + lg.n + ")"}`;
  $("futbook").innerHTML = `Futures book: <b>${fmt(fb.sbo, 0)}</b> buy orders v <b>${fmt(fb.sso, 0)}</b> sell, order imbalance <b class="${tone(fb.imb_o)}">${sgn(fb.imb_o, 2)}</b>, whole book <b class="${tone(fb.imb_t)}">${sgn(fb.imb_t, 2)}</b> (${sgn(fb.imb_t_chg, 2)} in 30 s). Bid orders <span class="c-${fb.bid_ord_cls}">${SH[fb.bid_ord_cls] || "—"}</span>, ask orders <span class="c-${fb.ask_ord_cls}">${SH[fb.ask_ord_cls] || "—"}</span>. Book→price <b>${sgn(fb.lead, 2)}</b>.`;
}

function drawOI(s) {
  const cv = $("oi"); const rows = (s.chain || []).slice().sort((a, b) => b[0] - a[0]);
  cv.height = Math.max(220, rows.length * 22 + 20);
  const [g, w, h] = fit(cv); g.clearRect(0, 0, w, h);
  const pr = s.pressure || {};
  $("pcr").textContent = nil(pr.pcr) ? "" : `put/call ${fmt(pr.pcr, 2)}, chain ${fmt(pr.chain_age, 0)} s old`;
  if (!rows.length) { g.fillStyle = C.mist; g.font = `14px ${NUMF}`; g.fillText("Waiting for the option chain", 10, 24); return; }
  const mid = w / 2, half = mid - 34, mx = Math.max(...rows.map(r => Math.max(r[1], r[2])), 1);
  const rowH = (h - 20) / rows.length, top = 10;
  const walls = new Set([...(pr.walls_up || []), ...(pr.walls_dn || [])].map(x => x[0]));
  const Y = (k) => { // strike -> y by interpolation over the rows (rows are descending)
    if (k >= rows[0][0]) return top + rowH / 2; if (k <= rows[rows.length - 1][0]) return top + rowH * (rows.length - .5);
    for (let i = 0; i < rows.length - 1; i++) if (k <= rows[i][0] && k >= rows[i + 1][0]) return top + rowH * (i + .5 + (rows[i][0] - k) / (rows[i][0] - rows[i + 1][0]));
    return top; };
  g.font = `12px ${NUMF}`; g.textAlign = "center";
  rows.forEach(([k, ce, pe, cec, pec], i) => {
    const y = top + i * rowH, bh = Math.max(4, rowH - 7), isW = walls.has(k);
    g.fillStyle = alpha(C.up, isW ? .95 : .45); const pw = pe / mx * half; g.fillRect(mid - 30 - pw, y + 3, pw, bh);
    g.fillStyle = alpha(C.down, isW ? .95 : .45); const cw = ce / mx * half; g.fillRect(mid + 30, y + 3, cw, bh);
    g.fillStyle = C.ink; if (pec) { g.fillRect(mid - 30 - Math.abs(pec) / mx * half, y + rowH - 4, Math.abs(pec) / mx * half, 2); }
    if (cec) { g.fillRect(mid + 30, y + rowH - 4, Math.abs(cec) / mx * half, 2); }
    g.fillStyle = isW ? C.ink : C.mist; g.fillText(k, mid, y + rowH / 2 + 4);
  });
  const spot = s.spot || s.fut;
  if (!nil(spot)) {
    const y = Y(spot); g.strokeStyle = C.beacon; g.lineWidth = 1.5; g.beginPath(); g.moveTo(4, y); g.lineTo(w - 4, y); g.stroke();
    g.fillStyle = C.beacon; g.textAlign = "left"; g.fillText(`spot ${fmt(spot, 1)}`, 6, y - 4);
  }
  const gx = s.gex || {};
  if (gx.ok) {                                   // dealer-gamma markers: flip (dashed) and max pain (dotted)
    const mark = (k, dash, label, al) => { if (nil(k) || !rows.length) return; const y = Y(k);
      g.save(); g.setLineDash(dash); g.strokeStyle = C.ink; g.lineWidth = 1; g.beginPath(); g.moveTo(4, y); g.lineTo(w - 4, y); g.stroke(); g.restore();
      g.fillStyle = C.ink; g.textAlign = al; g.fillText(label, al === "right" ? w - 6 : 6, y - 3); };
    mark(gx.flip, [6, 4], `gamma flip ${fmt(gx.flip, 0)}`, "right"); mark(gx.max_pain, [2, 3], `max pain ${fmt(gx.max_pain, 0)}`, "left");
  }
  g.textAlign = "left"; g.fillStyle = C.mist; g.fillText("put OI: support", 4, h - 2); g.textAlign = "right"; g.fillText("call OI: resistance", w - 4, h - 2);
  const gw = { DAMPEN: "dealer hedging leans against moves, so spikes tend to fade", AMPLIFY: "dealer hedging leans with moves, so spikes can run", MIXED: "dealer hedging is balanced" };
  $("gex").innerHTML = gx.ok
    ? `Dealer gamma: <b class="${gx.regime === "AMPLIFY" ? "up" : gx.regime === "DAMPEN" ? "down" : ""}">${gx.regime.toLowerCase()}</b> (balance ${sgn(gx.balance, 2)}), ${gw[gx.regime]}. Flip ${nil(gx.flip) ? "none within 3%" : fmt(gx.flip, 0)}, call gamma wall ${nil(gx.call_wall) ? "—" : fmt(gx.call_wall, 0)}, put gamma wall ${nil(gx.put_wall) ? "—" : fmt(gx.put_wall, 0)}, max pain ${fmt(gx.max_pain, 0)}. <span class="c-0">Assumes dealers are long calls and short puts; shown as evidence only.</span>`
    : `Dealer gamma: ${gx.why || "warming"}.`;
  const f = s.force || {}, words = { "VACUUM": "sellers vanished, it should run", "BREAK-IMMINENT": "about to break", "WEAKENING": "weakening", "HOLD-STRONG": "holding firm", "TESTING": "being tested", "IDLE": "no level within 5 points", "BROKE": "broke", "REJECTED": "rejected the attack", "LEFT": "price left the level" };
  $("force").innerHTML = f.name ? `Futures at <b>${f.name}</b> (${fmt(f.level, 0)}): <b class="${["VACUUM", "BREAK-IMMINENT", "BROKE"].includes(f.verdict) ? "up" : f.verdict === "HOLD-STRONG" ? "down" : ""}">${words[f.verdict] || f.verdict}</b>. Refill ${fmt(f.rho, 2)}, pulled ${fmt(f.pi, 2)}.`
    : `Level check: ${words[f.verdict] || f.verdict || "—"}.${f.last ? ` Last: ${f.last.name} ${words[f.last.outcome] || f.last.outcome} after ${fmt(f.last.dur, 0)} s.` : ""} Room up ${pr.dest_up ? fmt(pr.dest_up.room, 0) + " pts" : "open"}, down ${pr.dest_dn ? fmt(pr.dest_dn.room, 0) + " pts" : "open"}.`;
}

// ── the Triangle ───────────────────────────────────────────────────────────
const anim = { push: 0, crowd: 0, fresh: .35, rot: 0, glow: 0, t: performance.now(), beads: {} };

function frame(tms) {
  const dt = Math.min(.1, (tms - anim.t) / 1000); anim.t = tms;
  if (S) drawTriangle(dt, tms);
  requestAnimationFrame(frame);
}

function drawTriangle(dt, tms) {
  const cv = $("tri"); const [g, w, h] = fit(cv); g.clearRect(0, 0, w, h);
  const c = corners(S), k = 1 - Math.exp(-dt * 6);
  for (const n of ["push", "crowd", "fresh"]) anim[n] += (clamp(c[n], 0, 1.35) - anim[n]) * k;
  const near = clamp(Math.min(anim.push, anim.crowd, c.ep ? anim.fresh : 0), 0, 1.2);
  anim.glow += ((c.closed || S.pos ? 1 : near * near) - anim.glow) * k;
  anim.rot += dt * (0.04 + 0.9 * near * near);
  const col = c.dir > 0 ? C.up : C.down;
  const cx = w / 2, cy = h * .52, R = Math.min(w, h) * .21;
  const ang = [-Math.PI / 2, Math.PI * 5 / 6, Math.PI / 6];
  const P = (a, r) => [cx + Math.cos(a) * r, cy + Math.sin(a) * r];

  // the current: spiral arms that turn faster as the corners converge
  g.lineWidth = 1;
  for (let arm = 0; arm < 5; arm++) {
    g.beginPath();
    for (let i = 0; i <= 70; i++) {
      const r = R * 2.3 * Math.exp(-i * .035), a = anim.rot + arm * Math.PI * 2 / 5 + i * .085;
      const [x, y] = P(a, r); i ? g.lineTo(x, y) : g.moveTo(x, y);
    }
    g.strokeStyle = alpha(anim.glow > .6 ? C.beacon : C.refill, .05 + .1 * near); g.stroke();
  }
  // sonar rings
  for (let i = 1; i <= 3; i++) { g.beginPath(); g.arc(cx, cy, R * (.55 * i), 0, 7); g.strokeStyle = alpha(C.line, .5); g.stroke(); }

  // the threshold triangle (dashed) and the market's triangle (filled)
  g.setLineDash([6, 6]); g.beginPath(); ang.forEach((a, i) => { const [x, y] = P(a, R); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath();
  g.strokeStyle = alpha(C.ink, .45); g.lineWidth = 1.2; g.stroke(); g.setLineDash([]);
  const fr = [anim.push, anim.crowd, anim.fresh];
  g.beginPath(); ang.forEach((a, i) => { const [x, y] = P(a, R * Math.max(.04, fr[i])); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath();
  const fillCol = anim.glow > .85 ? C.beacon : col;
  g.fillStyle = alpha(fillCol, .14 + .22 * near); g.fill(); g.strokeStyle = alpha(fillCol, .9); g.lineWidth = 2; g.stroke();

  // the eye
  const er = R * (.12 + .32 * anim.glow);
  const grd = g.createRadialGradient(cx, cy, 0, cx, cy, er * 2.2);
  grd.addColorStop(0, alpha(C.beacon, .2 + .75 * anim.glow)); grd.addColorStop(.45, alpha(C.beacon, .12 * anim.glow + .03)); grd.addColorStop(1, alpha(C.beacon, 0));
  g.fillStyle = grd; g.beginPath(); g.arc(cx, cy, er * 2.2, 0, 7); g.fill();

  // one orchestrated moment: the entry shock-wave
  const since = (tms - flashAt) / 1000;
  if (since < 1.6) { g.beginPath(); g.arc(cx, cy, R * (.3 + since * 1.4), 0, 7); g.strokeStyle = alpha(C.beacon, .8 * (1 - since / 1.6)); g.lineWidth = 3; g.stroke(); }

  // corner labels
  const d0 = S.domino || {}, p = S.params || { m_star: 2, s_star: .5 };
  const lab = [
    ["Push", `futures ${sgn((d0.z || 0) * c.dir, 1)} of ${p.m_star}`],
    ["Together", `${pct(c.dir > 0 ? d0.S_up : d0.S_dn)} of ${Math.round(p.s_star * 100)}% weight`],
    ["Fresh", c.ep ? (nil(S.late) ? "—" : S.late < 1 ? `${Math.round((1 - S.late) * 100)}% of room left` : "too late") : "no move yet"],
  ];
  g.textAlign = "center";
  ang.forEach((a, i) => {
    const [x, y] = P(a, R + 30), ok = fr[i] >= 1 && (i < 2 || c.ep);
    g.font = `700 ${Math.max(14, R * .085)}px ${NUMF}`; g.fillStyle = ok ? C.beacon : C.ink; g.fillText(lab[i][0], x, y + (i === 0 ? -10 : 6));
    g.font = `500 ${Math.max(12, R * .06)}px ${NUMF}`; g.fillStyle = ok ? C.beacon : C.mist; g.fillText(lab[i][1], x, y + (i === 0 ? 8 : 24));
  });

  // the heavyweights orbit and are pulled in when they join the move
  const tiles = (S.tiles || []).slice().sort((a, b) => b.w - a.w), n = tiles.length;
  const first = S.episode && S.episode.first;
  tiles.forEach((t, j) => {
    const pull = clamp(((t.z || 0) * c.dir) / 2, 0, 1);
    const b = anim.beads[t.sym] || (anim.beads[t.sym] = { pull: 0 });
    b.pull += (pull - b.pull) * k;
    const a = anim.rot * .35 + j * Math.PI * 2 / n - Math.PI / 2;
    const [x, y] = P(a, R * (2.02 - .52 * b.pull));
    const rad = Math.max(3, Math.sqrt(t.w) * R * .032);
    const mv = t.m || 0, bc = mv > 0 ? C.up : mv < 0 ? C.down : C.mist;
    const strength = clamp(Math.abs(t.z || 0) / 2, .2, 1);
    if (b.pull > .3) { g.beginPath(); g.moveTo(x, y); const [x2, y2] = P(a, R * (2.02 - .52 * b.pull) + rad * 3); g.lineTo(x2, y2); g.strokeStyle = alpha(bc, .4 * b.pull); g.lineWidth = rad * .9; g.stroke(); }
    g.beginPath(); g.arc(x, y, rad, 0, 7); g.fillStyle = alpha(bc, .25 + .7 * strength); g.fill();
    if (t.sym === first) { g.strokeStyle = C.beacon; g.lineWidth = 2; g.stroke(); }
    if (t.w >= 3.3 || t.sym === first) { g.font = `600 ${Math.max(11, R * .05)}px ${NUMF}`; g.fillStyle = t.sym === first ? C.beacon : C.ink; g.fillText(t.sym, x, y - rad - 5); }
  });
  g.textAlign = "left";
}

// ── straddle watch ─────────────────────────────────────────────────────────
// A FIXED strike's CE+PE (the live ATM re-centres and makes the usual straddle chart jump).
// The chart: the straddle (ink), what theta alone would have done to it since the anchor
// (dashed), its VWAP, every spike (gold) and every ATM roll (blue). The leg that carries a
// spike — rising delta, price moving faster than theta — is the gamma leg.
let swSig = "";
function renderStraddle(s, now) {
  const w = s.straddle_watch;
  const hint = $("swhint"), stateEl = $("swstate"), legsEl = $("swlegs"), tb = $("swt").querySelector("tbody");
  if (!w || nil(w.K)) {
    hint.textContent = ""; stateEl.textContent = "Waiting for the ATM straddle"; legsEl.innerHTML = ""; tb.innerHTML = "";
    drawStraddle(null); return;
  }
  hint.innerHTML = `strike <b>${w.K}</b> since ${w.since || "—"}${s.atm !== w.K ? ` · live ATM ${s.atm}` : ""} · straddle <b>${fmt(w.px, 1)}</b> from ${fmt(w.open_px, 1)}${nil(w.vwap) ? "" : `, VWAP ${fmt(w.vwap, 1)}`}`;
  const L = w.legs || {}, sp = w.spike;
  legsEl.innerHTML = ["CE", "PE"].map(rr => {
    const l = L[rr] || {};
    const dd = l.ddelta, rising = !nil(dd) && dd >= 0.03;
    return `<div class="sw-leg ${rr.toLowerCase()}${w.leg === rr ? " gamma" : ""}">
      <div class="h"><b>${w.K} ${rr}</b><span class="px ${tone(l.chg5)}">${fmt(l.px, 2)}</span></div>
      <span>5 min <b class="${tone(l.chg5)}">${sgn(l.chg5, 1)}</b></span><span>1 min <b class="${tone(l.chg1)}">${sgn(l.chg1, 2)}</b>${nil(l.acc) ? "" : ` <small class="${tone(l.acc)}">${l.acc > 0 ? "faster" : l.acc < 0 ? "slower" : ""}</small>`}</span>
      <span>delta <b>${fmt(l.delta5, 2)}</b> → <b class="${rising ? "beacon" : ""}">${fmt(l.delta, 2)}</b></span><span>gamma <b>${nil(l.gamma) ? "—" : (l.gamma * 1000).toFixed(2) + "‰"}</b></span>
      <span>theta <b>${nil(l.theta) ? "—" : fmt(l.theta, 3)}</b>/min</span><span>${nil(l.theta) || nil(l.chg5) ? "" : `vs <b class="${tone(l.chg5 - l.theta * 5)}">${sgn(l.chg5 - l.theta * 5, 1)}</b> over theta`}</span>
    </div>`;
  }).join("");
  let txt, cls = "sw-state";
  if (sp) {
    cls += " spike";
    txt = `<b>SPIKE</b> on the ${sp.leg} leg, ${fmt(sp.age, 0)} s in: straddle ran <b>${sgn(sp.peak_excess, 1)}</b> over theta, the ${sp.leg} is <b>${sgn(sp.leg_move, 1)}</b> since it started (delta ${fmt(sp.delta0, 2)} → ${fmt(sp.delta_now, 2)}), futures <b>${sgn(sp.fut_move, 1)}</b> its way.`;
  } else if (w.state === "VOL-SPIKE") {
    txt = `Premium rising on <b>both</b> legs (${sgn(w.excess, 1)} over theta in 5 min): IV, not direction — no leg favoured.`;
  } else if (w.state === "WARMING") {
    txt = `Warming up: five minutes of this strike's prices needed before a spike can be measured.`;
  } else {
    txt = `${w.state === "DECAYING" ? "Decaying as a straddle should" : "Flat"}: <b>${sgn(w.drift_min, 2)}</b>/min over 10 min vs theta <b>${sgn(w.theta_min, 2)}</b>; 5-min change ${sgn(w.chg5, 1)} (${sgn(w.excess, 1)} over theta, spike at +${fmt(w.thr, 1)}).`;
  }
  stateEl.className = cls; stateEl.innerHTML = txt;
  const rows = (w.spikes || []).map(x => `<tr><td>${x.t0}</td><td class="${x.leg === "CE" ? "up" : "down"}">${x.K} ${x.leg}</td><td class="r">+${fmt(x.peak_excess, 1)}</td><td class="r ${tone(x.leg_move)}">${sgn(x.leg_move, 1)}</td><td class="r ${tone(x.fut_move)}">${sgn(x.fut_move, 1)}</td><td>${x.ended ? `${x.ended} · ${x.end_why}` : "<b class=\"beacon\">live</b>"}</td></tr>`)
    .concat((w.shifts || []).slice().reverse().map(x => `<tr class="mist"><td>${x.t}</td><td colspan="5">ATM rolled ${x.from} → ${x.to}: straddle ${fmt(x.s_before, 1)} → ${fmt(x.s_after, 1)}</td></tr>`));
  const sig = rows.join("|");
  if (sig !== swSig) { swSig = sig; tb.innerHTML = rows.length ? rows.join("") : `<tr><td colspan="6" class="empty">No spike yet today. A spike is the straddle gaining more than theta should let it in 5 minutes.</td></tr>`; }
  drawStraddle(w, now);
}

function drawStraddle(w, now) {
  const cv = $("swline"); const [g, wd, h] = fit(cv); g.clearRect(0, 0, wd, h);
  const ser = (w && w.series) || [];
  if (ser.length < 2) { g.fillStyle = C.mist; g.font = `13px ${NUMF}`; g.fillText("Collecting the straddle's path", 10, 24); return; }
  const t1 = ser[ser.length - 1][0], span = Math.max(900, Math.min(7200, t1 - ser[0][0])), t0 = t1 - span;
  const pts = ser.filter(p => p[0] >= t0);
  const ys = [];
  for (const p of pts) { if (!nil(p[1])) ys.push(p[1]); if (!nil(p[4])) ys.push(p[4]); }
  if (w.vwap) ys.push(w.vwap);
  let lo = Math.min(...ys), hi = Math.max(...ys); const pad = Math.max(1, (hi - lo) * .15); lo -= pad; hi += pad;
  const RW = 56, X = (t) => (t - t0) / span * (wd - RW), Y = (v) => h - 16 - (v - lo) / (hi - lo) * (h - 28);
  g.font = `12px ${NUMF}`;
  // spike windows (engine clock, seconds — same clock as the series)
  for (const x of w.spikes || []) {
    if (nil(x.t_s)) continue;
    const xa = X(x.t_s), xb = X(nil(x.end_s) ? t1 : x.end_s);
    if (xb > 0 && xa < wd - RW) { g.fillStyle = alpha(C.beacon, .10); g.fillRect(Math.max(0, xa), 0, Math.min(wd - RW, xb) - Math.max(0, xa), h - 14); }
  }
  // ATM rolls
  for (const x of w.shifts || []) {
    if (nil(x.t_s) || x.t_s < t0) continue;
    g.strokeStyle = alpha(C.refill, .7); g.setLineDash([3, 4]); g.beginPath(); g.moveTo(X(x.t_s), 0); g.lineTo(X(x.t_s), h - 14); g.stroke(); g.setLineDash([]);
    g.fillStyle = C.refill; g.fillText(`${x.from}→${x.to}`, X(x.t_s) + 4, 12);
  }
  // theta-only path
  g.strokeStyle = alpha(C.mist, .8); g.setLineDash([5, 5]); g.lineWidth = 1; g.beginPath();
  let started = false;
  for (const p of pts) { if (nil(p[4])) continue; started ? g.lineTo(X(p[0]), Y(p[4])) : g.moveTo(X(p[0]), Y(p[4])); started = true; }
  g.stroke(); g.setLineDash([]);
  // VWAP
  if (w.vwap) { g.strokeStyle = alpha(C.refill, .55); g.beginPath(); g.moveTo(0, Y(w.vwap)); g.lineTo(wd - RW, Y(w.vwap)); g.stroke(); g.fillStyle = C.refill; g.fillText("vwap " + fmt(w.vwap, 1), wd - RW + 4, Y(w.vwap) + 4); }
  // the straddle
  g.strokeStyle = w.spike ? C.beacon : C.ink; g.lineWidth = 1.8; g.beginPath(); started = false;
  for (const p of pts) { if (nil(p[1])) continue; started ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])); started = true; }
  g.stroke();
  const lp = pts[pts.length - 1];
  const taken = [];                                   // label rows already used on the right margin
  const place = (y) => { let yy = Math.min(h - 18, Math.max(14, y)); for (let i = 0; i < 4; i++) { if (taken.every(t => Math.abs(t - yy) >= 13)) break; yy += 13; } taken.push(yy); return yy; };
  if (w.vwap) taken.push(Y(w.vwap) + 4);
  if (!nil(lp[1])) { g.fillStyle = w.spike ? C.beacon : C.ink; g.beginPath(); g.arc(X(lp[0]), Y(lp[1]), 3, 0, 7); g.fill(); g.fillText(fmt(lp[1], 1), wd - RW + 4, place(Y(lp[1]) + 4)); }
  if (!nil(lp[4])) { g.fillStyle = C.mist; g.fillText("theta " + fmt(lp[4], 1), wd - RW + 4, place(Y(lp[4]) + 4)); }
  g.fillStyle = C.mist; g.fillText(`${Math.round(span / 60)} min`, 4, h - 3);
}

// ── lower panels ───────────────────────────────────────────────────────────
function renderHeavy(s) {
  const d = (s.episode && s.episode.dir) || (s.domino && s.domino.dir) || 1, first = s.episode && s.episode.first;
  const tiles = (s.tiles || []).slice().sort((a, b) => b.w - a.w);
  const fo = {}; for (const e of s.eq || []) fo[e.sym] = nil(e.fut_oi_chg) ? "—" : sgn(e.fut_oi_chg, 0);
  const mx = Math.max(3, ...tiles.map(t => Math.abs(t.m || 0)));
  $("hw").innerHTML = tiles.map(t => {
    const m = t.m || 0, wd = Math.abs(m) / mx * 50, join = (t.z || 0) * d >= 1;
    return `<div class="hrow"><span class="s ${t.sym === first ? "first" : ""}" title="z ${fmt(t.z, 1)}, volume ${fmt(t.act, 1)}× its normal, futures OI ${fo[t.sym] ?? "—"} in ~5 min">${t.sym}</span><span class="w">${fmt(t.w, 1)}%</span>
      <span class="track"><i class="${join ? "join" : ""}" style="left:${m >= 0 ? 50 : 50 - wd}%;width:${wd}%;background:${m >= 0 ? C.up : C.down};color:${m >= 0 ? C.up : C.down}"></i></span>
      <span class="v ${tone(m)}">${sgn(m, 2)}</span></div>`;
  }).join("");
  const dm = s.domino || {};
  $("hwhint").textContent = nil(dm.Mb) ? "in Nifty points" : `basket implies ${sgn(dm.Mb, 1)} pts, futures moved ${sgn(dm.Mf, 1)}, lag ${sgn(dm.gap, 1)}`;
  $("hw2").innerHTML = (s.eq || []).filter(e => !e.wn).map(e => `<span>${e.sym} <b class="${tone(e.chg)}">${sgn(e.chg)}%</b></span>`).join("") || "";
}

function renderTrades(s) {
  const b = s.book || {};
  $("tstats").textContent = b.trades ? `${b.trades} trades, ${b.wins} won, ${sgn(b.pnl_pts)} points` : "";
  const why = (r) => ({ TRAIL: "Trailing stop", STOP: "Stop loss" }[r] || r.replace("THESIS-VOID (synchrony flipped)", "Heavyweights turned against it").replace("TIME (15:25 flatten)", "15:25 close").replace("TIME (0DTE 15:00)", "Expiry-day 15:00 close"));
  $("tt").querySelector("tbody").innerHTML = (s.trades || []).length ? s.trades.map(t =>
    `<tr><td>${t.time_in}</td><td>${t.time_out}</td><td>${t.strike} ${t.rr}</td><td class="r">${t.lots}</td><td class="r">${fmt(t.entry)}</td><td class="r">${fmt(t.exit)}</td>
     <td class="r ${tone(t.pnl_pts)}">${sgn(t.pnl_pts)}</td><td class="r ${tone(t.pnl_rs)}">${inr(t.pnl_rs)}</td><td>${why(t.reason)}</td><td class="r">${inr(t.capital_after)}</td></tr>`).join("")
    : `<tr><td colspan="10" class="empty">No trades yet today. Entries appear here the moment the triangle closes.</td></tr>`;
}

function renderBooks(s) {
  const vs = s.variants || [], mx = Math.max(1, ...vs.map(v => Math.abs(v.pnl_pts)));
  const name = (n) => n === "RAW" ? "No rules (RAW)" : n === "straddle_spike" ? "straddle spike leg" : n.startsWith("gap") ? n.replace(/^gap([\d.]+)_s([\d.]+)$/, (_, g, x) => `basket gap ${g}, ${Math.round(x * 100)}%`)
    : n.endsWith("_bookexit") ? "push 2.0, 50% + book exit" : n.replace(/^m([\d.]+)_s([\d.]+)$/, (_, m, x) => `push ${m}, ${Math.round(x * 100)}%`);
  $("books").innerHTML = vs.map(v => {
    const wd = Math.abs(v.pnl_pts) / mx * 50;
    return `<div class="book ${v.name === s.champion ? "champ" : ""}"><span class="n">${name(v.name)}${v.open ? " ●" : ""}</span>
      <span class="track"><i style="left:${v.pnl_pts >= 0 ? 50 : 50 - wd}%;width:${wd}%;background:${v.pnl_pts >= 0 ? C.up : C.down}"></i></span>
      <span class="v ${tone(v.pnl_rs)}">${inr(v.pnl_rs)}</span></div>`;
  }).join("");
  const l = s.learning || {}, sb = l.scoreboard || {};
  $("lstat").textContent = { COLLECTING: "collecting evidence", GO: "edge looks real", KILL: "lead book retired", "NO-EDGE": "no edge found" }[l.status] || "collecting evidence";
  $("sprt").textContent = `Lead book since ${l.champion_since || "—"}: ${sb.n ?? 0} trades, ${sgn(sb.sum ?? 0, 1)} points. Proven at ${fmt(sb.go_line, 1)}, retired at ${fmt(sb.kill_line, 1)}. Changes happen only after the close.`;
}

function renderTape(s) {
  const ev = s.events || [];
  const names = { ENTRY: "Bought", EXIT: "Sold", "RAW-ENTRY": "RAW bought", "RAW-EXIT": "RAW sold", SYSTEM: "System", LEARN: "Learned", ARMED: "Armed",
                  SPIKE: "Straddle spike", SHIFT: "ATM rolled" };
  $("ev").innerHTML = ev.map(e => `<li class="${e.k}"><span class="t">${e.t}</span><span class="k">${names[e.k] || e.k}</span><span>${e.x}</span></li>`).join("");
  const top = ev.find(e => e.k === "ENTRY" || e.k === "EXIT" || e.k === "ARMED" || e.k === "SPIKE");
  const key = top ? top.t + top.k + top.x : "";
  if (key && key !== lastEvKey) {
    if (lastEvKey) {
      if (top.k === "ENTRY") flashAt = performance.now();
      if (sound) beep(top.k === "ENTRY" ? 880 : (top.k === "ARMED" || top.k === "SPIKE") ? 660 : 440);
    }
    lastEvKey = key;
  }
}

function beep(freq) {
  try {
    actx = actx || new AudioContext();
    const o = actx.createOscillator(), g = actx.createGain();
    o.frequency.value = freq; o.connect(g); g.connect(actx.destination);
    g.gain.setValueAtTime(.15, actx.currentTime); g.gain.exponentialRampToValueAtTime(.001, actx.currentTime + .4);
    o.start(); o.stop(actx.currentTime + .42);
  } catch (e) { }
}

$("snd").onclick = () => {
  sound = !sound; const b = $("snd");
  b.setAttribute("aria-pressed", sound); b.textContent = sound ? "Sound on" : "Sound off";
  if (sound) beep(660);
};
window.addEventListener("resize", () => S && render(S));
loadInstruments().then(() => { connectTicks(); connectState(); requestAnimationFrame(frame); });
