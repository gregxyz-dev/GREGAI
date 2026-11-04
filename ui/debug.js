// debug.js: skrypt strony /debug (wydzielony z debug.html, żeby polityka CSP
// serwera mogła zabronić skryptów wpisanych w HTML).

const STAGE_LABELS = {
  doprecyzowanie_rozwiazane: "Doprecyzowanie",
  dwuznacznosc: "Dopytanie",
  szybka_sciezka: "Szybka ścieżka",
  wyuczona_sciezka: "Wyuczona ścieżka",
  ollama_niedostepna: "Model niedostępny",
  ollama_blad: "Błąd modelu",
  ollama_narzedzie: "Model: narzędzie",
  ollama_rozmowa: "Model: rozmowa",
  korekta_wyuczonego: "Korekta (zapomniane)",
  serce_kontrola_ollama: "Serce: model",
  serce_blad: "Serce: błąd",
  zadanie: "Zadanie",
  zadanie_potwierdzone: "Zadanie: zgoda",
  zadanie_anulowane: "Zadanie: anulowane",
  // 1.18.0: nazwy etapów koryta (agent/koryto.py) zamiast starych
  // "chmura"/"żongler" - klucze zostają, bo tak zapisuje je agent/router.py.
  chmura_rozmowa: "Koryto: Claude",
  uczen_rozmowa: "Koryto lokalnie: uczeń",
  zongler_rozmowa: "Koryto: darmowa pula",
  zongler_senior_juniorzy: "Koryto: senior+juniorzy",
  teraz_blad: "Teraz: błąd bloku",
  namysl: "Namysł (6 faz)",
  namysl_blad: "Namysł: błąd",
  pamiec_rozmowy: "Pamięć rozmowy: streszczenie",
  pamiec_rozmowy_blad: "Pamięć rozmowy: błąd",
  komenda: "Komenda /",
  lekcja_zapisana: "Lekcja: zapisana",
  // 1.32.2 (audyt tura 7): etapy, które dotąd pokazywały się surową nazwą.
  zapis_wezla: "Zapis do grafu",
  zapis_wezla_brak: "Zapis do grafu: brak treści",
  rozmowa_usunieta: "Rozmowa usunięta",
  zadania_stale_blad: "Zadania stałe: błąd",
  zadania_stale_blad_petli: "Zadania stałe: błąd pętli",
  zadanie_stale_alert: "Zadanie stałe: alert",
  zadanie_stale_bez_oceny: "Zadanie stałe: bez oceny",
  lekcja_odrzucona: "Lekcja: odrzucona",
};

// Polska liczba mnoga - kopia pluralPl z app.js (1.19.0): samodzielne /debug
// ładuje tylko ten plik.
function pluralPlD(n, one, few, many) {
  const a = Math.abs(Number(n) || 0);
  if (a === 1) return one;
  const d = a % 10, h = a % 100;
  return d >= 2 && d <= 4 && !(h >= 12 && h <= 14) ? few : many;
}

// Etapy, na których odpowiedział etap SIECIOWY koryta (Claude, darmowa pula) -
// do licznika "przez sieć" (1.19.0: dawne "przez Ollamę" liczyło tylko lokalne
// etapy, choć domyślnie odpowiada sieć).
const NETWORK_STAGES = new Set(["chmura_rozmowa", "zongler_rozmowa", "zongler_senior_juniorzy"]);
const LOCAL_STAGES = new Set(["ollama_narzedzie", "ollama_rozmowa", "uczen_rozmowa"]);
// Etapy z kolorowym tłem odznaki w debug.css - tylko one dostają ciemny tekst
// (klasa .tone). Nieznany albo neutralny etap: jasny tekst na neutralnym tle.
const STAGE_TONED = new Set(["szybka_sciezka", "wyuczona_sciezka", "doprecyzowanie_rozwiazane", "dwuznacznosc",
  "ollama_narzedzie", "ollama_niedostepna", "ollama_blad", "korekta_wyuczonego", "serce_kontrola_ollama", "serce_blad",
  "zadanie", "zadanie_potwierdzone", "chmura_rozmowa", "uczen_rozmowa", "zongler_rozmowa", "zongler_senior_juniorzy",
  "namysl", "namysl_blad", "teraz_blad", "pamiec_rozmowy_blad", "zadania_stale_blad", "zadania_stale_blad_petli",
  "zadanie_stale_alert"]);
let logEntries = [];
let logFilter = "";

// Token dostępu (tylko przy połączeniu spoza localhost, jak w app.js).
//
// 1.32.18 (audyt tura 20/20): /debug jest zapasową stroną - ma działać
// SAMODZIELNIE, nawet gdy app.js (jedyne miejsce, które dotąd pytało o token)
// się nie wczytał. Z telefonu przez LAN, w nowej karcie/przeglądarce bez
// zapisanego tokenu, każda sekcja milczała "brak połączenia z GREGAI" w
// nieskończoność (co 15 s) i nigdzie na stronie nie dało się tokenu wpisać -
// dokładnie wtedy, gdy Grzegorz najbardziej potrzebuje tej strony (appka się
// posypała). Teraz debug.js ma WŁASNE ensureTokenD (kopia ensureToken z
// app.js) i apiFetch prosi o token przy pierwszym "Brak autoryzacji" (403),
// tak jak gregaiFetch w app.js.
let tokenPromptDeclinedD = false;

function ensureTokenD() {
  const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if (isLocal) return;
  let have = "";
  try { have = localStorage.getItem("gregai_token") || ""; } catch (e) {}
  if (have || tokenPromptDeclinedD) return;
  const token = prompt("To urządzenie łączy się z GREGAI przez sieć, podaj token dostępu (ten sam co GREGAI_TOKEN w .env na serwerze):");
  if (token) {
    try { localStorage.setItem("gregai_token", token.trim()); } catch (e) {}
  } else {
    tokenPromptDeclinedD = true;
  }
}

async function apiFetch(url, options = {}, retried = false) {
  const headers = Object.assign({}, options.headers || {});
  let stored = "";
  try {
    stored = localStorage.getItem("gregai_token") || "";
  } catch (e) {}
  if (stored) headers["X-Gregai-Token"] = stored;
  const res = await fetch(url, Object.assign({}, options, { headers }));
  if (res.status === 403 && !retried) {
    try {
      const body = await res.clone().json();
      if (body && body.error === "Brak autoryzacji") {
        try { localStorage.removeItem("gregai_token"); } catch (e) {}
        ensureTokenD();
        let haveNow = "";
        try { haveNow = localStorage.getItem("gregai_token") || ""; } catch (e) {}
        if (haveNow) return apiFetch(url, options, true);
      }
    } catch (e) {}
  }
  return res;
}

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("pl-PL", { hour12: false });
  } catch (e) {
    return iso || "";
  }
}

function fmtMs(ms) {
  if (ms == null) return "";
  if (ms >= 1000) return (ms / 1000).toFixed(1) + " s";
  return Math.round(ms) + " ms";
}

