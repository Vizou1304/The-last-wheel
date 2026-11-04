// Tableau de bord, chronique et lien avec la simulation. Fonctionne avec ou sans la 3D.
const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const POST_TAIL = "\n\nThe Last Wheel, a frozen city kept alive by @squeekchain's hamster.";

export const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

const WEATHER_TEXT = {
  clear: "The sky is clear.", wind: "A bitter wind is blowing.", snow: "Snow is falling.", blizzard: "A blizzard is raging.",
};

function tempColor(c) {
  const t = Math.min(Math.max((c + 40) / 40, 0), 1); // -40 °C givre -> 0 °C braise
  const from = [201, 214, 234], to = [255, 178, 120];
  return `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * t)).join(",")})`;
}

// ------------------------------------------ preuve sur la chaîne (Ethereum) ---
const TX_RE = /^0x[0-9a-fA-F]{64}$/;
const num = (n) => (n == null ? "unknown" : Number(n).toLocaleString("en"));
let chainSig = "";

function updateChain(chain) {
  const box = $("chain");
  if (!chain) { box.hidden = true; return; } // simulation : pas de données de chaîne, jamais de faux lots
  box.hidden = false;
  const sig = JSON.stringify(chain);
  if (sig === chainSig) return;
  chainSig = sig;
  const st = chain.settlements || {};
  const net = st.network === "sepolia" || !st.network ? "Sepolia testnet" : String(st.network);
  const short = net.replace(" testnet", "");
  $("chain-title").textContent = `On Ethereum · ${net}`;
  // « live » et « réglé » ne sont jamais fusionnés : le travail réglé est toujours en retard sur le live
  $("chain-totals").textContent = `Live, counted by the Wheel: ${num(chain.live_work)} work units. Settled on Ethereum: ${num(chain.settled_work)}. Settlement runs behind the live count.`;
  const list = $("chain-list");
  list.replaceChildren();
  const items = st.status === "ok" ? st.items || [] : [];
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "unknown";
    li.textContent = st.status === "ok" ? "No batch settled in the last 24 hours." : "Chain data is unavailable right now. Unknown is not zero.";
    list.append(li);
    return;
  }
  const base = String(chain.explorer_tx || "");
  for (const it of items) {
    const li = document.createElement("li");
    const what = document.createElement("span");
    const added = it.work == null ? "" : ` · +${num(it.work)} work units`; // montant inconnu : on n'écrit rien (inconnu n'est pas zéro)
    what.textContent = `Block ${num(it.block)}${added}${it.confirmation && it.confirmation !== "safe" ? " (confirming)" : ""}`;
    li.append(what);
    if (base.startsWith("https://") && TX_RE.test(it.tx)) { // le lien n'est construit que pour un hash bien formé
      const a = document.createElement("a");
      a.href = base + it.tx;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = `Verify on ${short} ↗`;
      li.append(a);
    }
    list.append(li);
  }
}

const LINK_TEXT = {
  lost: "Signal lost. The Wheel is out of sight.",
  fault: "The Wheel's counter is offline. Nobody knows how it turns.",
  unverified: "Waiting for a verified signal from the Wheel.",
};

function updateHud(s) {
  $("temp").firstChild.nodeValue = Math.round(s.temperature);
  $("temp").style.setProperty("--t-color", tempColor(s.temperature));
  const sky = WEATHER_TEXT[s.weather] || "";
  $("phase").textContent = s.frozen ? `Hibernation. The colony waits for the Wheel. ${sky}`
    : s.phase === "night" ? `Night ${s.nights}. The colony sleeps. ${sky}`
    : `Day. The furnace is burning. ${sky}`;
  $("hamster").classList.toggle("asleep", !s.hamster.active);
  const rpm = (s.hamster.rpm || 0) / 1000; // la petite roue tourne aussi à la vraie vitesse
  $("wheel-icon").style.animationDuration = s.hamster.active && rpm > 0 ? `${(60 / rpm).toFixed(3)}s` : "0s";
  // signal perdu ou panne du compteur : donnée inconnue, on ne dit jamais « il dort »
  const link = s.hamster.link || "live";
  // distance courue aujourd'hui (réelle, donnée par l'appareil) : seulement si elle est connue et positive
  const mm = s.hamster.distance_mm;
  const km = s.mode !== "sim" && link === "live" && mm > 0 ? ` · ${(mm / 1e6).toFixed(2)} km today` : "";
  $("ham-text").textContent = (s.mode === "sim" ? "Simulation · " : "") + (LINK_TEXT[link]
    || (s.hamster.active ? "is running. The Wheel is turning." : "is resting. The Wheel is still.")) + km;
  $("reserve").textContent = `${s.reserve.toLocaleString("en")} / ${s.reserve_cap.toLocaleString("en")}`;
  $("reserve-bar").style.width = `${(100 * s.reserve) / Math.max(s.reserve_cap, 1)}%`;
  $("people").textContent = `${s.population} / ${s.capacity}`;
  $("camp").textContent = s.waiting ? `${s.waiting} in camp` : "";
  $("frost-val").textContent = `${Math.round(s.frost * 100)}%`;
  $("frost-bar").style.width = `${s.frost * 100}%`;
  $("g-build").hidden = !s.project;
  if (s.project) {
    $("build-name").textContent = cap(s.project.name);
    $("build-pct").textContent = `${s.project.pct}%`;
    $("build-bar").style.width = `${s.project.pct}%`;
  }
}

