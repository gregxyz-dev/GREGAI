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

function renderSysInfo(data) {
  const grid = document.getElementById("sysinfoGrid");
  const empty = document.getElementById("sysinfoEmpty");
  // Gdy odczyt parametrów się nie udał, dziennik zostaje taki, jaki był (nie ma danych, więc nie
  // twierdzimy, że "nic się nie działo").
  if (data && data.sysop) renderSysopLog(data.sysop.recent);
  else if (data) renderSysopLog([]);
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
    // Koryto (1.17.0, agent/koryto.py): jedna kolejność etapów dla całego myślenia.
    ["Kto odpowiada, po kolei (koryto)", data.koryto
      ? escapeHtml(data.koryto.opis || (data.koryto.kolejnosc || []).join(" -> ") || "?")
        + (data.koryto.routing_siecia ? "" : " <span class=\"warn\">(routing lokalnie: KORYTO_ROUTING=0)</span>")
        + (data.koryto.zadania_siecia ? "" : " <span class=\"warn\">(planer zadań lokalnie: KORYTO_ZADANIA=0)</span>")
      : "brak danych"],
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
const DBG_TABS = ["przeglad", "mysli", "nauka", "system"];
function setDebugTab(name) {
  if (!DBG_TABS.includes(name)) name = "przeglad";
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
  let saved = "przeglad";
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
ensureTokenD();
if (debugVisible()) refresh();
setInterval(() => { if (!document.hidden && debugVisible()) refresh(); }, 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && debugVisible()) refresh(); });
window.GregaiDebug = { show: refresh };