// Bezpiecznik żonglera (1.10.0, agent/juggler.py breaker_state): który dostawca
// odpoczywa po awarii (cooldown) albo jest wyłączony do restartu (401/403).
// Zdrowi dostawcy nie są wymieniani - pusty napis znaczy "wszyscy w grze".
function breakerSummary(providers) {
  if (!providers || typeof providers !== "object") return "";
  const parts = [];
  for (const [name, p] of Object.entries(providers)) {
    const b = p && p.bezpiecznik;
    if (!b || b.stan === "ok") continue;
    const why = b.powod ? ` (${escapeHtml(String(b.powod))})` : "";
    if (b.stan === "wylaczony") parts.push(`${escapeHtml(name)}: wyłączony do restartu${why}`);
    else parts.push(`${escapeHtml(name)}: odpoczywa jeszcze ${Math.max(0, Math.round(Number(b.sekund) || 0))} s${why}`);
  }
  return parts.length ? ` <span class="warn">bezpiecznik - ${parts.join("; ")}</span>` : "";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderLogFilter(entries) {
  const sel = document.getElementById("logFilter");
  if (!sel) return;
  const stages = [...new Set(entries.map((e) => e.stage))].sort((a, b) =>
    (STAGE_LABELS[a] || a).localeCompare(STAGE_LABELS[b] || b, "pl"));
  if (logFilter && !stages.includes(logFilter)) stages.push(logFilter);
  sel.innerHTML = `<option value="">Wszystkie ścieżki (${entries.length})</option>` + stages.map((st) => {
    const n = entries.filter((e) => e.stage === st).length;
    return `<option value="${escapeHtml(st)}"${st === logFilter ? " selected" : ""}>${escapeHtml(STAGE_LABELS[st] || st)} (${n})</option>`;
  }).join("");
}

function renderLog(allEntries) {
  logEntries = allEntries;
  renderLogFilter(allEntries);
  const entries = logFilter ? allEntries.filter((e) => e.stage === logFilter) : allEntries;
  const tbody = document.querySelector("#logTable tbody");
  const empty = document.getElementById("logEmpty");
  if (!entries.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
    tbody.innerHTML = entries.map((e) => {
      const label = STAGE_LABELS[e.stage] || e.stage;
      const newPattern = e.extra && e.extra.nowy_wzorzec
        ? `<span class="new-pattern">+ nowy wzorzec: ${escapeHtml(e.extra.nowy_wzorzec.join(", "))}</span>`
        : "";
      const newTopicWords = e.extra && e.extra.nowe_slowa_tematu
        ? `<span class="new-pattern topic">+ słowo do dopytań: ${escapeHtml(e.extra.nowe_slowa_tematu.join(", "))}</span>`
        : "";
      const forgotten = e.extra && e.extra.zapomniane
        ? `<span class="new-pattern forgotten">− zapomniane: ${escapeHtml(e.extra.zapomniane.join(", "))}</span>`
        : "";
      // Koryto (dawniej żongler/chmura): skąd naprawdę przyszła odpowiedź (juggler_provider), i - gdy
      // zamiast tego trafiło do lokalnego modelu - DLACZEGO poprzednie kroki zawiodły
      // (juggler_error/cloud_error, patrz agent/router.py _record_distill_pair i "Krok 2a0"/"2a").
      // Bez tego /debug nie pokazywał żadnego powodu, dlaczego mimo skonfigurowanego
      // klucza rozmowa i tak poszła do wolnego lokalnego modelu.
      // 1.18.0: dostawca opisany etapem koryta - "anthropic" to Claude (etap
      // pierwszy), reszta to darmowa pula.
      const jugglerProvider = e.extra && e.extra.juggler_provider
        ? (e.extra.juggler_provider === "anthropic"
          ? `<span class="new-pattern" title="odpowiedział pierwszy etap koryta">Claude</span>`
          : `<span class="new-pattern" title="odpowiedział dostawca z darmowej puli">darmowa pula: ${escapeHtml(e.extra.juggler_provider)}</span>`)
        : "";
      const extraChip = (key, text, cls = "forgotten", title = "") => (e.extra && e.extra[key]
        ? `<span class="new-pattern ${cls}"${title ? ` title="${escapeHtml(title)}"` : ""}>${escapeHtml(text(e.extra[key]))}</span>`
        : "");
      const korytoEtap = extraChip("koryto", (v) => `etap: ${v}`, "", "etap koryta, który odpowiedział");
      const localSkip = extraChip("lokalnie", (v) => `lokalnie: ${v}`, "forgotten", "dlaczego lokalny etap nie odpowiedział");
      const ollamaError = extraChip("ollama_error", (v) => `model lokalny błąd: ${v}`, "forgotten");
      const notesError = extraChip("notatki_error", (v) => `notatki błąd: ${v}`, "forgotten");
      const modelDown = extraChip("model_down", () => "model lokalny niedostępny", "forgotten");
      const routingCtx = extraChip("routing_kontekst", () => "argument z kontekstu rozmowy", "topic", "narzędzie dostało temat z poprzednich wiadomości - nie uczy się z tego wzorca");
      const jugglerJuniors = e.extra && e.extra.juggler_juniorzy
        ? `<span class="new-pattern" title="dostawcy, którzy zrobili research">juniorzy: ${escapeHtml(e.extra.juggler_juniorzy.join(", "))}</span>`
        : "";
      const jugglerError = e.extra && e.extra.juggler_error
        ? `<span class="new-pattern forgotten" title="darmowa pula zawiodła, spróbowano dalej">darmowa pula błąd: ${escapeHtml(e.extra.juggler_error)}</span>`
        : "";
      const cloudError = e.extra && e.extra.cloud_error
        ? `<span class="new-pattern forgotten" title="Claude zawiódł, spróbowano dalej">Claude błąd: ${escapeHtml(e.extra.cloud_error)}</span>`
        : "";
      const studentError = e.extra && e.extra.student_error
        ? `<span class="new-pattern forgotten" title="uczeń zawiódł, spróbowano dalej">uczeń błąd: ${escapeHtml(e.extra.student_error)}</span>`
        : "";
      // Model (np. żongler: Groq openai/gpt-oss-20b) wypluł surowy token
      // czatu albo niewykonaną próbę wywołania narzędzia własną składnią
      // (np. "<|toolcallstart|>[searchbrain(...)]<|toolcall_end|>") zamiast
      // zwykłej odpowiedzi - router.py (_sanitize_leaked_tokens) to wyciął
      // PRZED pokazaniem w czacie, ale tu widać, że się zdarzyło.
      const sanitizedLeak = e.extra && e.extra.sanitized_leak
        ? `<span class="new-pattern forgotten" title="model wypluł surowy token czatu/próbę wywołania narzędzia - wycięte przed pokazaniem">wyczyszczono wyciek</span>`
        : "";
      return `<tr>
        <td class="mono">${fmtTime(e.ts)}</td>
        <td><span class="badge badge-${escapeHtml(e.stage)}${STAGE_TONED.has(e.stage) ? " tone" : ""}">${escapeHtml(label)}</span>${newPattern}${newTopicWords}${forgotten}${jugglerProvider}${korytoEtap}${jugglerJuniors}${jugglerError}${cloudError}${studentError}${ollamaError}${localSkip}${notesError}${modelDown}${routingCtx}${sanitizedLeak}</td>
        <td class="msg" title="${escapeHtml(e.message)}">${escapeHtml(e.message)}</td>
        <td class="mono">${escapeHtml(e.tool || "")}</td>
        <td class="mono">${fmtMs(e.took_ms)}</td>
      </tr>`;
    }).join("");
  }

  // Krótkie podsumowanie na górze: ile decyzji poszło którą ścieżką,
  // żeby jednym spojrzeniem widzieć, jak często Ollama jest w ogóle
  // potrzebna.
  // Liczone ze WSZYSTKICH wpisów, nie tylko z filtra.
  const all = allEntries;
  const counts = {};
  for (const e of all) counts[e.stage] = (counts[e.stage] || 0) + 1;
  const fast = (counts.szybka_sciezka || 0) + (counts.wyuczona_sciezka || 0);
  const viaNet = (e) => NETWORK_STAGES.has(e.stage) || (e.extra && (e.extra.koryto === "anthropic" || e.extra.koryto === "darmowe"
    || String(e.extra.router_model || "").startsWith("koryto:")));
  const net = all.filter(viaNet).length;
  const local = all.filter((e) => LOCAL_STAGES.has(e.stage) && !viaNet(e)).length;
  document.getElementById("statTotal").innerHTML = `<b>${all.length}</b> ${pluralPlD(all.length, "decyzja", "decyzje", "decyzji")}`;
  document.getElementById("statFast").innerHTML = `<b>${fast}</b> bez czekania na model`;
  document.getElementById("statModel").innerHTML = `<b>${net}</b> przez sieć · <b>${local}</b> lokalnie`;
  document.getElementById("statModel").title = "Sieć: Claude albo darmowa pula (koryto). Lokalnie: model na tym komputerze.";
}

function renderLearned(routes) {
  const tbody = document.querySelector("#learnedTable tbody");
  const empty = document.getElementById("learnedEmpty");
  if (!routes.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
    tbody.innerHTML = routes.map((r) => `<tr>
        <td class="mono">${escapeHtml(r.tool)}</td>
        <td class="words">${escapeHtml(r.words.join(", "))}</td>
        <td>${r.hits || 0}</td>
        <td class="msg" title="${escapeHtml(r.example)}">${escapeHtml(r.example)}</td>
        <td class="mono">${r.last_used ? fmtTime(r.last_used) : "nigdy"}</td>
        <td><button type="button" class="lan-small-btn learned-forget" data-tool="${escapeHtml(r.tool)}" data-words="${escapeHtml(JSON.stringify(r.words))}">Zapomnij</button></td>
      </tr>`).join("");
    // 1.32.11: wzorzec da się usunąć ręcznie (źle wyuczony przekierowywał niezwiązane pytania).
    tbody.querySelectorAll(".learned-forget").forEach((btn) => btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await apiFetch("/api/debug/learned/zapomnij", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tool: btn.dataset.tool, words: JSON.parse(btn.dataset.words) }),
        });
        const d = await res.json();
        if (d.error) throw new Error(d.error);
        btn.closest("tr").remove();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "Nie udało się";
      }
    }));
  }
  document.getElementById("statLearned").innerHTML = `<b>${routes.length}</b> ${pluralPlD(routes.length, "wyuczony wzorzec", "wyuczone wzorce", "wyuczonych wzorców")}`;
}

function renderTopicWords(topicWords) {
  const tbody = document.querySelector("#topicTable tbody");
  const empty = document.getElementById("topicEmpty");
  const keys = Object.keys(topicWords).filter((k) => (topicWords[k] || []).length);
  if (!keys.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
    tbody.innerHTML = keys.map((key) => `<tr>
        <td class="mono">${escapeHtml(key)}</td>
        <td class="words">${escapeHtml(topicWords[key].join(", "))}</td>
      </tr>`).join("");
  }
}

function fmtMb(mb) {
  if (mb == null) return "?";
  if (mb >= 1024) return (mb / 1024).toFixed(1).replace(".", ",") + " GB";
  return mb + " MB";
}