// ------------------------------------------------------------ chronique ---
let lastT = 0;
function addEntries(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  const list = $("entries");
  list.querySelector(".empty")?.remove();
  const first = lastT === 0;
  for (const e of rows) {
    lastT = Math.max(lastT, e.t);
    const el = document.createElement("article");
    el.className = first ? "entry" : "entry new";
    const d = new Date(e.t * 1000);
    const time = document.createElement("time");
    time.dateTime = d.toISOString();
    time.textContent = d.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
    const p = document.createElement("p");
    p.textContent = e.text;
    const btn = document.createElement("button");
    btn.className = "copy";
    btn.type = "button";
    btn.textContent = "Copy for X";
    btn.addEventListener("click", () => copy(e.text + POST_TAIL, btn, "Copy for X"));
    el.append(time, p, btn);
    list.prepend(el);
  }
  while (list.children.length > 120) list.lastChild.remove();
  setLastEntry(rows[rows.length - 1], !first);
}

async function copy(text, btn, label) {
  try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; }
  catch { btn.textContent = "Copy failed"; }
  setTimeout(() => { btn.textContent = label; }, 1800);
}

// ----------------------------------------------- dernière ligne de log ---
function setLastEntry(entry, animate) {
  const p = $("last-text");
  p.textContent = entry.text;
  if (animate) {
    p.classList.remove("new");
    void p.offsetWidth; // force reflow pour relancer l'animation
    p.classList.add("new");
  }
}

// -------------------------------------------------------- tiroir journal ---
function openLog() {
  const drawer = $("drawer"), overlay = $("drawer-overlay");
  drawer.removeAttribute("inert");
  drawer.setAttribute("aria-hidden", "false");
  overlay.setAttribute("aria-hidden", "false");
  drawer.classList.add("is-open");
  overlay.classList.add("is-open");
  $("close-log").focus();
}

function closeLog() {
  const drawer = $("drawer"), overlay = $("drawer-overlay");
  drawer.classList.remove("is-open");
  overlay.classList.remove("is-open");
  drawer.setAttribute("aria-hidden", "true");
  overlay.setAttribute("aria-hidden", "true");
  // remet inert après la transition pour sortir les éléments du tab order
  setTimeout(() => { if (!drawer.classList.contains("is-open")) drawer.setAttribute("inert", ""); }, 300);
  $("open-log").focus();
}

// ------------------------------------------------------- image de repli ---
export function fallback(msg) {
  $("loading").hidden = true;
  $("still-msg").textContent = msg;
  $("still").hidden = false;
}

// -------------------------------------------------------------- réseau ---
// onState(state) est appelé à chaque nouvel état, onFirstState(state) une seule fois.
export function startHud({ onState = () => {}, onFirstState = () => {} } = {}) {
  $("share").addEventListener("click", () => copy(location.href, $("share"), "Copy link"));
  $("open-log").addEventListener("click", openLog);
  $("close-log").addEventListener("click", closeLog);
  $("drawer-overlay").addEventListener("click", closeLog);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("drawer").classList.contains("is-open")) closeLog();
    // piège de focus dans le tiroir
    if (e.key === "Tab" && $("drawer").classList.contains("is-open")) {
      const focusable = [...$("drawer").querySelectorAll("button, [href], input, [tabindex]:not([tabindex='-1'])")];
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  let first = true;
  async function poll() {
    try {
      const [st, ch] = await Promise.all([
        fetch("api/state", { cache: "no-store" }).then((r) => r.json()),
        fetch(`api/chronicle?since=${lastT}`, { cache: "no-store" }).then((r) => r.json()),
      ]);
      if (st && st.catalog) {
        if (first) { first = false; onFirstState(st); }
        updateHud(st);
        updateChain(st.chain);
        onState(st);
      }
      addEntries(ch);
      $("offline").hidden = true;
    } catch {
      $("offline").hidden = false;
    }
    setTimeout(poll, POLL_MS);
  }
  poll();
}