// Dziennik audytu SYSOP (data/sysop_log.json): ostatnie wykonane i odrzucone
// operacje. Pole "ok" = false oznacza błąd albo odmowę.
function renderSysopLog(entries) {
  const tbody = document.querySelector("#sysopTable tbody");
  const empty = document.getElementById("sysopEmpty");
  const list = Array.isArray(entries) ? entries.slice().reverse() : [];
  if (!list.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  tbody.innerHTML = list.map((e) => `<tr>
      <td class="mono">${e.ts ? fmtTime(e.ts) : ""}</td>
      <td class="mono">${escapeHtml(e.tool || "")}</td>
      <td class="msg" title="${escapeHtml(e.arg || e.speech || "")}">${escapeHtml(e.arg || "")}</td>
      <td class="mono">${escapeHtml(e.tier || "")}</td>
      <td><span class="${e.ok ? "ok" : "warn"}">${e.ok ? "wykonane" : "odmowa/błąd"}</span></td>
    </tr>`).join("");
}

// Blok „Teraz” (/api/debug/teraz, agent/awareness.py): dokładnie to, co model
// dostanie przy najbliższej wiadomości. textContent, nie innerHTML: w bloku są
// fakty wpisane przez użytkownika (memory/), nigdy nie wolno ich renderować
// jako HTML.
function renderTeraz(data) {
  const localEl = document.getElementById("terazLocal");
  const cloudEl = document.getElementById("terazCloud");
  const empty = document.getElementById("terazEmpty");
  const label = document.getElementById("terazLocalLabel");
  if (!data || typeof data.local !== "string") {
    localEl.textContent = "";
    cloudEl.textContent = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  localEl.textContent = data.local;
  cloudEl.textContent = data.cloud || "";
  const parts = [`Model lokalny (Ollama): ${data.local.length}/${data.max_chars || "?"} znaków`];
  if (data.next_clock_change) parts.push(`następna zmiana pory dnia o ${data.next_clock_change}`);
  label.textContent = parts.join(" · ");
}


// --- 1.33.1: Nadzorca w dwóch kolumnach -----------------------------------
// Koryto jako rura, tabela modeli, timeline Straży i paski budżetu. Wszystko
// czyta istniejące /api/system_info (bez nowych endpointów i bez zmian w
// agent/), a animacje są w debug.css (CSP: zero <style>).

function dbgUsd(x) {
  return Number(x || 0).toFixed(2).replace(".", ",");
}

function dbgSecs(s) {
  const n = Math.max(0, Number(s) || 0);
  if (n < 9.95) return n.toFixed(1).replace(".", ",") + "s";
  return Math.round(n) + "s";
}

function dbgMedian(values) {
  const v = values.map(Number).filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

// Mediana czasu typowej fazy dla dostawcy, z tych samych próbek co stepper
// w app.js (localStorage["gregai.fazeTimes"]). <3 próbek = null (nie zgadujemy).
function dbgEta(provider) {
  try {
    const all = JSON.parse(localStorage.getItem("gregai.fazeTimes") || "{}");
    const vals = [];
    for (const key of Object.keys(all)) {
      if (key.startsWith((provider || "") + "|") && Array.isArray(all[key])) vals.push(...all[key]);
    }
    return vals.length >= 3 ? dbgMedian(vals) : null;
  } catch (e) { return null; }
}

const DBG_PROVIDER_LABELS = {
  groq: "Groq", gemini: "Gemini", openrouter: "OpenRouter",
  huggingface: "HuggingFace", cloudflare: "Cloudflare",
};

function providerState(p) {
  const b = (p && p.bezpiecznik) || {};
  if (!p || !p.key_present) return { cls: "off", badge: "brak", title: "brak klucza w .env" };
  if (p.budzet_wyczerpany) return { cls: "bad", badge: "budżet", title: String(p.budzet_wyczerpany) };
  const why = String(b.powod || "");
  if (b.stan === "wylaczony") {
    const code = /429/.test(why) ? "429" : /401/.test(why) ? "401" : /402/.test(why) ? "402" : "wył.";
    return { cls: "bad", badge: code, title: why || "wyłączony do restartu" };
  }
  if (b.stan === "cooldown") {
    // 1.33.1: 429 (także dzienny, 4 h) to dla użytkownika "wyczerpany" - czerwony
    // z kodem, a nie szary "cooldown". `bezpiecznik.powod` nie niesie kodu HTTP,
    // więc długość przerwy jest drugim sygnałem: 4 h = dzienny 429, 15 min = 403.
    const left = Math.max(0, Math.round(Number(b.sekund) || 0));
    if (/429/.test(why) || left >= 3600) return { cls: "bad", badge: "429", title: /429/.test(why) ? why : `przerwa ${left} s - dzienny limit (429)` };
    if (/403/.test(why) || left >= 600) return { cls: "bad", badge: "403", title: /403/.test(why) ? why : `przerwa ${left} s (403)` };
    return { cls: "warn", badge: "cooldown " + left + "s", title: why };
  }
  const lim = Number(p.daily_limit || 0), used = Number(p.today_calls || 0);
  if (lim && used >= lim) return { cls: "bad", badge: "429", title: `limit dzienny ${used}/${lim}` };
  return { cls: "ok", badge: "gotowy", title: (p.model || "") + (lim ? ` · dziś ${used}/${lim}` : "") };
}

function providerChip(name, p) {
  const st = providerState(p);
  return `<span class="dbg-chip ${st.cls}" title="${escapeHtml(st.title || "")}">` +
    `${escapeHtml(DBG_PROVIDER_LABELS[name] || name)} <b>${escapeHtml(st.badge)}</b></span>`;
}

function renderKorytoPipe(data) {
  const box = document.getElementById("korytoPipe");
  const empty = document.getElementById("korytoEmpty");
  if (!box || !empty) return;
  const k = data && data.koryto;
  if (!k) { box.innerHTML = ""; empty.classList.remove("hidden"); return; }
  const eff = (k.efektywna && (k.efektywna["2"] || k.efektywna["3"])) || k.kolejnosc || [];
  if (!eff.length) { box.innerHTML = ""; empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden");
  const providers = (data.juggler && data.juggler.providers) || {};
  const ollama = data.ollama || {};
  const localEta = dbgEta("lokalnie");
  let activeSet = false;
  const stages = [];

  for (const etap of eff) {
    let cls = "off", badge = "brak", title = "", body = "", usable = false;
    if (etap === "anthropic") {
      const p = providers.anthropic || {};
      const st = providerState(p);
      cls = st.cls; badge = st.badge; title = st.title;
      usable = st.cls === "ok";
      const used = Number(p.today_calls || 0), lim = Number(p.daily_limit || 0);
      body = `<div class="dbg-pipe-name">Claude</div>` +
        `<div class="dbg-pipe-sub">${escapeHtml(p.model || (data.cloud && data.cloud.model) || "Anthropic")}` +
        (lim ? ` · dziś ${used}/${lim}` : "") + `</div>`;
    } else if (etap === "darmowe") {
      const names = Object.keys(DBG_PROVIDER_LABELS);
      const good = names.filter((n) => providerState(providers[n]).cls === "ok").length;
      usable = good > 0;
      cls = usable ? "ok" : "bad";
      badge = `${good}/${names.length}`;
      title = usable ? "co najmniej jeden darmowy dostawca gotowy" : "żaden darmowy dostawca nie jest gotowy";
      body = `<div class="dbg-pipe-name">Darmowa pula</div>` +
        `<div class="dbg-pipe-chips">${names.map((n) => providerChip(n, providers[n])).join("")}</div>`;
    } else if (etap === "lokalnie") {
      const reach = !!ollama.reachable;
      const warming = data.warm && data.warm.state === "trwa";
      cls = warming ? "warn" : reach ? "ok" : "bad";
      badge = warming ? "rozgrzewa" : reach ? "gotowy" : "brak";
      usable = reach;
      title = warming ? "model wczytuje się do RAM" : reach ? "Ollama odpowiada" : "Ollama nie odpowiada";
      const eta = localEta != null ? ` · ≈ ${dbgSecs(localEta)}` : "";
      body = `<div class="dbg-pipe-name">Lokalnie</div>` +
        `<div class="dbg-pipe-sub">${escapeHtml(data.ollama_model || "Ollama")}${eta}</div>`;
    } else {
      continue;
    }
    const active = !activeSet && usable;
    if (active) activeSet = true;
    stages.push(
      `<div class="dbg-pipe-stage ${cls}${active ? " active" : ""}" title="${escapeHtml(title)}">` +
      `<div class="dbg-pipe-node">${active ? '<span class="dbg-pipe-flow" aria-hidden="true"></span>' : ""}${body}</div>` +
      `<span class="dbg-pipe-badge ${cls}">${escapeHtml(badge)}</span>` +
      `</div>`
    );
  }
  box.innerHTML = stages.join('<span class="dbg-pipe-link" aria-hidden="true"></span>');
}

function renderModelTable(data) {
  const table = document.getElementById("modelTable");
  const empty = document.getElementById("modelEmpty");
  if (!table || !empty) return;
  const o = (data && data.ollama) || {};
  const installed = Array.isArray(o.installed) ? o.installed : [];
  const loaded = Array.isArray(o.loaded) ? o.loaded : [];
  const installedMap = new Map(installed.map((m) => [String(m.name), m]));
  const loadedMap = new Map(loaded.map((m) => [String(m.name), m]));
  const warm = (data && data.warm) || {};
  const eta = dbgEta("lokalnie");
  const rows = new Map();
  const add = (name, role) => {
    const n = String(name || "").trim();
    if (!n) return;
    if (!rows.has(n)) rows.set(n, { name: n, role: role || "" });
  };
  add(data && data.ollama_model, "rozmowa");
  if (data && data.router && data.router.enabled) add(data.router.model, "router");
  if (data && data.student && data.student.enabled) add(data.student.model, "uczeń");
  if (data && data.planner && data.planner.enabled) add(data.planner.model, "planer");
  for (const m of installed) add(m.name, "");
  if (!rows.size) {
    table.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  table.classList.remove("hidden");
  const out = [];
  let main = true;
  for (const row of rows.values()) {
    const ld = loadedMap.get(row.name);
    const inst = installedMap.get(row.name);
    let cls = "off", status = "brak", ram = "—";
    if (ld) {
      cls = "ok"; status = "gotowy";
      ram = fmtMb(ld.size_vram_mb || ld.size_mb);
    } else if (warm.state === "trwa" && String(warm.detail || "").includes(row.name)) {
      cls = "warn"; status = "rozgrzewa";
    } else if (inst) {
      cls = "ok"; status = "gotowy";
    }
    const role = row.role ? `<span class="dbg-model-role">${escapeHtml(row.role)}</span>` : "";
    out.push(`<tr><td class="dbg-model-name">${escapeHtml(row.name)}${role}</td>` +
      `<td class="mono">${escapeHtml(ram)}</td>` +
      `<td class="mono">${eta != null ? "≈ " + escapeHtml(dbgSecs(eta)) : "—"}</td>` +
      `<td><span class="dbg-status ${cls}">${escapeHtml(status)}</span></td></tr>`);
    main = false;
    if (out.length >= 12) break;
  }
  table.querySelector("tbody").innerHTML = out.join("");
}

// --- 1.35.0: archiwum Straży, koryto, budżet, sieć, eval -------------------
let strazData = { wpisy: [], wyciszone: {} };
let strazPoziom = "";
let strazLimit = 50;

function renderStrazTimeline() {
  const box = document.getElementById("strazTimeline");
  const empty = document.getElementById("strazTimelineEmpty");
  if (!box || !empty) return;
  const ack = strazData.wyciszone || {};
  let items = Array.isArray(strazData.wpisy) ? strazData.wpisy : [];
  if (strazPoziom) items = items.filter((a) => a.poziom === strazPoziom);
  const moreBtn = document.getElementById("strazMoreBtn");
  if (moreBtn) moreBtn.disabled = items.length <= strazLimit;
  items = items.slice(0, strazLimit);
  if (!items.length) {
    box.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  box.innerHTML = items.map((a) => {
    const ts = String(a.ts || "");
    const kiedy = escapeHtml(ts.slice(0, 16).replace("T", " ") || "?");
    const ocena = a.ocena ? `<div class="dbg-tl-ocena">${escapeHtml(a.ocena)}</div>` : "";
    const wyciszone = !!ack[ts];
    const akcja = wyciszone
      ? `<span class="dbg-ack is-ack">WYCISZONE</span>`
      : `<button type="button" class="dbg-ack" data-ack="${escapeHtml(ts)}">WYCISZ</button>`;
    return `<li class="poziom-${escapeHtml(a.poziom || "inne")}${wyciszone ? " is-ack" : ""}">` +
      `<span class="dbg-tl-dot" aria-hidden="true"></span>` +
      `<div class="dbg-tl-body"><time>${kiedy}</time>` +
      `<div class="dbg-tl-co">${escapeHtml(a.co || "—")}</div>${ocena}${akcja}</div></li>`;
  }).join("");
  box.querySelectorAll("[data-ack]").forEach((btn) => btn.addEventListener("click", async () => {
    const ts = btn.dataset.ack;
    btn.disabled = true;
    try {
      const res = await apiFetch("/api/straz/wycisz", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ts }),
      });
      const data = await res.json();
      if (data.ok) {
        strazData.wyciszone = Object.assign({}, strazData.wyciszone, { [ts]: "1" });
        renderStrazTimeline();
      }
    } catch (e) { btn.disabled = false; }
  }));
}

function renderKorytoHistory(data) {
  data = data || {};
  const tbody = document.querySelector("#korytoHistoria tbody");
  const empty = document.getElementById("korytoHistoriaEmpty");
  const items = Array.isArray(data.wywolania) ? data.wywolania : [];
  if (tbody && empty) {
    if (!items.length) {
      tbody.innerHTML = "";
      empty.classList.remove("hidden");
    } else {
      empty.classList.add("hidden");
      tbody.innerHTML = items.map((w) => {
        const czas = String(w.ts || "").slice(11, 19) || "—";
        const kto = w.kto === "claude" ? "Claude" : w.kto === "darmowe" ? "Darmowa pula" : "Lokalnie";
        const etap = STAGE_LABELS[w.etap] || w.etap || "—";
        const sek = Number(w.sekund);
        return `<tr><td>${escapeHtml(czas)}</td><td>${escapeHtml(kto)}</td>` +
          `<td>${escapeHtml(etap)}</td><td>${Number.isFinite(sek) ? escapeHtml(dbgSecs(sek)) : "—"}</td></tr>`;
      }).join("");
    }
  }
  const bars = document.getElementById("korytoBars");
  const barsEmpty = document.getElementById("korytoBarsEmpty");
  if (!bars || !barsEmpty) return;
  const counts = Object.entries(data.wywolania_dzis || {}).filter(([, n]) => Number(n) > 0);
  counts.sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!counts.length) {
    bars.innerHTML = "";
    barsEmpty.classList.remove("hidden");
    return;
  }
  barsEmpty.classList.add("hidden");
  const max = Math.max(...counts.map(([, n]) => Number(n) || 0), 1);
  bars.innerHTML = counts.slice(0, 8).map(([name, n]) =>
    `<div class="dbg-bar-row"><span class="dbg-bar-name">${escapeHtml(name)}</span>` +
    `<div class="dbg-bar-track"><div class="dbg-bar-fill" data-n="${Number(n)}"></div></div>` +
    `<span class="dbg-bar-val">${escapeHtml(String(n))}</span></div>`).join("");
  bars.querySelectorAll(".dbg-bar-fill").forEach((el) => {
    el.style.setProperty("--f", String(Math.max(0.02, Number(el.dataset.n || 0) / max)).slice(0, 6));
  });
}

function renderModelLog(data) {
  const tbody = document.querySelector("#modelLog tbody");
  const empty = document.getElementById("modelLogEmpty");
  if (!tbody || !empty) return;
  const items = Array.isArray(data && data.inferencje) ? data.inferencje : [];
  if (!items.length) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  tbody.innerHTML = items.map((m) => {
    const czas = String(m.ts || "").slice(11, 19) || "—";
    const tok = m.tok_s == null ? "—" : String(m.tok_s).replace(".", ",");
    return `<tr><td>${escapeHtml(czas)}</td><td>${escapeHtml(m.model || "?")}</td>` +
      `<td>${m.sekund == null ? "—" : escapeHtml(String(m.sekund).replace(".", ","))}</td>` +
      `<td>${escapeHtml(tok)}</td></tr>`;
  }).join("");
}

function renderBudgetDetails(data) {
  data = data || {};
  const sp = data.budzet || {};
  const sum = document.getElementById("budzetSuma");
  if (sum) {
    const used = Number(sp.dzien || 0).toFixed(2).replace(".", ",");
    const limit = Number(sp.limit_dzien || 0).toFixed(2).replace(".", ",");
    sum.textContent = `SUMA: $${used} / $${limit}`;
  }
  const tbody = document.querySelector("#budzetTabela tbody");
  const empty = document.getElementById("budzetTabelaEmpty");
  if (!tbody || !empty) return;
  const items = Array.isArray(data.wydatki) ? data.wydatki : [];
  if (!items.length) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  tbody.innerHTML = items.map((w) => {
    const czas = String(w.ts || "").slice(11, 19) || "—";
    const usd = Number(w.usd || 0);
    return `<tr><td>${escapeHtml(czas)}</td><td>${escapeHtml(w.model || "?")}</td>` +
      `<td>${escapeHtml(String(w.wejscie ?? 0))}</td><td>${escapeHtml(String(w.wyjscie ?? 0))}</td>` +
      `<td>${usd ? "$" + usd.toFixed(4).replace(".", ",") : "$0"}</td></tr>`;
  }).join("");
}

function renderSiec(data) {
  data = data || {};
  const meta = document.getElementById("siecMeta");
  const btn = document.getElementById("siecSkanBtn");
  const skan = data.skan || {};
  if (meta) {
    if (skan.running) meta.textContent = "SKANOWANIE…";
    else if (skan.time) meta.textContent = `OSTATNI SKAN: ${String(skan.time).replace("T", " ").slice(0, 16)} · ${skan.devices_seen ?? "?"} urz.`;
    else meta.textContent = "BRAK SKANU";
  }
  if (btn) {
    btn.disabled = !!skan.running;
    btn.textContent = skan.running ? "Skanowanie…" : "Skanuj teraz";
  }
  const tbody = document.querySelector("#siecTabela tbody");
  const empty = document.getElementById("siecEmpty");
  if (!tbody || !empty) return;
  const items = Array.isArray(data.urzadzenia) ? data.urzadzenia : [];
  if (!items.length) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  tbody.innerHTML = items.map((u) => {
    const nazwa = u.hostname || u.vendor || "—";
    const last = u.last_seen ? String(u.last_seen).replace("T", " ").slice(0, 16) : "—";
    return `<tr><td>${escapeHtml(u.ip || "—")}</td><td>${escapeHtml(nazwa)}</td>` +
      `<td><span class="dbg-online ${u.online ? "on" : "off"}">${u.online ? "ONLINE" : "OFFLINE"}</span></td>` +
      `<td>${escapeHtml(last)}</td></tr>`;
  }).join("");
}

function renderEval(data) {
  data = data || {};
  const meta = document.getElementById("evalOstatni");
  const btn = document.getElementById("evalRunBtn");
  const pre = document.getElementById("evalWynik");
  const run = data.uruchomienie || {};
  const items = Array.isArray(data.rekordy) ? data.rekordy : [];
  if (meta) {
    if (run.running) meta.textContent = "TRWA…";
    else if (items.length) {
      const r = items[0];
      meta.textContent = `OSTATNI: ${r.zaliczone}/${r.przypadki} — ${String(r.ts || "").replace("T", " ").slice(0, 16)}`;
    } else meta.textContent = "BRAK HISTORII";
  }
  if (btn) {
    btn.disabled = !!run.running;
    btn.textContent = run.running ? "Liczy…" : "Uruchom";
  }
  if (pre) {
    const wynik = String(run.wynik || "");
    pre.textContent = wynik;
    pre.classList.toggle("hidden", !wynik);
  }
  const tbody = document.querySelector("#evalHistoria tbody");
  const empty = document.getElementById("evalHistoriaEmpty");
  if (!tbody || !empty) return;
  if (!items.length) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  tbody.innerHTML = items.map((r) => {
    const ts = String(r.ts || "").replace("T", " ").slice(0, 16) || "—";
    const ok = Number(r.zaliczone) >= Number(r.przypadki);
    return `<tr><td>${escapeHtml(ts)}</td><td>${escapeHtml(r.tryb || "?")}</td>` +
      `<td><span class="${ok ? "ok" : "warn"}">${escapeHtml(String(r.zaliczone))}/${escapeHtml(String(r.przypadki))}</span></td></tr>`;
  }).join("");
}

function renderBudget(bu) {
  const box = document.getElementById("budgetBars");
  const empty = document.getElementById("budgetEmpty");
  if (!box || !empty) return;
  const rows = [];
  if (bu) {
    if (Number(bu.limit_dzien) > 0) rows.push({ label: "Dzień", used: Number(bu.dzien) || 0, limit: Number(bu.limit_dzien) });
    if (Number(bu.limit_miesiac) > 0) rows.push({ label: "Miesiąc", used: Number(bu.miesiac) || 0, limit: Number(bu.limit_miesiac) });
  }
  if (!rows.length) {
    box.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  box.innerHTML = rows.map((r) => {
    const pct = Math.max(0, Math.min(100, 100 * r.used / r.limit));
    const cls = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
    return `<div class="dbg-budget-row">` +
      `<div class="dbg-budget-head"><span>${escapeHtml(r.label)}</span>` +
      `<span class="dbg-budget-val">${escapeHtml(dbgUsd(r.used))} / ${escapeHtml(dbgUsd(r.limit))} USD</span></div>` +
      `<div class="dbg-budget-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(pct)}">` +
      `<div class="dbg-budget-fill ${cls}"></div></div></div>`;
  }).join("");
  // Szerokość przez CSS variable + transform: scaleX(var(--f)) - GPU, bez layoutu.
  box.querySelectorAll(".dbg-budget-fill").forEach((el, i) => {
    const r = rows[i];
    el.style.setProperty("--f", String(Math.max(0, Math.min(1, r.used / r.limit)).toFixed(4)));
  });
}

function renderSysInfo(data) {
  const grid = document.getElementById("sysinfoGrid");
  const empty = document.getElementById("sysinfoEmpty");
  // Gdy odczyt parametrów się nie udał, dziennik zostaje taki, jaki był (nie ma danych, więc nie
  // twierdzimy, że "nic się nie działo").
  if (data && data.sysop) renderSysopLog(data.sysop.recent);
  else if (data) renderSysopLog([]);
  // 1.33.1: nowe bloki Nadzorcy (lewa: straż i budżet, prawa: koryto i modele).
  // Renderują także przy niepełnym odczycie - ale same pokazują wtedy "brak danych".
  renderBudget(data && data.budzet);
  renderKorytoPipe(data);
  renderModelTable(data);
  if (!data || !data.host) {
    grid.innerHTML = "";
    empty.style.display = "block";
    renderHero(null);
    return;
  }
  empty.style.display = "none";
  const h = data.host;
  const o = data.ollama || { reachable: false, installed: [], loaded: [] };

  // RAM wolnej mniej niż 1GB albo poniżej 15% całości: to jest ten
  // próg, przy którym na tym laptopie realnie zaczyna się swapowanie
  // (patrz router.py: swap = o wiele wolniejsze odpowiedzi modelu niż
  // samo dekodowanie na CPU by sugerowało).
  const ramLowFrac = h.ram_total_mb ? h.ram_available_mb / h.ram_total_mb : 1;
  const ramWarn = h.ram_available_mb != null && (h.ram_available_mb < 1024 || ramLowFrac < 0.15);

  const loaded = o.loaded && o.loaded.length
    ? o.loaded.map((m) => `${escapeHtml(m.name)} (${fmtMb(m.size_mb)} w RAM)`).join(", ")
    : "nic teraz nie wczytane";
  const installed = o.installed && o.installed.length
    ? o.installed.map((m) => `${escapeHtml(m.name)} (${fmtMb(m.size_mb)} na dysku)`).join(", ")
    : "brak";

  // 1.24.0: najpierw cztery rzeczy zrozumiałe bez słownika, reszta pod "Szczegóły techniczne".
  const st = data.straz || {};
  const bu = data.budzet || {};
  const fmtUsd = (x) => Number(x || 0).toFixed(2).replace(".", ",");
  const main = [
    ["Internet (przez WARP)", data.warp
      ? (data.warp.connected ? '<span class="ok">działa, chroniony</span>'
        : `<span class="warn">zablokowany: ${escapeHtml(data.warp.reason || "WARP rozłączony")}</span>`)
      : '<span class="warn">brak danych</span>'],
    ["Straż komputera", st.wlaczona === false ? '<span class="warn">wyłączona</span>'
      : (typeof st.sekund_temu === "number" ? `<span class="ok">pilnuje</span> · obchód ${st.sekund_temu} s temu` : "startuje")],
    ["Budżet na Claude (miesiąc)", bu.limit_miesiac
      ? `<span class="${bu.miesiac >= bu.limit_miesiac ? "warn" : (bu.miesiac >= 0.8 * bu.limit_miesiac ? "warn" : "ok")}">${fmtUsd(bu.miesiac)} z ${Math.round(bu.limit_miesiac)} USD</span> · dziś ${fmtUsd(bu.dzien)}`
      : "brak danych"],
    ["Pamięć komputera (RAM)", `<span class="${ramWarn ? "warn" : "ok"}">${fmtMb(h.ram_available_mb)} wolne</span> z ${fmtMb(h.ram_total_mb)}`],
  ];
  const items = [
    ["CPU", `${escapeHtml(h.cpu_model || "?")} · ${escapeHtml(h.cpu_logical_cores || "?")} wątki`],
    ["RAM wolna / cała", `<span class="${ramWarn ? "warn" : "ok"}">${fmtMb(h.ram_available_mb)}</span> / ${fmtMb(h.ram_total_mb)}`],
    ["Swap wolny / cały", `${fmtMb(h.swap_free_mb)} / ${fmtMb(h.swap_total_mb)}`],
    ["Dysk wolny", h.disk_free_gb != null ? h.disk_free_gb + " GB" : "?"],
    ["Cloudflare WARP", data.warp
      ? (data.warp.connected
          ? '<span class="ok">połączony</span>'
          : `<span class="warn">${escapeHtml(data.warp.reason || "rozłączony - internet zablokowany")}</span>`)
      : '<span class="warn">brak danych</span>'],
    ["Model na laptopie (Ollama)", o.reachable ? '<span class="ok">działa</span>' : '<span class="warn">nie odpowiada</span>'],
    // Koryto (1.17.0, agent/koryto.py; 1.32.30): efektywna kolejność per waga
    // uwagi (rozdzielnica), nie sama lista z .env - inaczej panel mówi "Claude
    // pierwszy", gdy przy wadze 1-2 pytana jest darmowa pula.
    ["Kto odpowiada, po kolei (koryto)", (() => {
      if (!data.koryto) return "brak danych";
      const nazwa = (e) => e === "anthropic" ? "Claude" : e === "darmowe" ? "darmowa pula" : "lokalny";
      const fmt = (arr) => (arr || []).map(nazwa).join(" -> ") || "?";
      const eff = data.koryto.efektywna || {};
      const policy = data.koryto.rozdzielnica ? ` (polityka ${escapeHtml(data.koryto.rozdzielnica)})` : "";
      const wiersze = (eff["2"] || eff["3"])
        ? `<span class="ok">waga 1-2:</span> ${escapeHtml(fmt(eff["2"]))}<br><span class="ok">waga 3-4:</span> ${escapeHtml(fmt(eff["3"]))}`
        : escapeHtml(data.koryto.opis || (data.koryto.kolejnosc || []).join(" -> ") || "?");
      return wiersze + policy
        + (data.koryto.routing_siecia ? "" : " <span class=\"warn\">(routing lokalnie: KORYTO_ROUTING=0)</span>")
        + (data.koryto.zadania_siecia ? "" : " <span class=\"warn\">(planer zadań lokalnie: KORYTO_ZADANIA=0)</span>");
    })()],
    ["Claude (Anthropic, płatny)", data.cloud ? escapeHtml(data.cloud.reason || "?") : "brak danych"],
    ["Darmowe AI w zapasie", data.juggler ? escapeHtml(data.juggler.reason || "?") + breakerSummary(data.juggler.providers) : "brak danych"],
    ["Router", data.router ? escapeHtml(data.router.reason || "?") : "brak danych"],
    ["Uczeń", data.student ? escapeHtml(data.student.reason || "?") : "brak danych"],
    ["Planer", data.planner ? escapeHtml(data.planner.reason || "?") : "brak danych"],
    ["Rozgrzewanie modeli", data.warm
      ? (data.warm.state === "gotowe"
          ? `<span class="ok">${escapeHtml(data.warm.detail || "gotowe")}</span>`
          : `<span class="${data.warm.state === "błąd" ? "warn" : ""}">${escapeHtml(data.warm.state)}${data.warm.detail ? ": " + escapeHtml(data.warm.detail) : ""}</span>`)
      : "brak danych"],
    ["Wersja", escapeHtml(data.version || "?") + (data.project_root ? " (" + escapeHtml(data.project_root) + ")" : "")],
    ["SYSOP", data.sysop ? (data.sysop.enabled
      ? (data.sysop.full
          // Tryb pełny (1.17.0, agent/sysop.py "Tryb PEŁNY"): wyizolowane Ubuntu, pełen dostęp.
          ? '<span class="warn">TRYB PEŁNY (SYSOP_MODE=pelny): cały system, sudo bez hasła, dowolny shell; pytania o zgodę: ' + escapeHtml(data.sysop.pytaj || "niebezpieczne") + '</span>'
          : '<span class="ok">włączony: stałe narzędzia (' + (data.sysop.tools ? data.sysop.tools.length : "?") + ')</span>' + (data.sysop.shell ? ' <span class="warn">+ dowolny shell (SYSOP_SHELL=1)</span>' : ", shell wyłączony"))
      : "wyłączony") : "brak danych"],
    ["Model (rdzeń)", escapeHtml(data.ollama_model || "?")],
    ["Wczytany teraz", loaded],
    ["Zainstalowane modele", installed],
  ];
  const tile = ([label, value]) => `
    <div class="sysinfo-item">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${value}</div>
    </div>`;
  // Stan rozwinięcia przeżywa odświeżenie co kilka sekund.
  const wasOpen = !!grid.querySelector("details.sysinfo-more[open]");
  grid.innerHTML = main.map(tile).join("") +
    `<details class="sysinfo-more"${wasOpen ? " open" : ""}><summary>Szczegóły techniczne (${items.length})</summary>` +
    `<div class="sysinfo-more-grid">${items.map(tile).join("")}</div></details>`;
  renderHero(data, { ramWarn });
}

// Podsumowanie na górze: jedno zdanie "czy wszystko gra" zamiast szukania
// po kafelkach. Zbiera tylko to, co realnie wymaga uwagi.
function renderHero(data, extra) {
  const hero = document.getElementById("dbgHero");
  if (!hero) return;
  const ico = document.getElementById("dbgHeroIco");
  const title = document.getElementById("dbgHeroTitle");
  const sub = document.getElementById("dbgHeroSub");
  const dot = document.getElementById("dbgTabDot");
  let state = "ok", problems = [];
  if (!data || !data.host) {
    state = "bad"; problems = ["Nie udało się odczytać stanu systemu. Spróbuj odświeżyć stronę."];
  } else {
    const o = data.ollama || {};
    if (o.reachable === false) problems.push("Model lokalny (Ollama) nie odpowiada.");
    if (data.warp && data.warp.connected === false) problems.push("Cloudflare WARP jest rozłączony, więc internet dla GREGAI jest zablokowany.");
    if (extra && extra.ramWarn) problems.push("Mało wolnej pamięci RAM, odpowiedzi mogą być wolniejsze.");
    if (data.warm && data.warm.state === "błąd") problems.push("Rozgrzewanie modeli zakończyło się błędem.");
    const st = data.straz || {};
    if (st.wlaczona === false) problems.push("Straż systemu jest wyłączona.");
    else if (typeof st.sekund_temu === "number" && st.sekund_temu > 3 * (st.co_s || 60) + 60) problems.push("Straż systemu dawno nie zrobiła obchodu.");
    else if (st.sekund_temu == null && st.bledy > 0) problems.push("Straż systemu nie może zrobić obchodu (błędy). Uruchom gregai check.");
    const bu = data.budzet || {};
    if (bu.limit_miesiac && bu.miesiac >= bu.limit_miesiac) problems.push("Miesięczny budżet na Claude się skończył: GREGAI używa darmowych modeli do końca miesiąca.");
    else if (bu.limit_miesiac && bu.miesiac >= 0.8 * bu.limit_miesiac) problems.push("Zużyto ponad 80% miesięcznego budżetu na Claude.");
    // 1.30.0 (Twierdza): dziennik bezpieczeństwa naruszony = ktoś majstrował przy śladach.
    const dz = st.dziennik_bezp || {};
    if (dz.ok === false) { problems.push("Uwaga: dziennik bezpieczeństwa był zmieniany lub czyszczony (ktoś próbował zatrzeć ślady). Obejrzyj data/straz/bezpieczenstwo.jsonl."); state = "bad"; }
    if (problems.length && state !== "bad") state = "warn";
  }
  hero.dataset.state = state;
  ico.textContent = state === "ok" ? "✅" : state === "warn" ? "⚠️" : "⛔";
  // 1.32.2 (audyt tura 7): "bad" z danymi (np. naruszony dziennik) to nie "brak danych".
  title.textContent = state === "ok" ? "Wszystko działa" : state === "warn" ? "Warto coś sprawdzić"
    : (data && data.host ? "Wymaga pilnej uwagi" : "Brak danych");
  sub.textContent = state === "ok"
    ? "Silnik, internet i pamięć są w porządku. Szczegóły w kafelkach poniżej."
    : problems.join(" ");
  if (dot) dot.classList.toggle("hidden", state === "ok");
  renderGuardLine(data);
}

// 1.24.0: jedna prosta linia pod nagłówkiem: czy straż pilnuje i ile z budżetu poszło.
function renderGuardLine(data) {
  const hero = document.getElementById("dbgHero");
  if (!hero || !data) return;
  let line = document.getElementById("dbgGuardLine");
  if (!line) {
    line = document.createElement("div");
    line.id = "dbgGuardLine";
    line.className = "dbg-guard-line";
    hero.appendChild(line);
  }
  const parts = [];
  const st = data.straz || {};
  if (st.wlaczona === false) parts.push("🛡️ Straż: wyłączona");
  else if (typeof st.sekund_temu === "number") parts.push(`🛡️ Straż pilnuje (obchód ${st.sekund_temu} s temu)`);
  else if (st.wlaczona) parts.push("🛡️ Straż startuje");
  const last = Array.isArray(st.ostatnie) && st.ostatnie[0];
  if (last && last.co) parts.push(`ostatnio: ${last.co}`);
  const bu = data.budzet || {};
  if (bu.limit_miesiac) {
    const fmt = (x) => Number(x || 0).toFixed(2).replace(".", ",");
    parts.push(`💰 Claude w tym miesiącu: ${fmt(bu.miesiac)} z ${Math.round(bu.limit_miesiac)} USD`);
  }
  line.textContent = parts.join(" · ");
  line.hidden = !parts.length;
}

// Zakładki Nadzorcy. Wybór zapamiętany w przeglądarce (opcjonalnie).
const DBG_TABS = ["stan", "koryto", "modele", "straz", "budzet", "siec", "evaluacja", "mysli", "nauka", "system"];
const DBG_TAB_ALIASES = { przeglad: "stan" };
function setDebugTab(name) {
  name = DBG_TAB_ALIASES[name] || name;
  if (!DBG_TABS.includes(name)) name = "stan";
  if (typeof visualClick === "function") visualClick(0.02);
  const root = document.getElementById("debug-segment") || document;
  root.querySelectorAll("[data-tab]").forEach((el) => el.classList.toggle("tab-hidden", el.dataset.tab !== name));
  root.querySelectorAll("[data-tab-btn]").forEach((b) => {
    const on = b.dataset.tabBtn === name;
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
  });
  try { localStorage.setItem("gregai.debugTab", name); } catch (e) { /* ignore */ }
}
(function initDebugTabs() {
  const root = document.getElementById("debug-segment") || document;
  // 1.19.0 (dostępność): zakładki według wzorca WAI-ARIA - panele z rolą
  // tabpanel i powiązaniem z przyciskiem, strzałki/Home/End między zakładkami.
  const btns = [...root.querySelectorAll("[data-tab-btn]")];
  btns.forEach((b) => {
    const tab = b.dataset.tabBtn;
    b.id = b.id || `dbg-tab-${tab}`;
    const panels = [...root.querySelectorAll(`section[data-tab="${tab}"]`)];
    panels.forEach((sec, k) => {
      sec.id = sec.id || `dbg-panel-${tab}-${k}`;
      sec.setAttribute("role", "tabpanel");
      sec.setAttribute("aria-labelledby", b.id);
    });
    b.setAttribute("aria-controls", panels.map((sec) => sec.id).join(" "));
    b.addEventListener("click", () => setDebugTab(tab));
    b.addEventListener("keydown", (e) => {
      const i = btns.indexOf(b);
      let j = null;
      if (e.key === "ArrowRight") j = (i + 1) % btns.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + btns.length) % btns.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = btns.length - 1;
      if (j === null) return;
      e.preventDefault();
      setDebugTab(btns[j].dataset.tabBtn);
      btns[j].focus();
    });
  });
  // Tabele przewijane w poziomie na wąskim ekranie (1.19.0: na telefonie
  // ostatnia kolumna była ucięta).
  root.querySelectorAll("table").forEach((t) => {
    if (t.parentElement && t.parentElement.classList.contains("table-scroll")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-scroll";
    t.parentNode.insertBefore(wrap, t);
    wrap.appendChild(t);
  });
  const filter = document.getElementById("logFilter");
  if (filter) filter.addEventListener("change", () => { logFilter = filter.value; renderLog(logEntries); });
  let saved = "stan";
  try { saved = localStorage.getItem("gregai.debugTab") || saved; } catch (e) { /* ignore */ }
  setDebugTab(saved);
})();

// Przełącznik "dostęp z sieci lokalnej" (GREGAI_LAN, patrz main.py
// _handle_lan_mode). Zapamiętujemy ostatni stan Z SERWERA, żeby kliknięcie
// "Zastosuj" bez żadnej zmiany (checkbox w tej samej pozycji) nic nie robiło
// - restart to kilka sekund przerwy w rozmowie, nie ma po co go wywoływać na darmo.
let _lanServerEnabled = null;

function renderLanAccess(lan) {
  const checkbox = document.getElementById("lanCheckbox");
  const tokenRow = document.getElementById("lanTokenRow");
  const tokenInput = document.getElementById("lanTokenInput");
  if (!lan) return;
  _lanServerEnabled = !!lan.enabled;
  // Nie nadpisuj checkboxa, gdy użytkownik właśnie coś w nim zmienił, a
  // żądanie jeszcze się nie zakończyło (disabled=true w tym oknie).
  if (!checkbox.disabled) checkbox.checked = _lanServerEnabled;
  if (lan.token) {
    tokenInput.value = lan.token;
    tokenRow.classList.remove("hidden");
  } else {
    tokenInput.value = "";
    tokenRow.classList.add("hidden");
  }
}

// 1.32.0: lekcje z rozmów (agent/lekcje.py).
function renderLessons(list) {
  const ol = document.getElementById("lessonList");
  const empty = document.getElementById("lessonEmpty");
  if (!ol || !empty) return;
  ol.innerHTML = "";
  empty.classList.toggle("hidden", list.length > 0);
  for (const l of list) {
    const li = document.createElement("li");
    li.innerHTML = `<b>${escapeHtml(l.tytul || "")}</b>: ${escapeHtml(l.rozwiazanie || "")}` +
      (l.kiedy ? `<span class="lesson-when">Kiedy: ${escapeHtml(l.kiedy)}</span>` : "");
    ol.appendChild(li);
  }
}

// 1.32.0: diagnoza internetu warstwa po warstwie (/api/diagnoza).
function renderDiagnosis(rep) {
  const ol = document.getElementById("diagList");
  const verdict = document.getElementById("diagVerdict");
  if (!ol || !verdict) return;
  ol.innerHTML = "";
  verdict.classList.remove("hidden");
  verdict.dataset.ok = rep.internet && !(rep.warstwy || []).some((l) => l.ok === false) ? "1" : "0";
  verdict.textContent = rep.werdykt + (rep.naprawa ? ` Co zrobić: ${rep.naprawa}` : "");
  for (const l of rep.warstwy || []) {
    const li = document.createElement("li");
    li.className = l.ok === true ? "diag-ok" : l.ok === false ? "diag-bad" : "diag-skip";
    const state = l.ok === true ? "OK" : l.ok === false ? "BŁĄD" : "-";
    li.innerHTML = `<span class="diag-state">${state}</span><span class="diag-name">${escapeHtml(l.nazwa)}</span>` +
      `<span class="diag-detail">${escapeHtml(l.szczegoly || "")}${Number.isFinite(Number(l.ms)) && l.ms != null ? ` (${Number(l.ms)} ms)` : ""}</span>` +
      (l.rada && l.ok === false ? `<code class="diag-fix">${escapeHtml(l.rada)}</code>` : "");
    ol.appendChild(li);
  }
}

async function runDiagnosis() {
  const btn = document.getElementById("diagBtn");
  const status = document.getElementById("diagStatus");
  if (!btn) return;
  btn.disabled = true;
  status.textContent = "Sprawdzam warstwa po warstwie (do 40 s)…";
  try {
    const res = await apiFetch("/api/diagnoza");
    const rep = await res.json();
    renderDiagnosis(rep);
    status.textContent = `Gotowe w ${rep.czas_s ?? "?"} s.`;
  } catch (e) {
    status.textContent = "Nie udało się połączyć z GREGAI.";
  } finally {
    btn.disabled = false;
  }
}

async function refresh() {
  // /api/system_info ma WŁASNY try/catch: jego błąd nie ma oznaczać całej
  // strony jako "brak połączenia z GREGAI", gdy ślad decyzji i nauczone wzorce działają.
  try {
    const sysRes = await apiFetch("/api/system_info");
    const sysData = await sysRes.json();
    renderSysInfo(sysData.error ? null : sysData);
    if (!sysData.error) renderLanAccess(sysData.lan);
  } catch (e) {
    renderSysInfo(null);
  }

  // 1.35.0: panele historii (koryto, straż, budżet, sieć, eval, modele). Osobny
  // try/catch: brak jednego z nich nie gasi całego Nadzorcy.
  try {
    const [korytoRes, strazRes, budzetRes, siecRes, evalRes, modelRes] = await Promise.all([
      apiFetch("/api/koryto/historia?limit=20"),
      apiFetch("/api/straz/historia?limit=200"),
      apiFetch("/api/budget/daily"),
      apiFetch("/api/network/devices"),
      apiFetch("/api/eval/history?limit=10"),
      apiFetch("/api/models/log?limit=10"),
    ]);
    const [korytoData, strazNew, budzetData, siecData, evalData, modelData] = await Promise.all([
      korytoRes.json(), strazRes.json(), budzetRes.json(), siecRes.json(), evalRes.json(), modelRes.json(),
    ]);
    if (!korytoData.error) renderKorytoHistory(korytoData);
    if (!strazNew.error) {
      strazData = { wpisy: strazNew.wpisy || [], wyciszone: strazNew.wyciszone || {} };
      renderStrazTimeline();
    }
    if (!budzetData.error) renderBudgetDetails(budzetData);
    if (!siecData.error) renderSiec(siecData);
    if (!evalData.error) renderEval(evalData);
    if (!modelData.error) renderModelLog(modelData);
  } catch (e) { /* panele historii są dodatkiem */ }

  try {
    const [logRes, learnedRes, topicRes, terazRes] = await Promise.all([
      apiFetch("/api/debug/log"),
      apiFetch("/api/debug/learned"),
      apiFetch("/api/debug/topic_words"),
      apiFetch("/api/debug/teraz"),
    ]);
    const logData = await logRes.json();
    const learnedData = await learnedRes.json();
    const topicData = await topicRes.json();
    const terazData = await terazRes.json();
    if (logData.error || learnedData.error || topicData.error) {
      throw new Error(logData.error || learnedData.error || topicData.error);
    }
    renderLog(logData.entries || []);
    renderLearned(learnedData.routes || []);
    renderTopicWords(topicData.topic_words || {});
    // Blok „Teraz” osobno: jego błąd pokazuje własny komunikat w swojej sekcji,
    // nie unieważnia całego odświeżenia (ślad i nauka wyżej są już narysowane).
    renderTeraz(terazData.error ? null : terazData);
    try {
      const lessons = await (await apiFetch("/api/lekcje")).json();
      renderLessons(lessons.lekcje || []);
    } catch (e) { /* lekcje są dodatkiem: ich błąd nie psuje odświeżenia */ }
    document.getElementById("statusDot").classList.remove("stale");
    document.getElementById("lastRefresh").textContent =
      "odświeżono " + new Date().toLocaleTimeString("pl-PL", { hour12: false });
  } catch (e) {
    document.getElementById("statusDot").classList.add("stale");
    // TypeError = fetch nie dotarł do serwera; inne błędy to odpowiedź serwera
    // (np. brak autoryzacji), którą warto zobaczyć zamiast ogólnego "brak połączenia".
    document.getElementById("lastRefresh").textContent =
      e instanceof TypeError || !e.message ? "brak połączenia z GREGAI" : "błąd GREGAI: " + e.message;
  }
}

async function waitForRestart(btn, statusEl) {
  // Serwer zastępuje swój proces (os.execve) ułamek sekundy po
  // odpowiedzi - w tym oknie faktycznie na chwilę traci połączenie,
  // więc odpytujemy /api/status, aż znów odpowie, zamiast zgadywać
  // jeden sztywny czas oczekiwania.
  statusEl.textContent = "restartuję…";
  const deadline = Date.now() + 30000;
  await new Promise((r) => setTimeout(r, 1200));
  while (Date.now() < deadline) {
    try {
      const res = await apiFetch("/api/status");
      if (res.ok) {
        statusEl.textContent = "zrestartowano ✓";
        btn.disabled = false;
        refresh();
        setTimeout(() => { statusEl.textContent = ""; }, 4000);
        return;
      }
    } catch (e) {
      // jeszcze nie wstał, próbuj dalej
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  statusEl.textContent = "nie odpowiada po 30s - sprawdź usługę ręcznie";
  btn.disabled = false;
}

if (document.getElementById("diagBtn")) document.getElementById("diagBtn").addEventListener("click", runDiagnosis);

document.getElementById("restartBtn").addEventListener("click", async () => {
  const btn = document.getElementById("restartBtn");
  const statusEl = document.getElementById("restartStatus");
  if (!confirm("Zrestartować GREGAI teraz? Trwająca rozmowa się przerwie na kilka sekund.")) return;
  btn.disabled = true;
  try {
    const res = await apiFetch("/api/restart", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    let body = null;
    try { body = await res.json(); } catch (e) { /* odpowiedź ucięta przez restart */ }
    if (!res.ok || (body && body.error)) {
      // Serwer odmówił (np. brak autoryzacji): to nie jest restart, nie czekamy na niego.
      statusEl.textContent = "serwer odmówił restartu: " + ((body && body.error) || ("HTTP " + res.status));
      btn.disabled = false;
      return;
    }
  } catch (e) {
    // Oczekiwane: serwer może zamknąć gniazdo w trakcie restartu,
    // zanim fetch zdąży odebrać odpowiedź - to nie jest błąd.
  }
  waitForRestart(btn, statusEl);
});

document.getElementById("lanApplyBtn").addEventListener("click", async () => {
  const checkbox = document.getElementById("lanCheckbox");
  const btn = document.getElementById("lanApplyBtn");
  const statusEl = document.getElementById("lanStatus");
  const desired = checkbox.checked;
  if (_lanServerEnabled !== null && desired === _lanServerEnabled) {
    statusEl.textContent = "już w tym stanie";
    setTimeout(() => { statusEl.textContent = ""; }, 2500);
    return;
  }
  const msg = desired
    ? "Udostępnić GREGAI w sieci lokalnej? Każdy z adresem IP tego komputera i tokenem dostępu (pokazanym po włączeniu) będzie mógł z nim rozmawiać i czytać notatki, z tej samej sieci (np. domowe wifi). Wymaga też osobno przepuszczenia portu w zaporze, jeśli jest aktywna (patrz opis wyżej - GREGAI sam zapory nie dotyka). Zrestartować teraz, żeby to zastosować?"
    : "Wyłączyć dostęp z sieci lokalnej (z powrotem tylko ten komputer)? Zrestartować teraz, żeby to zastosować?";
  if (!confirm(msg)) { checkbox.checked = _lanServerEnabled; return; }
  checkbox.disabled = true;
  btn.disabled = true;
  statusEl.textContent = "zapisuję…";
  try {
    const res = await apiFetch("/api/debug/lan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: desired }),
    });
    const body = await res.json();
    if (!res.ok || body.error) {
      statusEl.textContent = "nie zapisano: " + (body.error || ("HTTP " + res.status));
      checkbox.disabled = false;
      btn.disabled = false;
      checkbox.checked = _lanServerEnabled;
      return;
    }
    renderLanAccess({ enabled: desired, token: body.token });
    checkbox.disabled = false;
  } catch (e) {
    statusEl.textContent = "błąd zapisu: " + (e.message || e);
    checkbox.disabled = false;
    btn.disabled = false;
    checkbox.checked = _lanServerEnabled;
    return;
  }
  try {
    await apiFetch("/api/restart", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (e) {
    // jw. restartBtn: oczekiwane, serwer zamyka gniazdo w trakcie restartu
  }
  waitForRestart(btn, statusEl);
});

document.getElementById("lanTokenShowBtn").addEventListener("click", () => {
  const input = document.getElementById("lanTokenInput");
  const btn = document.getElementById("lanTokenShowBtn");
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  btn.textContent = showing ? "Pokaż" : "Ukryj";
});

document.getElementById("lanTokenCopyBtn").addEventListener("click", async () => {
  const input = document.getElementById("lanTokenInput");
  const btn = document.getElementById("lanTokenCopyBtn");
  if (!input.value) return;
  try {
    await navigator.clipboard.writeText(input.value);
    const old = btn.textContent;
    btn.textContent = "Skopiowano ✓";
    setTimeout(() => { btn.textContent = old; }, 2000);
  } catch (e) {
    input.type = "text";
    input.select();
  }
});

// Co 15 s i tylko przy widocznej karcie: każde odświeżenie pyta WARP,
// Ollamę i system, a na dwóch rdzeniach CPU ma liczyć model, nie panel.
// Od 1.11.0 ten skrypt żyje w jednej aplikacji (index.html, segment Nadzorca)
// i na stronie zapasowej /debug. Odświeża TYLKO, gdy segment jest widoczny
// (body.segment-debug) - żeby na laptopie na baterii nie budzić serwera co 15 s,
// kiedy ktoś rozmawia albo ogląda graf. app.js woła GregaiDebug.show() przy
// wejściu do segmentu, żeby dane były świeże od razu.
function debugVisible() { return document.body.classList.contains("segment-debug"); }

// 1.35.0: kontrolki nowych podsekcji Nadzorcy.
(function initNadzorcaPanele() {
  document.querySelectorAll("[data-straz-poziom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      strazPoziom = btn.dataset.strazPoziom || "";
      document.querySelectorAll("[data-straz-poziom]").forEach((b) => {
        b.setAttribute("aria-pressed", String((b.dataset.strazPoziom || "") === strazPoziom));
      });
      renderStrazTimeline();
    });
  });
  const more = document.getElementById("strazMoreBtn");
  if (more) more.addEventListener("click", () => { strazLimit += 50; renderStrazTimeline(); });

  const scan = document.getElementById("siecSkanBtn");
  if (scan) scan.addEventListener("click", async () => {
    scan.disabled = true;
    scan.textContent = "Skanowanie…";
    const meta = document.getElementById("siecMeta");
    if (meta) meta.textContent = "SKANOWANIE…";
    try {
      await apiFetch("/api/network/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    } catch (e) { /* poniżej i tak odświeżamy stan */ }
    let tries = 0;
    const poll = async () => {
      tries += 1;
      try {
        const data = await (await apiFetch("/api/network/devices")).json();
        if (!data.error) renderSiec(data);
        if (!(data.skan || {}).running || tries >= 24) return;
      } catch (e) { if (tries >= 24) return; }
      setTimeout(poll, 5000);
    };
    setTimeout(poll, 4000);
  });

  const evalBtn = document.getElementById("evalRunBtn");
  if (evalBtn) evalBtn.addEventListener("click", async () => {
    evalBtn.disabled = true;
    evalBtn.textContent = "Liczy…";
    try {
      await apiFetch("/api/eval/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    } catch (e) { /* j.w. */ }
    let tries = 0;
    const poll = async () => {
      tries += 1;
      try {
        const data = await (await apiFetch("/api/eval/history?limit=10")).json();
        if (!data.error) renderEval(data);
        if (!(data.uruchomienie || {}).running || tries >= 100) return;
      } catch (e) { if (tries >= 100) return; }
      setTimeout(poll, 3000);
    };
    setTimeout(poll, 3000);
  });
})();

ensureTokenD();
if (debugVisible()) refresh();
setInterval(() => { if (!document.hidden && debugVisible()) refresh(); }, 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && debugVisible()) refresh(); });
window.GregaiDebug = { show: refresh };

// 1.34.0 PLASTIC CRACK: uptime strony w pasku statusu Nadzorcy (mono, rośnie
// co sekundę). Liczy czas od wczytania panelu - nie budzi serwera.
(function debugUptime() {
  const el = document.getElementById("dbgUptime");
  if (!el) return;
  const started = Date.now();
  const tick = () => {
    const total = Math.max(0, Math.floor((Date.now() - started) / 1000));
    const hh = String(Math.floor(total / 3600)).padStart(2, "0");
    const mm = String(Math.floor(total / 60) % 60).padStart(2, "0");
    const ss = String(total % 60).padStart(2, "0");
    el.textContent = `UPTIME ${hh}:${mm}:${ss}`;
  };
  tick();
  setInterval(tick, 1000);
})();
