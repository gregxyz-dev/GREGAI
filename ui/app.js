/**
 * app.js: łączy dane z /api/graph z komponentami UI: graf notatek (filtry,
 * wyszukiwanie, edycja, tworzenie i usuwanie węzłów) oraz okno rozmowy z
 * GREGAI (/api/chat).
 */

const TYPE_LABELS_ORDER = [
  "Call", "Note", "Concept", "Project", "Person",
  "Client", "Invoice", "Proposal", "Sop", "Brief", "Campaign", "Routine", "Wiki", "Journal",
  "Wiedza", "Nauka", "Memory",
];

// Typ w plikach (frontmatter `type:`) zostaje po angielsku, to on steruje
// kolorami (--type-call itd.) i logiką filtrów. Tłumaczymy tylko to, co
// widzi użytkownik na ekranie.
const TYPE_LABELS_PL = {
  Call: "Rozmowa",
  Note: "Notatka",
  Concept: "Koncepcja",
  Project: "Projekt",
  Person: "Osoba",
  Client: "Klient",
  Invoice: "Faktura",
  Proposal: "Oferta",
  Sop: "Procedura",
  Brief: "Brief",
  Campaign: "Kampania",
  Routine: "Rutyna",
  Wiki: "Z Wikipedii",
  Journal: "Dziennik",
  Wiedza: "Wiedza",
  Nauka: "Nauka",
  Memory: "Pamięć",
  Task: "Zadanie",
};

// Typ pochodzi z pliku, więc nazwa w rodzaju "constructor" nie może trafić do
// dziedziczonych własności obiektu (stąd hasOwn, nie samo TYPE_LABELS_PL[type]).
function typeLabelPl(type) {
  return Object.hasOwn(TYPE_LABELS_PL, type) ? TYPE_LABELS_PL[type] : type;
}

// Typ spoza znanej listy (własny `type:` w pliku) dostaje kolor zwykłej notatki.
function typeColorVar(type) {
  return TYPE_LABELS_ORDER.includes(type) ? `--type-${type.toLowerCase()}` : "--type-note";
}

/**
 * Obsługa tokenu dostępu (GREGAI_TOKEN): potrzebna tylko gdy serwer
 * działa w trybie sieciowym (GREGAI_LAN=1) i łączysz się z innego
 * urządzenia niż localhost. Z samego serwera (localhost) token nie
 * jest wymagany. Serwer wpuszcza 127.0.0.1 bez pytania.
 *
 * Token trzymany tylko w localStorage TEJ przeglądarki, nigdzie
 * indziej nie jest wysyłany ani zapisywany.
 */
// Polska liczba mnoga (1.19.0, audyt: "1 połączeń", "2 faz", "12 pliki"):
// 1 -> one; 2-4 (poza 12-14) -> few; reszta -> many. Jedno źródło dla
// całego interfejsu (debug.js ma kopię, bo standalone /debug ładuje się bez app.js).
function pluralPl(n, one, few, many) {
  const a = Math.abs(Number(n) || 0);
  if (a === 1) return one;
  const d = a % 10, h = a % 100;
  return d >= 2 && d <= 4 && !(h >= 12 && h <= 14) ? few : many;
}

function getStoredToken() {
  try {
    return localStorage.getItem("gregai_token") || "";
  } catch (e) {
    return "";
  }
}

// Po anulowaniu okienka nie pytamy ponownie do odświeżenia strony: odpytywanie co
// 30 s wyświetlałoby je w kółko.
let tokenPromptDeclined = false;

function ensureToken() {
  const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if (isLocal) return;
  if (getStoredToken() || tokenPromptDeclined) return;
  const token = prompt("To urządzenie łączy się z GREGAI przez sieć, podaj token dostępu (ten sam co GREGAI_TOKEN w .env na serwerze):");
  if (token) {
    try {
      localStorage.setItem("gregai_token", token.trim());
    } catch (e) {
      /* prywatne okno / zablokowany storage, token poproszony ponownie następnym razem */
    }
  } else {
    tokenPromptDeclined = true;
  }
}

// 1.18.0 (audyt interfejsu): licznik kolejnych nieudanych połączeń z WŁASNYM
// serwerem GREGAI (wyjątek z fetch - serwer nie odpowiedział wcale; kod HTTP
// to nadal odpowiedź). Znacznik modelu pokazuje go, żeby "Brak połączenia" po
// jednym zgubionym odczycie odróżniał się od serwera, który leży od minut.
let serverFailStreak = 0;

async function gregaiFetch(url, options = {}, retried = false) {
  const token = getStoredToken();
  const headers = Object.assign({}, options.headers || {});
  if (token) headers["X-Gregai-Token"] = token;
  let res;
  try {
    res = await fetch(url, Object.assign({}, options, { headers }));
  } catch (e) {
    serverFailStreak += 1;
    throw e;
  }
  serverFailStreak = 0;
  if (res.status === 403) {
    // Token zły/wygasł: wyczyść, zapytaj o nowy (tylko przy połączeniu spoza
    // localhosta) i ponów zapytanie JEDEN raz: odrzucone żądanie nie zostało
    // przetworzone, więc ponowienie niczego nie dubluje. Tylko przy błędzie
    // autoryzacji - inne 403 (np. ochrona przed obcymi stronami w
    // agent/main.py) nie mają nic wspólnego z tokenem.
    try {
      const body = await res.clone().json();
      if (body && body.error === "Brak autoryzacji") {
        localStorage.removeItem("gregai_token");
        if (!retried) {
          ensureToken();
          if (getStoredToken()) return gregaiFetch(url, options, true);
        }
      }
    } catch (e) {}
  }
  return res;
}

// Jeden pasek stanu na górze strony dla wszystkich komunikatów. Zwykły
// komunikat znika po `ms`; błąd ładowania (ms = 0) zostaje do następnego
// udanego odświeżenia. Zegar jest wspólny, więc stary komunikat nie zgasi nowego.
let bannerTimer = null;
function showBanner(text, { info = false, ms = 0 } = {}) {
  const banner = document.getElementById("status-banner");
  clearTimeout(bannerTimer);
  banner.textContent = text;
  banner.classList.toggle("info", info);
  banner.classList.add("visible");
  if (ms > 0) bannerTimer = setTimeout(() => banner.classList.remove("visible"), ms);
}

// 1.32.10: baner z przyciskiem "Cofnij" (przywraca notatkę z kosza).
function showUndoBanner(text, kosz) {
  const banner = document.getElementById("status-banner");
  showBanner(text, { info: true, ms: 15000 });
  if (!kosz) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "banner-undo";
  btn.textContent = "Cofnij";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const res = await gregaiFetch("/api/note/przywroc", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kosz }),
      });
      const d = await res.json();
      if (d.error) { showBanner("Nie udało się przywrócić: " + d.error, { ms: 8000 }); return; }
      await refreshGraphData();
      showBanner("Przywrócono notatkę.", { info: true, ms: 4000 });
    } catch (e) {
      showBanner("Nie udało się przywrócić: " + (e && e.message ? e.message : "błąd"), { ms: 8000 });
    }
  });
  banner.appendChild(document.createTextNode(" "));
  banner.appendChild(btn);
}

function hideBanner() {
  clearTimeout(bannerTimer);
  document.getElementById("status-banner").classList.remove("visible");
}

// Pliki pominięte przy indeksowaniu (za duże, dowiązania poza folderem) i błędy
// odczytu: bez tego notatka "znika" z grafu bez słowa wyjaśnienia.
function reportGraphProblems() {
  const errors = Array.isArray(graphData.errors) ? graphData.errors.length : 0;
  const skipped = Number(graphData.skipped) || 0;
  if (!errors && !skipped) return;
  const parts = [];
  if (skipped) parts.push(`pominięto pliki: ${skipped} (powyżej 2 MB, dowiązania poza folderem albo nietypowe nazwy)`);
  if (errors) parts.push(`błędy odczytu: ${errors}`);
  showBanner("Uwaga: " + parts.join("; "), { info: true, ms: 10000 });
}

function populateLinkPicker(selectId, excludeId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const sorted = [...graphData.nodes].sort((a, b) => a.title.localeCompare(b.title, "pl"));
  select.innerHTML = sorted
    // Tytuł z [ ] | # nie da się zapisać jako [[powiązanie]] (parser w
    // agent/vault.py czyta | i # jako alias i nagłówek), więc go tu nie ma.
    .filter((n) => n.id !== excludeId && n.title.length <= 200 && !/[\[\]|#]/.test(n.title))
    .map((n) => `<option value="${escapeHtml(n.title)}">${escapeHtml(n.title)} (${escapeHtml(typeLabelPl(n.type))})</option>`)
    .join("");
}

function insertLinkAtCursor(textareaId, title) {
  const el = document.getElementById(textareaId);
  const insertText = `[[${title}]]`;
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, start) + insertText + el.value.slice(end);
  el.focus();
  const cursorPos = start + insertText.length;
  el.setSelectionRange(cursorPos, cursorPos);
  // Zmiana wartości z kodu nie wywołuje zdarzenia "input": bez tego wstawione
  // powiązanie nie liczyłoby się jako zmiana i zapis mówiłby "Bez zmian."
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

let graph;
let graphData = { nodes: [], edges: [] };
let graphRetryTimer = null;

async function loadGraph() {
  let loaded = false;
  try {
    const res = await gregaiFetch("/api/graph");
    if (!res.ok) throw new Error(await httpErrorText(res));
    graphData = await res.json();
    hideBanner();
    loaded = true;
  } catch (err) {
    showBanner(`Błąd ładowania indeksu: ${err.message}`);
    graphData = { nodes: [], edges: [] };
    // Serwer mógł się właśnie restartować: spróbuj ponownie, aż wstanie. Jeden wspólny
    // zegar z refreshGraphData: gdy graf zdąży wstać inną drogą (powrót do karty), ponowne
    // pełne ładowanie zniszczyłoby układ, widok i zaznaczenie.
    clearTimeout(graphRetryTimer);
    graphRetryTimer = setTimeout(() => (graph ? refreshGraphData() : loadGraph()), 5000);
  }


  if (!graph) {
    const canvas = document.getElementById("graph-canvas");
    graph = new Graph(canvas, {
      onSelect: onNodeSelect,
      canSelect: canChangeSelection,
      onTypesChanged: populateFilterList,
      onInfo: (text) => showBanner(text, { info: true, ms: 3000 }),
    });
    graph.loadDataWhenVisible(graphData.nodes, graphData.edges);
    graph.setAutoOrbit(document.body.classList.contains("segment-nodes") && document.visibilityState === "visible");
    startRenderLoop(graph);
  } else if (loaded) {
    // Nieudane ładowanie przy istniejącym grafie nie zastępuje go pustym.
    graph.loadDataWhenVisible(graphData.nodes, graphData.edges);
  }

  populateHubList();
  populateFilterList();
  populateProjectList();
  if (loaded) {
    restoreSavedProject();
    reportGraphProblems();
  }
}

// 1.32.2: otwarty projekt po odświeżeniu - raz, przy pierwszym udanym wczytaniu grafu
// (przegląd poprawek: dawniej dopiero przy późniejszym odświeżeniu, które nagle
// przełączało rozmowę).
function restoreSavedProject() {
  if (projectRestored || activeProject) { projectRestored = true; return; }
  projectRestored = true;
  let saved = null;
  try { saved = localStorage.getItem("gregai_projekt"); } catch (e) { saved = null; }
  const node = saved && graphData.nodes.find((n) => n.id === saved && n.type === "Project");
  if (node) setActiveProject({ id: node.id, title: node.title || node.id });
}

// "HTTP 403: <komunikat serwera>" zamiast samego kodu (np. adres 0.0.0.0 daje
// odmowę Host, a bez treści błędu nie widać dlaczego).
async function httpErrorText(res) {
  let detail = "";
  try {
    const body = await res.json();
    if (body && body.error) detail = `: ${body.error}`;
  } catch (e) { /* odpowiedź bez JSON-a */ }
  return `HTTP ${res.status}${detail}`;
}

let lastGraphRefresh = Date.now();

// Odświeża dane na JUŻ ISTNIEJĄCYM obiekcie grafu (po edycji notatki lub
// zapisie z czatu): nie tworzy nowego Graph ani nowej pętli renderowania, a
// {keep: true} zachowuje pozycje węzłów, przybliżenie, zaznaczenie i filtry.
async function refreshGraphData() {
  clearTimeout(graphRetryTimer);
  try {
    const res = await gregaiFetch("/api/graph");
    if (!res.ok) throw new Error(await httpErrorText(res));
    graphData = await res.json();
    lastGraphRefresh = Date.now();
    hideBanner();
  } catch (err) {
    showBanner(`Błąd odświeżania grafu: ${err.message}`);
    // Jak przy pierwszym ładowaniu: serwer mógł się restartować, ponawiamy, aż odpowie
    // (inaczej baner błędu zostałby po powrocie serwera do czasu kolejnej akcji).
    graphRetryTimer = setTimeout(refreshGraphData, 5000);
    return;
  }
  graph.loadDataWhenVisible(graphData.nodes, graphData.edges, { keep: true });
  populateHubList();
  populateFilterList();
  // Projekt przypisany do aktywnej rozmowy mógł właśnie zniknąć (usunięty węzeł,
  // zmieniony typ): rozmowa nie może dalej udawać, że jest przy nim przypisana.
  if (activeProject && !graphData.nodes.some((n) => n.id === activeProject.id && n.type === "Project")) {
    showBanner(`Projekt „${activeProject.title}” nie jest już węzłem typu Project - wracam do ogólnej rozmowy.`, { info: true, ms: 7000 });
    setActiveProject(null);
  } else {
    populateProjectList();
  }
}
let projectRestored = false;

// Jedna lista rankingu hubów, renderowana w dwóch miejscach: pełna w panelu
// Węzłów (klik = samo wycentrowanie), skrócona w szynie Rozmowy (klik =
// najpierw przejście do segmentu Węzły, dopiero potem wycentrowanie - w
// szynie graf jeszcze nie jest widoczny). Rail to podkategoria, nie powiela
// zachowania panelu, tylko do niego prowadzi.
function populateHubList() {
  const degrees = new Map();
  for (const e of graphData.edges) {
    degrees.set(e.source, (degrees.get(e.source) || 0) + 1);
    degrees.set(e.target, (degrees.get(e.target) || 0) + 1);
  }
  const ranked = [...graphData.nodes]
    .map((n) => ({ ...n, degree: degrees.get(n.id) || 0 }))
    .sort((a, b) => b.degree - a.degree)
    .slice(0, 10);

  renderHubListInto(document.getElementById("hub-list"), ranked, (id) => graph.focusNode(id));
}

function renderHubListInto(list, ranked, onActivate) {
  if (!list) return;
  list.innerHTML = "";
  for (const n of ranked) {
    const li = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = `var(${typeColorVar(n.type)})`;
    const name = document.createElement("span");
    name.className = "hub-name";
    name.textContent = n.title;
    name.title = n.title; // ucięta nazwa ma pełną w podpowiedzi
    const count = document.createElement("span");
    count.className = "hub-count";
    count.textContent = n.degree;
    li.append(swatch, name, count);
    li.addEventListener("click", () => onActivate(n.id));
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.addEventListener("keydown", onActivateKey(() => onActivate(n.id)));
    list.appendChild(li);
  }
}

// --- Szyna "Projekty": notatki typu Project (ui/app.js TYPE_LABELS_ORDER,
// agent/vault.py PROJECT_TYPE) jako osobne, WZAJEMNIE ODIZOLOWANE wątki
// rozmowy (patrz setActiveProject/conversations niżej) - "Ogólna rozmowa"
// to wątek nieprzypisany do żadnego projektu, dokładnie taki jak dotąd. ---
function populateProjectList() {
  const list = document.getElementById("project-list");
  if (!list) return;
  const projects = graphData.nodes
    .filter((n) => n.type === "Project")
    .sort((a, b) => a.title.localeCompare(b.title, "pl"));
  dropConversationsOfMissingProjects();
  // 1.19.0 (przegląd): lista jest budowana od nowa przy każdej zmianie stanu
  // (kropki odpowiedzi) - fokus klawiatury wraca na ten sam przycisk tej samej rozmowy.
  const ae = document.activeElement;
  let focusKey = null, focusClass = null;
  if (ae && list.contains(ae)) {
    const li = ae.closest("li");
    focusKey = li ? li.dataset.key : null;
    focusClass = ["project-name", "project-jump", "project-trash"].find((c) => ae.classList.contains(c)) || null;
  }
  list.innerHTML = "";

  const addItem = (label, project) => {
    const li = document.createElement("li");
    const isActive = project ? activeProject && activeProject.id === project.id : !activeProject;
    li.className = "project-item" + (isActive ? " active" : "");
    li.dataset.key = conversationKey(project);
    // Kropka koloru: ta sama konwencja co w Top hubach/Filtrach (hub-list/
    // filter-list) - "Ogólna rozmowa" nie jest projektem, więc dostaje
    // neutralny, przygaszony znacznik, nie kolor typu Project z grafu.
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = project ? `var(${typeColorVar("Project")})` : "var(--text-dim)";
    // 1.19.0 (dostępność): nazwa to prawdziwy przycisk - dawniej cały wiersz
    // miał role="button" i zawierał w sobie dwa inne przyciski.
    const name = document.createElement("button");
    name.type = "button";
    name.className = "project-name";
    name.textContent = label;
    name.setAttribute("aria-pressed", String(isActive));
    li.append(swatch, name);
    // Kropka stanu (1.19.0): trwa odpowiedź albo czeka nieprzeczytana.
    const conv = conversations.get(conversationKey(project));
    if (conv && (conv.run || conv.unread)) {
      const dot = document.createElement("span");
      dot.className = "project-state " + (conv.run ? "busy" : "unread");
      const what = conv.run ? "odpowiedź w toku" : "nowa odpowiedź";
      dot.title = what;
      dot.setAttribute("role", "img");
      dot.setAttribute("aria-label", what);
      li.appendChild(dot);
    }
    // Projekt w Rozmowie i jego węzeł w Węzłach to DOKŁADNIE ten sam punkt
    // (ten sam Note/graf, patrz agent/vault.py PROJECT_TYPE) - ta ikona jest
    // widocznym rozgałęzieniem między tymi dwoma widokami tej samej rzeczy,
    // nie osobnym skrótem. "Ogólna rozmowa" nie ma swojego węzła, więc jej
    // nie dostaje.
    if (project) {
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "project-jump";
      jump.title = `Zobacz „${label}” w Węzłach`;
      jump.setAttribute("aria-label", `Zobacz „${label}” w Węzłach`);
      jump.innerHTML = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="4" cy="4" r="1.6" fill="currentColor"/><circle cx="12" cy="4" r="1.6" fill="currentColor"/><circle cx="8" cy="11.6" r="1.6" fill="currentColor"/><path d="M5.3 4.9L7 9.8M10.7 4.9L9 9.8M5.7 4L10.3 4" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>';
      jump.addEventListener("click", (e) => {
        e.stopPropagation();
        navigateToNodesSegment();
        graph.focusNode(project.id);
      });
      li.appendChild(jump);
    }
    const trash = document.createElement("button");
    trash.type = "button";
    trash.className = "project-trash";
    const trashLabel = project ? `Usuń rozmowę „${label}” i jej pliki` : "Wyczyść Ogólną rozmowę i jej pliki";
    trash.title = trashLabel;
    trash.setAttribute("aria-label", trashLabel);
    trash.innerHTML = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.2a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.2M7 7v4M9 7v4" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    trash.addEventListener("click", (e) => { e.stopPropagation(); deleteConversation(project); });
    li.appendChild(trash);
    li.title = label;
    // 1.19.0: przełączanie w trakcie odpowiedzi jest dozwolone - odpowiedź jest
    // przypięta do swojej rozmowy (sendChatMessage), nie do otwartej.
    const choose = () => {
      if (!isActive) setActiveProject(project);
    };
    li.addEventListener("click", choose);
    list.appendChild(li);
  };

  addItem("Ogólna rozmowa", null);
  for (const p of projects) addItem(p.title, { id: p.id, title: p.title });
  if (focusKey && focusClass) {
    const li = [...list.children].find((x) => x.dataset.key === focusKey);
    const el = li && li.querySelector("." + focusClass);
    if (el) el.focus();
  }

  // Wybór rozmowy na telefonie (1.19.0): ta sama lista jako <select>.
  const picker = document.getElementById("project-picker");
  if (picker) {
    const mark = (project) => {
      const c = conversations.get(conversationKey(project));
      // Krótki dopisek - długi ucinał nazwę rozmowy na telefonie.
      return c && c.run ? " (…)" : c && c.unread ? " (nowa)" : "";
    };
    const opts = [{ value: "", label: "Ogólna rozmowa" + mark(null) }]
      .concat(projects.map((p) => ({ value: p.id, label: p.title + mark({ id: p.id }) })));
    picker.innerHTML = opts.map((o) => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join("");
    picker.value = activeProject ? activeProject.id : "";
    if (!picker.dataset.wired) {
      picker.dataset.wired = "1";
      picker.addEventListener("change", () => {
        const id = picker.value;
        const node = id ? graphData.nodes.find((x) => x.id === id) : null;
        setActiveProject(node ? { id: node.id, title: node.title } : null);
      });
    }
  }
}

function populateFilterList() {
  const list = document.getElementById("filter-list");
  list.innerHTML = "";
  const counts = new Map();
  for (const n of graphData.nodes) counts.set(n.type, (counts.get(n.type) || 0) + 1);

  const unknown = [...counts.keys()].filter((t) => !TYPE_LABELS_ORDER.includes(t)).sort();
  for (const type of [...TYPE_LABELS_ORDER, ...unknown]) {
    if (!counts.get(type)) continue;
    const li = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = `var(${typeColorVar(type)})`;
    const name = document.createElement("span");
    name.className = "filter-name";
    name.textContent = typeLabelPl(type);
    const count = document.createElement("span");
    count.className = "filter-count";
    count.textContent = counts.get(type);
    li.append(swatch, name, count);
    li.classList.toggle("disabled", !graph.activeTypes.has(type));
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.setAttribute("aria-pressed", String(graph.activeTypes.has(type)));
    li.title = "Pokaż/ukryj węzły tego typu";
    const toggle = () => {
      const active = graph.activeTypes.has(type);
      graph.setTypeActive(type, !active);
      li.classList.toggle("disabled", active);
      li.setAttribute("aria-pressed", String(!active));
    };
    li.addEventListener("click", toggle);
    li.addEventListener("keydown", onActivateKey(toggle));
    list.appendChild(li);
  }
}

// Enter albo spacja uruchamiają element, który działa jak przycisk.
function onActivateKey(fn) {
  return (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };
}

let selectedNodeId = null;

// Edycja notatki w inspektorze. `editDirty` = użytkownik coś zmienił od
// ostatniego zapisu; zmiana zaznaczenia (klik w inny węzeł, huby, wyszukiwarka)
// pyta wtedy o zgodę, zamiast po cichu wyrzucić wpisany tekst.
let editing = false;
let editDirty = false;

function canChangeSelection(node) {
  // Także ponowne zaznaczenie TEJ SAMEJ notatki odbudowuje inspektor i gubi
  // wpisany tekst, więc pyta tak samo (zapis i Anuluj zerują editDirty wcześniej).
  if (!editing || !editDirty) return true;
  return window.confirm("Masz niezapisane zmiany w notatce. Przejść dalej bez zapisu?");
}

window.addEventListener("beforeunload", (e) => {
  if (editing && editDirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

const READONLY_NOTES_PL = {
  pdf: "Źródło PDF: tylko do odczytu (zmieniasz je w menedżerze plików).",
  kodowanie: "Plik nie jest w UTF-8 (np. Windows-1250), więc jest tylko do odczytu: zapis z interfejsu zgubiłby polskie znaki. Zapisz go w UTF-8 w edytorze tekstu.",
};

// --- Powiązania jako osobna sekcja (1.14.0) ---
// Dane zostają zwykłym Markdownem ([[powiązanie]] w treści), ale interfejs nie
// każe już ich czytać ani pisać "w tekście": podgląd pokazuje powiązania w
// osobnej karcie (w dwóch kierunkach), a edytor ma osobną sekcję z kafelkami.
// Nowe powiązania dodane z interfejsu trafiają do jednej końcowej linii
// "Powiązania: [[A]], [[B]]", którą edytor chowa przed polem Treść i składa
// z powrotem przy zapisie - treść i powiązania nigdy nie mieszają się w polu.
const LINKS_LINE_RE = /(?:^|\n)[ \t]*Powiązania:[ \t]*((?:\[\[[^\[\]\n]+\]\](?:[ \t]*,[ \t]*|[ \t]+)?)+)[ \t]*$/;
const WIKILINK_G = /\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]/g;

function splitLinksLine(body) {
  const text = String(body || "").replace(/\s+$/, "");
  const m = text.match(LINKS_LINE_RE);
  if (!m) return { content: text, links: [] };
  const links = [...m[1].matchAll(WIKILINK_G)].map((x) => x[1].trim());
  return { content: text.slice(0, m.index).replace(/\s+$/, ""), links: [...new Set(links)] };
}

function composeBody(content, links) {
  const c = String(content || "").trim();
  if (!links.length) return c;
  return `${c}${c ? "\n\n" : ""}Powiązania: ${links.map((t) => `[[${t}]]`).join(", ")}`;
}

// CSP (style-src 'self') nie dopuszcza atrybutu style="" w znaczniku wstawianym
// przez innerHTML, więc kolor kropki idzie przez data-cv i jest ustawiany z JS.
function paintColors(root) {
  root.querySelectorAll("[data-cv]").forEach((el) => { el.style.background = `var(${el.dataset.cv})`; });
}

function nodeByTitle(title) {
  const t = String(title).trim().toLowerCase();
  return graphData.nodes.find((n) => n.title.toLowerCase() === t) || null;
}

function linkChipHTML(node, extra = "") {
  return `<button type="button" class="link-chip" data-node-id="${escapeHtml(node.id)}" title="${escapeHtml(typeLabelPl(node.type))}: ${escapeHtml(node.title)}">` +
    `<span class="link-chip-dot" data-cv="${typeColorVar(node.type)}"></span><span class="link-chip-name">${escapeHtml(node.title)}</span>${extra}</button>`;
}

function renderLinksCard(node) {
  const byId = new Map(graphData.nodes.map((n) => [n.id, n]));
  const out = (node.links || []).map((id) => byId.get(id)).filter(Boolean)
    .sort((a, b) => a.title.localeCompare(b.title, "pl"));
  const inc = graphData.nodes.filter((n) => n.id !== node.id && Array.isArray(n.links) && n.links.includes(node.id))
    .sort((a, b) => a.title.localeCompare(b.title, "pl"));
  const group = (label, hint, list) =>
    `<div class="link-group"><div class="link-group-head"><span>${label}</span><span class="link-count">${list.length}</span></div>` +
    (list.length ? `<div class="link-chips">${list.map((n) => linkChipHTML(n)).join("")}</div>` : `<p class="link-empty">${hint}</p>`) + `</div>`;
  return `<section class="insp-card insp-links" aria-label="Powiązania">
    <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">🔗</span>Powiązania<span class="link-count">${out.length + inc.length}</span></h4>
    ${group("Prowadzi do", "Ta notatka na nic nie wskazuje.", out)}
    ${group("Wskazują na nią", "Żadna notatka jeszcze na nią nie wskazuje.", inc)}
  </section>`;
}

function onNodeSelect(node) {
  const body = document.getElementById("inspector-body");
  editing = false;
  editDirty = false;
  deleteConfirmId = null; // potwierdzenie "Na pewno?" dotyczyło poprzedniej notatki
  selectedNodeId = node ? node.id : null;
  if (!node) {
    body.innerHTML = `<div class="insp-empty"><span class="insp-empty-ico" aria-hidden="true">👆</span><p>Kliknij węzeł w grafie, żeby zobaczyć jego treść i powiązania.</p><p class="insp-empty-sub">Shift-klik na drugim węźle wyznacza ścieżkę między nimi.</p></div>`;
    return;
  }
  const excerpt = String(node.excerpt || "").replace(/\s*Powiązania:.*$/, "").trim();
  body.innerHTML = `
    <header class="insp-head">
      <span class="insp-dot" data-cv="${typeColorVar(node.type)}"></span>
      <div class="insp-head-text"><div class="note-title">${escapeHtml(node.title)}</div><div class="note-type">${escapeHtml(typeLabelPl(node.type))}</div></div>
    </header>
    <section class="insp-card" aria-label="Treść">
      <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">📝</span>Treść</h4>
      <p class="insp-text">${escapeHtml(excerpt || "Brak podglądu treści.")}</p>
    </section>
    ${renderLinksCard(node)}
    <section class="insp-card insp-actions" aria-label="Działania">
      <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">⚙️</span>Działania</h4>
      ${node.readonly
        ? `<p class="note-edit-status">${escapeHtml(READONLY_NOTES_PL[node.readonly_reason] || READONLY_NOTES_PL.pdf)}</p>`
        : `<div class="inspector-btn-row">
        <button class="inspector-btn" id="btn-edit-note">Edytuj</button>
        <button class="inspector-btn danger" id="btn-delete-note">Usuń</button>
      </div>`}
    </section>
  `;
  paintColors(body);
  body.querySelectorAll(".link-chip").forEach((chip) => chip.addEventListener("click", () => {
    if (canChangeSelection(null)) graph.focusNode(chip.dataset.nodeId);
  }));
  if (node.readonly) return;
  document.getElementById("btn-edit-note").addEventListener("click", () => startNoteEdit(node.id));
  document.getElementById("btn-delete-note").addEventListener("click", (e) => handleDeleteClick(e.currentTarget, node.id));
}

let deleteConfirmId = null;

function handleDeleteClick(btn, id) {
  if (deleteConfirmId !== id) {
    // Pierwsze kliknięcie: proś o potwierdzenie zamiast kasować od razu.
    deleteConfirmId = id;
    btn.textContent = "Na pewno? Usuń (do kosza)";
    setTimeout(() => {
      if (deleteConfirmId === id) {
        deleteConfirmId = null;
        if (document.body.contains(btn)) btn.textContent = "Usuń";
      }
    }, 4000);
    return;
  }
  deleteConfirmId = null;
  deleteNote(id);
}

async function deleteNote(id) {
  const body = document.getElementById("inspector-body");
  try {
    const res = await gregaiFetch("/api/note/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // 1.27.0 (audyt): tytuł, który WIDZISZ - serwer odmówi, gdy pod tym id jest już
      // inna notatka (nieaktualna karta albo telefon po zmianach w grafie).
      body: JSON.stringify({ id, title: ((graphData.nodes || []).find((n) => n.id === id) || {}).title }),
    });
    const data = await res.json();
    if (data.error) {
      body.innerHTML = `<p class="text-danger">Błąd usuwania: ${escapeHtml(data.error)}</p>`;
      return;
    }
    editing = false;
    editDirty = false;
    await refreshGraphData();
    onNodeSelect(null);
    // 1.32.10: notatka idzie do kosza (data/kosz) - baner z "Cofnij" przez 15 s.
    const plural = (n, one, few, many) => n === 1 ? one : (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) ? few : many;
    let msg = "Notatka przeniesiona do kosza.";
    if (data.dangling_links) msg += ` ${data.dangling_links} ${plural(data.dangling_links, "notatka ma", "notatki mają", "notatek ma")} teraz link bez celu.`;
    if (data.repointed_links) msg += ` ${data.repointed_links} ${plural(data.repointed_links, "link wskazuje", "linki wskazują", "linków wskazuje")} teraz inną notatkę o podobnym tytule.`;
    showUndoBanner(msg, data.kosz);
  } catch (err) {
    body.innerHTML = `<p class="text-danger">Błąd usuwania: ${escapeHtml(err.message)}</p>`;
  }
}

let editLinks = []; // powiązania z końcowej linii "Powiązania:" (osobno od pola Treść)

function renderEditLinks(selfId) {
  const box = document.getElementById("edit-links-chips");
  if (!box) return;
  const content = document.getElementById("edit-body").value;
  const inline = [...new Set([...content.matchAll(WIKILINK_G)].map((m) => m[1].trim()))].filter((t) => !editLinks.includes(t));
  const chip = (title, kind) => {
    const node = nodeByTitle(title);
    const cv = node ? typeColorVar(node.type) : "--text-dim";
    const tip = kind === "inline" ? "powiązanie w treści - krzyżyk zdejmuje link, słowo zostaje" : "powiązanie";
    return `<span class="link-chip editable${node ? "" : " missing"}" title="${escapeHtml(tip)}${node ? "" : " (nie ma takiej notatki)"}">` +
      `<span class="link-chip-dot" data-cv="${cv}"></span><span class="link-chip-name">${escapeHtml(title)}</span>` +
      `<button type="button" class="link-chip-x" data-kind="${kind}" data-title="${escapeHtml(title)}" aria-label="Usuń powiązanie ${escapeHtml(title)}">×</button></span>`;
  };
  const all = [...editLinks.map((t) => chip(t, "line")), ...inline.map((t) => chip(t, "inline"))];
  box.innerHTML = all.length ? all.join("") : `<p class="link-empty">Brak powiązań. Dodaj pierwsze poniżej.</p>`;
  paintColors(box);
  const cnt = document.getElementById("edit-links-count");
  if (cnt) cnt.textContent = String(editLinks.length + inline.length);
  box.querySelectorAll(".link-chip-x").forEach((x) => x.addEventListener("click", () => {
    const title = x.dataset.title;
    if (x.dataset.kind === "line") {
      editLinks = editLinks.filter((t) => t !== title);
    } else {
      const ta = document.getElementById("edit-body");
      const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      ta.value = ta.value.replace(new RegExp(`\\[\\[\\s*${esc}\\s*(?:#[^\\[\\]|]*)?(?:\\|([^\\[\\]]*))?\\]\\]`, "g"), (_m, alias) => alias || title);
    }
    editDirty = true;
    renderEditLinks(selfId);
  }));
}

async function startNoteEdit(id) {
  const body = document.getElementById("inspector-body");
  body.innerHTML = `<p>Wczytuję…</p>`;
  try {
    const res = await gregaiFetch(`/api/note?id=${encodeURIComponent(id)}`);
    const data = await res.json();
    // W trakcie wczytywania zaznaczono inną notatkę: nie rysujemy cudzego formularza.
    if (selectedNodeId !== id) return;
    if (data.error) {
      body.innerHTML = `<p class="text-danger">${escapeHtml(data.error)}</p>`;
      return;
    }
    if (data.readonly) {
      // Plik zmienił się na dysku w międzyczasie (np. inne kodowanie): bez edycji.
      body.innerHTML = `<p class="note-edit-status">${escapeHtml(READONLY_NOTES_PL[data.readonly_reason] || READONLY_NOTES_PL.pdf)}</p>`;
      return;
    }
    const baseVersion = data.version || null;

    let typeOptions = "";
    // Własny typ z pliku (spoza listy) zostaje wybrany, inaczej zapis po cichu
    // zmieniłby go na pierwszy z listy.
    const editTypes = TYPE_LABELS_ORDER.includes(data.type) ? TYPE_LABELS_ORDER : [...TYPE_LABELS_ORDER, data.type];
    for (const t of editTypes) {
      const selected = t === data.type ? " selected" : "";
      typeOptions += `<option value="${escapeHtml(t)}"${selected}>${escapeHtml(typeLabelPl(t))}</option>`;
    }

    const split = splitLinksLine(data.body);
    editLinks = split.links;
    body.innerHTML = `
      <div id="edit-form-fields">
        <section class="insp-card" aria-label="Nazwa i typ">
          <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">🏷️</span>Nazwa i typ</h4>
          <label class="modal-label">Nazwa
            <input id="edit-title" type="text" class="modal-input" value="${escapeHtml(data.title)}" />
          </label>
          <label class="modal-label">Typ
            <select id="edit-type" class="modal-input">${typeOptions}</select>
          </label>
        </section>
        <section class="insp-card" aria-label="Treść">
          <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">📝</span>Treść</h4>
          <textarea id="edit-body" class="note-edit-area" aria-label="Treść notatki">${escapeHtml(split.content)}</textarea>
        </section>
        <section class="insp-card insp-links" aria-label="Powiązania">
          <h4 class="insp-h"><span class="insp-ico" aria-hidden="true">🔗</span>Powiązania<span class="link-count" id="edit-links-count">0</span></h4>
          <div id="edit-links-chips" class="link-chips"></div>
          <p class="link-help">Wybierz notatkę i dodaj ją jako powiązanie - nie musisz nic wpisywać w treści. Krzyżyk usuwa powiązanie (słowo w treści zostaje).</p>
          <div class="link-picker-row">
            <select id="edit-link-picker" class="modal-input" aria-label="Notatka do powiązania"></select>
            <button type="button" class="inspector-btn secondary" id="btn-insert-edit-link">Dodaj</button>
          </div>
        </section>
      </div>
      <div id="edit-raw-field" class="hidden">
        <label class="modal-label">Surowy Markdown (całość pliku)
          <textarea id="edit-raw" class="note-edit-area">${escapeHtml(data.text)}</textarea>
        </label>
      </div>
      <p id="edit-layout-hint" class="note-edit-status hidden">Ta notatka ma własny układ (np. frontmatter YAML), więc edytujesz ją jako surowy Markdown: nic w niej nie jest przepisywane po cichu.</p>
      <button class="inspector-btn secondary" id="btn-toggle-edit-raw" type="button">Edytuj jako surowy Markdown</button>
      <div class="inspector-btn-row">
        <button class="inspector-btn" id="btn-save-note">Zapisz</button>
        <button class="inspector-btn secondary" id="btn-cancel-note">Anuluj</button>
      </div>
      <p id="note-edit-status" class="note-edit-status"></p>
    `;
    editing = true;
    editDirty = false;
    if (!fitsStructuredEditor(data.text)) {
      showEditMode(true); // surowy tekst od razu, bez składania go z pól
      document.getElementById("btn-toggle-edit-raw").style.display = "none";
      document.getElementById("edit-layout-hint").style.display = "block";
    }
    body.querySelectorAll("input, textarea, select").forEach((el) => {
      if (el.id === "edit-link-picker") return; // wybór powiązania do wstawienia to jeszcze nie zmiana notatki
      el.addEventListener("input", () => { editDirty = true; });
    });
    document.getElementById("btn-cancel-note").addEventListener("click", () => {
      editDirty = false; // Anuluj to świadoma rezygnacja ze zmian
      graph.focusNode(id);
      const editBtn = document.getElementById("btn-edit-note");
      if (editBtn) editBtn.focus();
    });
    document.getElementById("btn-save-note").addEventListener("click", () => saveNoteEdit(id, baseVersion));
    document.getElementById("btn-toggle-edit-raw").addEventListener("click", (e) => {
      const rawMode = e.currentTarget.dataset.rawMode === "1";
      setEditRawMode(!rawMode, data);
    });
    populateLinkPicker("edit-link-picker", id);
    document.getElementById("btn-insert-edit-link").addEventListener("click", () => {
      const select = document.getElementById("edit-link-picker");
      const title = select.value;
      if (!title || editLinks.includes(title)) return;
      editLinks.push(title);
      editDirty = true;
      renderEditLinks(id);
    });
    document.getElementById("edit-body").addEventListener("input", () => renderEditLinks(id));
    renderEditLinks(id);
    // Przebudowa inspektora zabrała fokus (został na <body>): oddajemy go pierwszemu polu.
    const firstField = document.getElementById(document.getElementById("btn-toggle-edit-raw").dataset.rawMode === "1" ? "edit-raw" : "edit-title");
    if (firstField) firstField.focus();
  } catch (err) {
    // Błąd spóźnionej odpowiedzi nie może zamazać inspektora innej, już zaznaczonej notatki.
    if (selectedNodeId !== id) return;
    body.innerHTML = `<p class="text-danger">Błąd wczytywania: ${escapeHtml(err.message)}</p>`;
  }
}

// Ten sam tekst z kodem (blok ``` albo ~~~, `inline`) zastąpionym spacjami;
// pozycje dopasowań zgadzają się z oryginałem (patrz vault.mask_code).
function maskCode(text) {
  const blank = (m) => m.replace(/[^\n]/g, " ");
  return text
    // Ogrodzenie z 3+ znaków, zamykane co najmniej tyloma samymi (jak _FENCE_RE w vault.py).
    // Dwie osobne gałęzie: w JS odwołanie do grupy, która nie wzięła udziału, pasuje do pustego tekstu.
    .replace(/^[ \t]{0,3}(?:(`{3,})[^`\n]*\n[\s\S]*?(?:^[ \t]{0,3}\1`*[ \t]*$|$(?![\s\S]))|(~{3,})[^\n]*\n[\s\S]*?(?:^[ \t]{0,3}\2~*[ \t]*$|$(?![\s\S])))/gm, blank)
    .replace(/`[^`\n]+`/g, blank);
}

// Edytor pól odtwarza plik jako "# Tytuł", "type: Typ", pusta linia, treść. Notatka, w której
// PRZED nagłówkiem jest tekst (frontmatter YAML Obsidiana, komentarz) albo typ ma kilka słów
// lub kilka linii "type:", nie ma takiego układu: zapis z pól przepisałby ją po swojemu
// (frontmatter pod nagłówkiem, przestaje działać). Taką edytujemy tylko jako surowy Markdown.
function fitsStructuredEditor(text) {
  const masked = maskCode(text);
  const h1 = masked.match(/^#[ \t]+\S.*$/m);
  if (h1 && text.slice(0, h1.index).trim()) return false;
  if (!h1 && /^\s*---[ \t]*\n/.test(text)) return false; // frontmatter bez nagłówka
  const typeLines = masked.match(/^type:.*$/gm) || [];
  if (typeLines.length > 1) return false;
  // 1.27.0 (audyt): więcej linii "klucz: wartość" tuż pod type: (zadanie stałe:
  // status, interwal_minut; fakt z pamięci: data) to nagłówek, nie treść - edytor
  // pól wstawiłby pustą linię i zadanie po cichu przestałoby działać.
  if (/^type:.*\n[a-z_]+:[ \t]*\S/m.test(masked)) return false;
  return typeLines.every((line) => /^type:[ \t]*\S+[ \t]*$/.test(line));
}

function showEditMode(rawMode) {
  document.getElementById("edit-form-fields").style.display = rawMode ? "none" : "block";
  document.getElementById("edit-raw-field").style.display = rawMode ? "block" : "none";
  const toggleBtn = document.getElementById("btn-toggle-edit-raw");
  toggleBtn.textContent = rawMode ? "Wróć do pól osobno" : "Edytuj jako surowy Markdown";
  toggleBtn.dataset.rawMode = rawMode ? "1" : "0";
}

function setEditRawMode(rawMode, data) {
  if (rawMode) {
    // Przenieś aktualne wartości pól do trybu surowego, żeby nie zgubić edycji.
    const title = document.getElementById("edit-title").value.trim() || data.title;
    const type = document.getElementById("edit-type").value;
    const bodyText = composeBody(document.getElementById("edit-body").value, editLinks);
    document.getElementById("edit-raw").value = `# ${title}\ntype: ${type}\n\n${bodyText}\n`;
  } else {
    // Wróć z surowego trybu do pól, spróbuj wyciągnąć tytuł/typ z tekstu.
    // Te same wzorce co na serwerze (agent/vault.py: TITLE_RE, FRONTMATTER_TYPE_RE,
    // mask_code): "## Sekcja" i "#tag" nie są tytułem, a "# komentarz" w bloku
    // kodu też nie. Wycinamy tylko dopasowaną linię, resztę zostawiamy.
    let raw = document.getElementById("edit-raw").value;
    let masked = maskCode(raw);
    const cut = (re) => {
      const m = masked.match(re);
      if (!m) return null;
      const piece = raw.slice(m.index, m.index + m[0].length);
      raw = raw.slice(0, m.index) + raw.slice(m.index + m[0].length);
      masked = masked.slice(0, m.index) + masked.slice(m.index + m[0].length);
      return piece;
    };
    const titleLine = cut(/^#[ \t]+\S.*$/m);
    const typeLine = cut(/^type:[ \t]*\S+[ \t]*$/m);
    if (titleLine) document.getElementById("edit-title").value = titleLine.replace(/^#[ \t]+/, "").trim();
    if (typeLine) {
      const typeValue = typeLine.replace(/^type:[ \t]*/, "").trim();
      const select = document.getElementById("edit-type");
      if (![...select.options].some((o) => o.value === typeValue)) {
        const extra = document.createElement("option");
        extra.value = typeValue;
        extra.textContent = typeLabelPl(typeValue);
        select.appendChild(extra);
      }
      select.value = typeValue;
    }
    const back = splitLinksLine(raw);
    editLinks = back.links;
    document.getElementById("edit-body").value = back.content;
    renderEditLinks(null);
  }

  showEditMode(rawMode);
}

let noteSaveInFlight = false;

// 1.18.0: kolor komunikatu stanu przez klasę (.is-error/.is-dim w styles.css),
// nie przez kolor wpisywany w styl elementu w wielu miejscach - jedno miejsce na wygląd.
function setStatusTone(el, tone) {
  if (!el) return;
  el.classList.toggle("is-error", tone === "error");
  el.classList.toggle("is-dim", tone === "dim");
}

async function saveNoteEdit(id, baseVersion) {
  if (noteSaveInFlight) return; // podwójne kliknięcie nie wysyła zapisu dwa razy
  const status = document.getElementById("note-edit-status");
  if (!editDirty) { // nic nie zmieniono: plik zostaje bajt w bajt taki, jaki był
    status.textContent = "Bez zmian.";
    setStatusTone(status, "dim");
    return;
  }
  const rawMode = document.getElementById("btn-toggle-edit-raw").dataset.rawMode === "1";

  let text;
  if (rawMode) {
    text = document.getElementById("edit-raw").value;
  } else {
    const title = document.getElementById("edit-title").value.trim();
    const type = document.getElementById("edit-type").value;
    const bodyText = composeBody(document.getElementById("edit-body").value, editLinks);
    if (!title) {
      status.textContent = "Podaj nazwę.";
      setStatusTone(status, "error");
      return;
    }
    text = `# ${title}\ntype: ${type}\n\n${bodyText}\n`;
  }

  status.textContent = "Zapisuję…";
  setStatusTone(status, "dim");
  noteSaveInFlight = true;
  // Pola zablokowane na czas zapisu: znaki dopisane po wysłaniu nie zostaną
  // po cichu zgubione przy odbudowie formularza po zapisie.
  setEditFieldsDisabled(true);
  try {
    const res = await gregaiFetch("/api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, text, base: baseVersion }),
    });
    const data = await res.json();
    if (data.error) {
      status.textContent = `Błąd: ${data.error}`;
      setStatusTone(status, "");
      status.classList.toggle("note-edit-status-conflict", res.status === 409);
      document.getElementById("note-edit-reload-btn")?.remove(); // bez duplikatu przy kolejnej nieudanej próbie
      if (res.status === 409) {
        // Notatka zmieniła się na dysku od otwarcia edycji: zamiast zostawić
        // samą czerwoną linijkę, od razu oferujemy wyjście - świeżą wersję
        // o kliknięcie dalej, zamiast zgadywania co teraz zrobić z tekstem.
        const reload = document.createElement("button");
        reload.type = "button";
        reload.id = "note-edit-reload-btn";
        reload.className = "inspector-btn secondary note-edit-reload-btn";
        reload.textContent = "Wczytaj najnowszą wersję";
        reload.addEventListener("click", () => {
          // Wczytanie na nowo odrzuca to, co jest teraz w polach: ten sam konflikt
          // co zwykła zmiana zaznaczenia przy niezapisanej edycji, to samo pytanie.
          if (editDirty && !window.confirm("Wczytanie najnowszej wersji odrzuci Twój obecny, niezapisany tekst. Najpierw skopiuj go, jeśli chcesz go zachować. Kontynuować?")) return;
          startNoteEdit(id);
        });
        status.after(reload);
      } else {
        setStatusTone(status, "error");
      }
      refocusSave();
      return;
    }
    let savedMsg = data.backlinks_updated
      ? `Zapisano. Zaktualizowano ${data.backlinks_updated} ${pluralPl(data.backlinks_updated, "połączenie", "połączenia", "połączeń")} w innych notatkach.`
      : "Zapisano.";
    if (data.backlinks_failed) {
      savedMsg += ` Nie udało się przepisać połączeń w ${data.backlinks_failed} ${pluralPl(data.backlinks_failed, "notatce", "notatkach", "notatkach")} (szczegóły w dzienniku serwera).`;
    }
    if (data.backlinks_skipped) {
      savedMsg += ` Uwaga: ${data.backlinks_skipped}`;
    }
    // Treść, tytuł, typ lub połączenia mogły się zmienić, odśwież dane
    // na istniejącym obiekcie grafu (nie twórz nowego przez loadGraph()).
    editDirty = false;
    await refreshGraphData();
    // W trakcie zapisu użytkownik mógł zaznaczyć inną notatkę: nie wracamy do tej.
    if (selectedNodeId !== id) return;
    graph.focusNode(id);
    // focusNode odbudował inspektor (podgląd notatki): komunikat dopisujemy pod nim.
    const inspector = document.getElementById("inspector-body");
    if (inspector) {
      const note = document.createElement("p");
      note.className = "note-edit-status";
      note.textContent = savedMsg;
      inspector.appendChild(note);
      const editBtn = document.getElementById("btn-edit-note");
      if (editBtn) editBtn.focus();
    }
  } catch (err) {
    status.textContent = `Błąd zapisu: ${err.message}`;
    setStatusTone(status, "error");
    refocusSave();
  } finally {
    noteSaveInFlight = false;
    setEditFieldsDisabled(false);
  }
}

// Po nieudanym zapisie pola są odblokowywane w `finally`, więc fokus oddajemy w następnej turze.
function refocusSave() {
  setTimeout(() => { const b = document.getElementById("btn-save-note"); if (b && !b.disabled) b.focus(); }, 0);
}

function setEditFieldsDisabled(disabled) {
  document.querySelectorAll("#inspector-body input, #inspector-body textarea, #inspector-body select, #inspector-body button")
    .forEach((el) => { el.disabled = disabled; });
}

// Ucieka też cudzysłowy: wynik trafia do atrybutów (value="...",
// data-clarify-text="..."), gdzie sam tekst z <div>.innerHTML nie wystarcza.
function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Dymki czatu: lekki, własny Markdown (bez biblioteki - zero zależności, jak
// cała resta UI). Zgłoszenie Grzegorza: model formatuje odpowiedzi
// Markdownem (pogrubienia, listy - patrz agent/prompt.md), a dymek pokazywał
// to surowo ("**Dobro**" ze gwiazdkami). Obsługuje tylko to, czego model
// faktycznie używa: pogrubienie, kursywę, `kod`, listy wypunktowane/numerowane
// i akapity. KAŻDA linia jest uciekana escapeHtml() ZANIM cokolwiek inne jej
// dotknie - model nigdy nie wstrzykuje HTML, nawet jeśli ktoś by go o to
// poprosił w rozmowie.
// 1.18.0 (audyt interfejsu): wszystko, co renderer sam wstawia jako HTML
// (kod, odnośniki, [[wikilinki]]), trafia najpierw do schowka-zastępnika,
// żeby późniejsze reguły kursywy/pogrubienia go nie pocięły: "`a_b` i `c_d`"
// dawało <em> przecinające </code>. Kursywa tylko na granicy słowa (snake_case
// zostaje), gwiazdka otoczona spacjami ("2 * 3 * 4") to mnożenie, nie kursywa.
const MD_BOLD_STAR = /\*\*(?=\S)([^*]+?)(?<=\S)\*\*/g;
const MD_BOLD_UNDER = /(?<![\p{L}\p{N}_])__(?=\S)(.+?)(?<=\S)__(?![\p{L}\p{N}_])/gu;
const MD_EM_STAR = /(?<![*\p{L}\p{N}_])\*(?=\S)([^*\n]*?\S)\*(?![*\p{L}\p{N}_])/gu;
const MD_EM_UNDER = /(?<![\p{L}\p{N}_])_(?=\S)([^_\n]*?\S)_(?![\p{L}\p{N}_])/gu;
// Odnośnik po ucieczce HTML: kończy się na białym znaku; z końca zdejmujemy
// interpunkcję i uciekane cudzysłowy/nawiasy, które należą do zdania, nie do adresu.
// Bez \u0000: znaczniki miejsc (kod, wikilinki) nie mogą wejść do adresu.
const MD_URL = /\bhttps?:\/\/[^\s\u0000]+/g;
const MD_URL_TAIL_PART = /(?:&quot;|&#39;|&gt;|&lt;|[.,;:!?)\]”’])$/;

// Końcówka adresu, która jest interpunkcją zdania, nie częścią adresu. Nawias
// zamykający zostaje, gdy ma parę w adresie (Wikipedia: "Foo_(bar)").
function splitUrlTail(url) {
  let href = url;
  let tail = "";
  for (;;) {
    const m = href.match(MD_URL_TAIL_PART);
    if (!m) break;
    if (m[0] === ")" && (href.match(/\(/g) || []).length >= (href.match(/\)/g) || []).length) break;
    href = href.slice(0, -m[0].length);
    tail = m[0] + tail;
  }
  return [href, tail];
}

function inlineMarkdown(line) {
  const slots = [];
  const keep = (html) => `\u0000${slots.push(html) - 1}\u0000`;
  let out = escapeHtml(String(line ?? "").replace(/\u0000/g, ""));
  out = out.replace(/`([^`]+)`/g, (_, code) => keep(`<code>${code}</code>`));
  // 1.17.12: [[Tytuł notatki]] jako tytuł w cudzysłowie; 1.18.0: klikalny -
  // otwiera tę notatkę w Węzłach (delegowany nasłuch w initChat).
  // Audyt 1.32.1: kod `x` w środku [[...]] zostawiał w tytule znacznik zastępczy
  // (\0 1 \0) - teraz wstawiamy tam sam tekst kodu (już ucieczony).
  const plainSlots = (t) => t.replace(/\u0000(\d+)\u0000/g, (_, i) => (slots[Number(i)] || "").replace(/<[^>]*>/g, ""));
  out = out.replace(/\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g, (_, title, alias) =>
    keep(`<span class="chat-wikilink" role="link" tabindex="0" data-note-title="${plainSlots(title).trim()}" title="Otwórz notatkę w Węzłach">„${plainSlots(alias || title).trim()}”</span>`));
  out = out.replace(MD_URL, (url) => {
    const [href, tail] = splitUrlTail(url);
    if (!/^https?:\/\/[^/\s]/.test(href)) return url;
    return keep(`<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>`) + tail;
  });
  out = out.replace(MD_BOLD_STAR, "<strong>$1</strong>");
  out = out.replace(MD_BOLD_UNDER, "<strong>$1</strong>");
  out = out.replace(MD_EM_STAR, "<em>$1</em>");
  out = out.replace(MD_EM_UNDER, "<em>$1</em>");
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)] || "");
}

function renderMarkdownLite(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const htmlParts = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      htmlParts.push(`<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`);
      paragraph = [];
    }
  };
  const BULLET = /^\s*[-*•]\s+(.*)$/;
  const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
  // 1.17.6 (zrzut Grzegorza): modele sieciowe dokładają nagłówki "### ",
  // linie "---" i cytaty "> " - dymek pokazywał je surowo. Nagłówek = osobna
  // pogrubiona linia (nie <h3>: w dymku rozmowy to tylko śródtytuł),
  // separator = cienka kreska, cytat = wcięty blok.
  const HEADING = /^\s*#{1,6}\s+(.*)$/;
  const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
  const QUOTE = /^\s*>\s?(.*)$/;
  // 1.19.0 (audyt interfejsu): blok kodu ``` ... ``` to jeden <pre>, bez żadnego
  // formatowania w środku ("# komentarz" nie jest nagłówkiem, "- x" nie jest
  // punktem), z przyciskiem kopiowania. Prosta tabela "| a | b |" + linia
  // "|---|---|" to <table>.
  const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
  const TABLE_ROW = /^\s*\|.*\|\s*$/;
  const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;
  // Podział wiersza tabeli: "|" w `kodzie`, w [[link|alias]] i zapisane jako \|
  // nie dzieli komórki.
  const cells = (row) => {
    const t = row.trim().replace(/^\|/, "");
    const out = [];
    let cur = "", inCode = false, inLink = false;
    for (let k = 0; k < t.length; k++) {
      const ch = t[k];
      if (ch === "\\" && t[k + 1] === "|") { cur += "|"; k++; continue; }
      if (ch === "`") inCode = !inCode;
      else if (!inCode && t.startsWith("[[", k)) { inLink = true; cur += "[["; k++; continue; }
      else if (!inCode && inLink && t.startsWith("]]", k)) { inLink = false; cur += "]]"; k++; continue; }
      else if (ch === "|" && !inCode && !inLink) { out.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    if (cur.trim() || !t.endsWith("|")) out.push(cur.trim());
    return out;
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = FENCE.exec(line);
    if (fence) {
      flushParagraph();
      const marker = fence[1];
      const lang = fence[2] || "";
      const body = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(marker[0].repeat(3)) && lines[i].trim().replace(/[`~]/g, "") === "")) {
        body.push(lines[i]);
        i++;
      }
      i++; // linia zamykająca (albo koniec tekstu)
      htmlParts.push(
        `<div class="chat-code"><div class="chat-code-bar"><span class="chat-code-lang">${escapeHtml(lang || "kod")}</span>` +
        `<button type="button" class="chat-code-copy" aria-label="Kopiuj kod">Kopiuj kod</button></div>` +
        `<pre><code>${escapeHtml(body.join("\n"))}</code></pre></div>`);
      continue;
    }
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      flushParagraph();
      const head = cells(line);
      // Wyrównanie kolumn z linii "|:---|:---:|---:|" - klasami, nie stylem w HTML (CSP).
      const align = cells(lines[i + 1]).map((c) => (/^:-+:$/.test(c) ? " class=\"al-center\"" : /^-+:$/.test(c) ? " class=\"al-right\"" : ""));
      i += 2;
      const rows = [];
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        rows.push(cells(lines[i]));
        i++;
      }
      const th = head.map((c, k) => `<th${align[k] || ""}>${inlineMarkdown(c)}</th>`).join("");
      const trs = rows.map((r) => `<tr>${head.map((_, k) => `<td${align[k] || ""}>${inlineMarkdown(r[k] || "")}</td>`).join("")}</tr>`).join("");
      htmlParts.push(`<div class="chat-table-wrap"><table class="chat-table"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`);
      continue;
    }
    if (RULE.test(line)) {
      flushParagraph();
      htmlParts.push("<hr>");
      i++;
      continue;
    }
    if (HEADING.test(line)) {
      flushParagraph();
      htmlParts.push(`<p class="chat-heading"><strong>${inlineMarkdown(HEADING.exec(line)[1])}</strong></p>`);
      i++;
      continue;
    }
    if (QUOTE.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        items.push(inlineMarkdown(QUOTE.exec(lines[i])[1]));
        i++;
      }
      htmlParts.push(`<blockquote>${items.join("<br>")}</blockquote>`);
      continue;
    }
    if (BULLET.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && BULLET.test(lines[i])) {
        items.push(`<li>${inlineMarkdown(BULLET.exec(lines[i])[1])}</li>`);
        i++;
      }
      htmlParts.push(`<ul>${items.join("")}</ul>`);
      continue;
    }
    if (NUMBERED.test(line)) {
      flushParagraph();
      const items = [];
      // 1.18.0: lista kontynuowana po akapicie ("3. ...") zaczyna od SWOJEGO numeru.
      const first = Number(NUMBERED.exec(line)[1]);
      while (i < lines.length && NUMBERED.test(lines[i])) {
        items.push(`<li>${inlineMarkdown(NUMBERED.exec(lines[i])[2])}</li>`);
        i++;
      }
      htmlParts.push(`<ol${first > 1 ? ` start="${first}"` : ""}>${items.join("")}</ol>`);
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      i++;
      continue;
    }
    paragraph.push(line);
    i++;
  }
  flushParagraph();
  return htmlParts.join("");
}

// Znaki niewidoczne i sterujące (np. U+202E, zmiana kierunku tekstu) pokazane
// jawnie jako \uXXXX: to, co karta pokazuje, musi być tym, co zostanie wykonane.
// Nowa linia i tabulator zostają.
function revealHidden(text) {
  // Także spacje inne niż zwykła (U+00A0, U+3000...) i znaki-wypełniacze (U+3164, U+2800...),
  // które wyglądają jak puste miejsce, a w poleceniu czy ścieżce znaczą co innego.
  return String(text ?? "").replace(/[\p{Cc}\p{Cf}\p{Zs}\u2028\u2029\u3164\u2800\u115F\u1160\uFFA0]/gu, (ch) => {
    if (ch === "\n" || ch === "\t" || ch === " ") return ch;
    const hex = ch.codePointAt(0).toString(16).toUpperCase();
    return hex.length > 4 ? `\\u{${hex}}` : `\\u${hex.padStart(4, "0")}`;
  });
}

// --- Pasek dolny: wyszukiwanie węzłów po nazwie (bez AI, czyste
// dopasowanie tekstowe do już wczytanych danych grafu) -----------------
function initSearchBar() {
  const input = document.getElementById("search-input");
  let lastQuery = "";
  let lastIndex = -1;
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const query = input.value.trim().toLowerCase();
    if (!query) return;
    // Najpierw dokładna nazwa, potem początek nazwy, potem zawieranie; ponowne
    // Enter z tym samym tekstem przechodzi do kolejnego trafienia.
    const rank = (n) => {
      const t = n.title.toLowerCase();
      return t === query ? 0 : t.startsWith(query) ? 1 : t.includes(query) ? 2 : 3;
    };
    const matches = graphData.nodes.filter((n) => rank(n) < 3).sort((a, b) => rank(a) - rank(b));
    if (query !== lastQuery) lastIndex = -1;
    lastQuery = query;
    if (matches.length) {
      lastIndex = (lastIndex + 1) % matches.length;
      graph.focusNode(matches[lastIndex].id);
    } else {
      showBanner(`Brak węzła pasującego do: "${input.value.trim()}"`, { ms: 2500 });
    }
  });
}

// --- Dymek "Jak korzystać z mapy" (1.15.0): pokazuje się przy pierwszej wizycie
// w Węzłach, zamykany krzyżykiem (zapamiętane w przeglądarce, z try/catch -
// tryb prywatny potrafi odrzucić localStorage), wraca przyciskiem "?". ---
function initNodesGuide() {
  const guide = document.getElementById("nodes-guide");
  const closeBtn = document.getElementById("nodes-guide-close");
  const helpBtn = document.getElementById("nodes-help-btn");
  if (!guide) return;
  const KEY = "gregai_nodes_guide_closed";
  let closed = false;
  try { closed = localStorage.getItem(KEY) === "1"; } catch (e) { /* bez zapamiętywania */ }
  const set = (hidden) => {
    guide.classList.toggle("hidden", hidden);
    if (helpBtn) helpBtn.setAttribute("aria-pressed", String(!hidden));
  };
  set(closed);
  if (closeBtn) closeBtn.addEventListener("click", () => {
    set(true);
    try { localStorage.setItem(KEY, "1"); } catch (e) { /* ignoruj */ }
  });
  if (helpBtn) helpBtn.addEventListener("click", () => set(!guide.classList.contains("hidden") ? true : false));
}

// --- Tworzenie nowego węzła (modal) -----------------------------------

function populateCreateTypeSelect() {
  const select = document.getElementById("create-type");
  select.innerHTML = "";
  for (const type of TYPE_LABELS_ORDER) {
    const opt = document.createElement("option");
    opt.value = type; // wartość zapisana do pliku zostaje po angielsku
    opt.textContent = typeLabelPl(type);
    select.appendChild(opt);
  }
  // Pierwszy na liście jest "Rozmowa": nowa notatka bez wyboru typu ma być zwykłą notatką.
  if (TYPE_LABELS_ORDER.includes("Note")) select.value = "Note";
}

let createModalOpener = null;
// Pierwszy Esc w oknie z wpisaną treścią tylko ostrzega; drugi w ciągu 3 s zamyka. Zerowane przy
// KAŻDYM zamknięciu, inaczej po "Anuluj" następne otwarcie dałoby się odrzucić jednym Esc.
let escArmedAt = 0;

function openCreateModal(presetType) {
  createModalOpener = document.activeElement;
  document.getElementById("create-title").value = "";
  document.getElementById("create-text").value = "";
  document.getElementById("create-raw").value = "";
  document.getElementById("create-status").textContent = "";
  setCreateRawMode(false);
  populateCreateTypeSelect();
  // "Nowy projekt" w szynie Rozmowy: ten sam formularz, tylko z typem z góry
  // ustawionym na Project, zamiast zmuszać do przestawienia selecta ręcznie.
  const typeSelect = document.getElementById("create-type");
  if (presetType && [...typeSelect.options].some((o) => o.value === presetType)) {
    typeSelect.value = presetType;
  }
  populateLinkPicker("create-link-picker", null);
  // 1.19.0: tytuł okna mówi, co tworzysz (dawniej zawsze "Nowy węzeł").
  const head = document.getElementById("create-modal-title");
  if (head) head.textContent = presetType === "Project" ? "Nowy projekt" : "Nowa notatka";
  // 1.24.0: projekt = tytuł i jedno zdanie; typ, powiązania i surowy Markdown schowane.
  const simple = presetType === "Project";
  const panel = document.querySelector("#create-modal-overlay .modal-panel");
  if (panel) panel.classList.toggle("simple-project", simple);
  const textLabel = document.getElementById("create-text-label");
  if (textLabel) textLabel.textContent = simple ? "O czym jest ten projekt? (opcjonalnie)" : "Treść (opcjonalnie, obsługuje [[wikilinki]])";
  document.getElementById("create-title").placeholder = simple ? "np. Skup iPhone'ów" : "np. Nowy klient";
  const saveBtn = document.getElementById("btn-create-save");
  if (saveBtn) saveBtn.textContent = simple ? "Utwórz i zacznij rozmowę" : "Utwórz";
  document.getElementById("create-modal-overlay").classList.add("visible");
  document.getElementById("create-title").focus();
}

function closeCreateModal() {
  escArmedAt = 0;
  document.getElementById("create-modal-overlay").classList.remove("visible");
  // Fokus wraca tam, skąd otwarto okno (klawiatura nie ląduje na <body>).
  if (createModalOpener && createModalOpener.isConnected && typeof createModalOpener.focus === "function") createModalOpener.focus();
  createModalOpener = null;
}

function setCreateRawMode(rawMode) {
  document.getElementById("create-form-fields").style.display = rawMode ? "none" : "block";
  document.getElementById("create-raw-field").style.display = rawMode ? "block" : "none";
  document.getElementById("btn-toggle-raw").textContent = rawMode
    ? "Wróć do zwykłego formularza"
    : "Wklej surowy Markdown";
  document.getElementById("btn-toggle-raw").dataset.rawMode = rawMode ? "1" : "0";
  if (rawMode) document.getElementById("create-raw").focus();
}

async function submitCreateNode() {
  const rawMode = document.getElementById("btn-toggle-raw").dataset.rawMode === "1";
  const status = document.getElementById("create-status");
  let payload;

  if (rawMode) {
    const raw = document.getElementById("create-raw").value.trim();
    if (!raw) {
      status.textContent = "Wklej treść notatki.";
      setStatusTone(status, "error");
      return;
    }
    payload = { raw };
  } else {
    const title = document.getElementById("create-title").value.trim();
    const type = document.getElementById("create-type").value;
    const text = document.getElementById("create-text").value;
    if (!title) {
      status.textContent = "Podaj tytuł.";
      setStatusTone(status, "error");
      return;
    }
    payload = { title, type, text };
  }

  status.textContent = "Tworzę…";
  setStatusTone(status, "dim");
  const saveBtn = document.getElementById("btn-create-save");
  saveBtn.disabled = true; // podwójne kliknięcie nie utworzy dwóch notatek
  try {
    const res = await gregaiFetch("/api/note/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) {
      status.textContent = `Błąd: ${data.error}`;
      setStatusTone(status, "error");
      return;
    }
    closeCreateModal();
    await refreshGraphData();
    if (data.type === "Project") {
      // Nowy projekt: prosto do jego własnej, odizolowanej rozmowy, zamiast
      // centrować graf (Węzły to teraz podkategoria, nie tu zaczyna się praca).
      setActiveProject({ id: data.id, title: data.title });
    } else {
      graph.focusNode(data.id);
    }
  } catch (err) {
    status.textContent = `Błąd: ${err.message}`;
    setStatusTone(status, "error");
  } finally {
    saveBtn.disabled = false;
  }
}

function initCreateModal() {
  document.getElementById("btn-new-node").addEventListener("click", () => openCreateModal());
  document.getElementById("btn-new-project").addEventListener("click", () => openCreateModal("Project"));
  // 1.9.0: Namysł (ustawienia), załączniki (spinacz), Źródła (foldery).
  setupNamyslControl();
  setupAttachments();
  setupSources();
  showReturnNote();
  document.getElementById("btn-create-cancel").addEventListener("click", closeCreateModal);
  document.getElementById("btn-create-save").addEventListener("click", submitCreateNode);
  document.getElementById("btn-toggle-raw").addEventListener("click", (e) => {
    const currentlyRaw = e.currentTarget.dataset.rawMode === "1";
    setCreateRawMode(!currentlyRaw);
  });
  document.getElementById("btn-insert-create-link").addEventListener("click", () => {
    const select = document.getElementById("create-link-picker");
    if (select.value) insertLinkAtCursor("create-text", select.value);
  });
  // Zamknięcie tłem tylko wtedy, gdy KLIKNIĘCIE ZACZĘŁO się na tle (zaznaczanie
  // tekstu w polu z puszczeniem myszy poza panelem nie może zamknąć okna) i
  // formularz jest pusty. Wpisanej treści nie gubimy: Esc przy niepustym
  // formularzu pyta (drugi Esc w ciągu 3 s zamyka), przycisk Anuluj zamyka zawsze.
  const overlay = document.getElementById("create-modal-overlay");
  let pressedOnOverlay = false;
  overlay.addEventListener("mousedown", (e) => { pressedOnOverlay = e.target === overlay; });
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay && pressedOnOverlay && !createModalHasInput()) closeCreateModal();
    pressedOnOverlay = false;
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && overlay.classList.contains("visible")) {
      // Tab krąży po oknie: bez tego fokus uciekał na graf pod nakładką.
      const items = [...overlay.querySelectorAll("input, textarea, select, button")]
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      if (!overlay.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      return;
    }
    if (e.key !== "Escape" || !overlay.classList.contains("visible")) return;
    if (!createModalHasInput() || Date.now() - escArmedAt < 3000) {
      escArmedAt = 0;
      closeCreateModal();
      return;
    }
    escArmedAt = Date.now();
    showBanner("W formularzu jest wpisana treść. Naciśnij Esc jeszcze raz, żeby ją odrzucić.", { info: true, ms: 3000 });
  });
}

function createModalHasInput() {
  return ["create-title", "create-text", "create-raw"].some((id) => document.getElementById(id).value.trim() !== "");
}

// Notatki zmieniają się też poza interfejsem (serce zapisuje wnioski, pliki
// edytujesz w innym programie): po powrocie na kartę graf odświeża się sam.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  refreshModelBadge();
  if (!noteSaveInFlight && Date.now() - lastGraphRefresh > 15000) refreshGraphData();
});

window.addEventListener("DOMContentLoaded", () => {
  ensureToken();
  loadGraph();
  initSearchBar();
  initNodesGuide();
  initCreateModal();
  initChat();
});

/**
 * Czat: wysyła do /api/chat (lokalny model w Ollamie, a bez niego wzorce
 * słów kluczowych). Historia trzymana tylko w pamięci karty przeglądarki,
 * ostatnie 10 wiadomości.
 */
let modelBadgeInterval = null;

// --- Rozmowy: "Ogólna" (jak dotąd) + jedna na każdy projekt z szyny
// "Projekty" (populateProjectList wyżej). KAŻDA ma WŁASNĄ historię i WŁASNE
// karty doprecyzowania/potwierdzenia (pendingClarify/pendingAction) - to
// właśnie fizyczna izolacja, o którą prosił użytkownik ("projekty nie mają
// wspólnej wiedzy"): backend dostaje do każdej wiadomości TYLKO historię
// tego jednego wątku (patrz sendChatMessage) i, gdy project jest ustawiony,
// okrojony graf (agent/main.py: project_scope + shared_pool_slugs).
// 1.19.0 (audyt interfejsu): każda rozmowa ma też WŁASNĄ trwającą odpowiedź
// (run), szkic pola wpisywania (draft), stan "nieprzeczytane" (unread) i postęp
// Namysłu (progress). Odpowiedź jest przypięta do rozmowy, z której wyszła:
// trafia do niej i rysuje się tylko wtedy, gdy ta rozmowa jest otwarta - wolno
// więc przełączać rozmowy w trakcie odpowiedzi (dawniej odpowiedź lądowała w
// rozmowie otwartej w chwili przyjścia, a zapisywała się w innej).
// Wiadomości przeżywają odświeżenie strony (localStorage tej przeglądarki,
// patrz saveConversations); karty "tak/nie" po odświeżeniu są już nieaktywne.
const conversations = new Map(); // key -> {history, pendingClarify, pendingAction, messages, run, draft, unread, progress, pendingEl}
let activeProject = null; // null = Ogólna rozmowa; inaczej {id, title}

function conversationKey(project) {
  return project ? project.id : "__general__";
}

function getConversation(project) {
  const key = conversationKey(project);
  if (!conversations.has(key)) {
    conversations.set(key, { history: [], pendingClarify: null, pendingAction: null, messages: [],
      run: null, draft: "", unread: false, progress: null, pendingEl: null });
  }
  return conversations.get(key);
}

function activeConversation() {
  return getConversation(activeProject);
}

// Trwająca odpowiedź OTWARTEJ rozmowy (przycisk Zatrzymaj, Esc, blokada pola).
function activeRun() {
  return activeConversation().run;
}

// --- Rozmowy po odświeżeniu (1.19.0): tylko w TEJ przeglądarce, tylko
// wygoda. Zapisujemy tekst dymków, karty (bez stanu "do kliknięcia") i
// historię dla modelu; nigdy tokenu ani niczego spoza rozmowy. Każdy odczyt
// i zapis w try/catch: tryb prywatny i pełna pamięć nie psują rozmowy.
const CONV_STORE_KEY = "gregai.rozmowy.v1";
const CONV_STORE_MAX_MESSAGES = 80;
const CONV_STORE_MAX_CHARS = 1500000;
// Karty zapisywane w całości: same odczyty, bez wyniku poleceń systemowych.
// localStorage to zwykły plik przeglądarki (także na telefonie w sieci domowej),
// więc karta SYSOP/zadania/potwierdzenia zostaje tylko jako krótki opis.
const CONV_STORE_SAFE_CARDS = new Set(["namysl", "market_quote", "wiki_lookup", "research_web", "weather", "diagnoza"]);
const CARD_SHORT_LABELS = {
  sysop: "polecenie systemowe", zadanie: "zadanie wielokrokowe", confirm: "pytanie o zgodę",
  clarify: "dopytanie", network_status: "stan sieci", self_status: "stan GREGAI",
};
let convSaveTimer = null;
const convTombstones = new Map(); // key -> czas usunięcia (żeby druga karta nie wskrzesiła rozmowy)

// 1.23.0 (audyt): "Sprawdź, czy odpowiedź jest gotowa" - przycisk odtwarzany też po
// przełączeniu rozmowy i po odświeżeniu (jobId zapisany w wiadomości), a odebrana
// odpowiedź przechodzi PEŁNĄ ścieżkę: karta, pytanie o zgodę, historia dla modelu.
function attachResumeButton(conv, project, failMsg, failBubble) {
  const check = document.createElement("button");
  check.type = "button";
  check.className = "chat-retry";
  const isQuestion = failMsg.role === "user";  // 1.29.0: odświeżenie strony w trakcie odpowiedzi
  check.textContent = isQuestion ? "Odpowiedź mogła już przyjść. Sprawdź" : "Sprawdź, czy odpowiedź jest gotowa";
  check.addEventListener("click", async () => {
    if (conv.run) return;
    check.disabled = true;
    try {
      const got = await waitForChatJob(failMsg.jobId);
      if (got && typeof got.speech === "string" && !got.error) {
        if (isQuestion) {
          check.remove();
          delete failMsg.jobId;
        } else {
          const at = conv.messages.lastIndexOf(failMsg);
          if (at >= 0) conv.messages.splice(at, 1);
          failBubble.remove();
        }
        conv.pendingClarify = got.pending_clarify || null;
        conv.pendingAction = got.pending_action || null;
        const msg = { role: "assistant", text: got.speech || "(brak odpowiedzi)", card: got.card || null, node: got.suggested_node || null };
        // 1.32.14 (rozmowa 25.10): odebrana PÓŹNIEJ odpowiedź trafia ZA swoje pytanie, nie na koniec
        // rozmowy (lądowała pod odpowiedzią na kolejne pytanie, jakby była jej częścią).
        const qAt = isQuestion ? conv.messages.indexOf(failMsg) : -1;
        if (qAt >= 0) {
          msg.note = "Odpowiedź odebrana później, dotyczy pytania wyżej.";
          conv.messages.splice(qAt + 1, 0, msg);
        } else {
          convPush(conv, msg);
        }
        const asked = failMsg.askText || (isQuestion ? failMsg.raw : "");
        if (asked) {
          conv.history.push({ role: "user", content: asked });
          conv.history.push({ role: "assistant", content: got.speech || "", tool: got.kind !== "chat", sig: got.sig || null, provider: got.provider || null });
          if (conv.history.length > 10) conv.history = conv.history.slice(-4);
        }
        saveConversations();
        if (activeConversation() === conv) renderConversationMessages(conv, project);
        if (got.graph_changed) refreshGraphData();
      } else if (got && got.error && !got.anulowano) {
        // 1.29.0 (kontrola): zadania już nie ma na serwerze (restart, upłynęła godzina) -
        // czekanie nic nie da; proponujemy zadać pytanie jeszcze raz.
        check.textContent = "Zapytaj jeszcze raz";
        check.disabled = false;
        check.onclick = null;
        const fresh = check.cloneNode(true);
        check.replaceWith(fresh);
        fresh.addEventListener("click", () => {
          const input = document.getElementById("chat-input");
          if (isQuestion) delete failMsg.jobId;
          input.value = failMsg.askText || failMsg.raw || "";
          input.dispatchEvent(new Event("input"));
          input.focus();
        });
        showBanner("Tej odpowiedzi nie ma już na serwerze. Zadaj pytanie jeszcze raz.", { info: true, ms: 5000 });
      } else {
        check.disabled = false;
        showBanner(got && got.anulowano ? "To zadanie zostało zatrzymane." : "Odpowiedzi jeszcze nie ma. Spróbuj za chwilę.", { info: true, ms: 4000 });
      }
    } catch (e) {
      check.disabled = false;
      showBanner("Nadal brak połączenia z serwerem. Spróbuj za chwilę.", { info: true, ms: 4000 });
    }
  });
  failBubble.appendChild(check);
}

function conversationDeletedSince(key, since) {
  try {
    const stored = readStoredConversations()[key];
    const at = Math.max(convTombstones.get(key) || 0, stored && typeof stored.deleted === "number" ? stored.deleted : 0);
    if (at >= since) { convTombstones.set(key, at); return true; }
  } catch (e) { /* brak odczytu = nic nie usunięto */ }
  return false;
}

function convPush(conv, msg) {
  conv.messages.push(msg);
  conv.updated = Date.now();
}

function cardForStore(card) {
  if (!card || typeof card !== "object") return null;
  if (CONV_STORE_SAFE_CARDS.has(card.type)) return card;
  return { type: "skrot", label: CARD_SHORT_LABELS[card.type] || "karta narzędzia" };
}

function readStoredConversations() {
  try {
    const raw = localStorage.getItem(CONV_STORE_KEY);
    const data = raw ? JSON.parse(raw) : null;
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch (e) { return {}; }
}

// Zamknięcie karty albo uśpienie telefonu nie gubi ostatniej wymiany (1.20.0).
window.addEventListener("pagehide", () => { if (convSaveTimer) writeConversationsNow(); });
document.addEventListener("visibilitychange", () => { if (document.hidden && convSaveTimer) writeConversationsNow(); });

function saveConversations() {
  if (convSaveTimer) clearTimeout(convSaveTimer);
  convSaveTimer = setTimeout(writeConversationsNow, 300);
}

function writeConversationsNow() {
  convSaveTimer = null;
  const out = {};
  for (const [key, c] of conversations) {
    if (!c.messages.length) continue;
    const msgs = c.messages.slice(-CONV_STORE_MAX_MESSAGES).map((m, i, arr) => ({
      role: m.role, text: String(m.text || "").slice(0, 20000), raw: m.raw ? String(m.raw).slice(0, 20000) : undefined,
      // Karty tylko przy ostatnich wiadomościach: są duże, a starsze i tak nic nie robią.
      card: i >= arr.length - 10 ? cardForStore(m.card) : null,
      node: i >= arr.length - 10 ? m.node || undefined : undefined, nodeOutcome: m.nodeOutcome || undefined,
      note: m.note || undefined, failed: m.failed || undefined,
      jobId: (m.failed || m.role === "user") && typeof m.jobId === "string" ? m.jobId : undefined,
      askText: m.failed && m.jobId && typeof m.askText === "string" ? m.askText.slice(0, 20000) : undefined,
    }));
    out[key] = { updated: c.updated || 0, messages: msgs,
      history: c.history.slice(-10).map((t) => Object.assign({}, t, { content: String(t.content || "").slice(0, 8000) })) };
  }
  for (const [key, at] of [...convTombstones]) {
    // Rozmowa napisana na nowo po usunięciu wygrywa z nagrobkiem (1.20.0);
    // stare nagrobki (30 dni) nie rosną bez końca.
    const live = conversations.get(key);
    if ((live && live.messages.length && (live.updated || 0) > at) || Date.now() - at > 30 * 86400000) {
      convTombstones.delete(key);
      continue;
    }
    out[key] = { deleted: at };
  }
  // Ostatni zapis wygrywa PER ROZMOWA (1.19.0, dwie karty): rozmowa nowsza w
  // magazynie (pisała ją inna karta) zostaje, zamiast zniknąć pod naszym zapisem.
  const stored = readStoredConversations();
  for (const [key, v] of Object.entries(stored)) {
    if (!v || typeof v !== "object") continue;
    const mine = out[key];
    const theirAt = v.deleted || v.updated || 0;
    const mineAt = mine ? (mine.deleted || mine.updated || 0) : 0;
    const live = conversations.get(key);
    if (live && live.run) continue; // trwająca odpowiedź: nasza wersja
    if (!mine || theirAt > mineAt) out[key] = v;
  }
  let json = JSON.stringify(out);
  // Za dużo: najpierw karty i długie teksty, potem najstarsze wiadomości KAŻDEJ
  // rozmowy (także małych), aż limit naprawdę się zgadza.
  for (let guard = 0; json.length > CONV_STORE_MAX_CHARS && guard < 60; guard++) {
    for (const v of Object.values(out)) {
      if (!v.messages) continue;
      v.messages.forEach((m) => {
        m.card = null; m.node = undefined;
        if (m.text && m.text.length > 4000) m.text = m.text.slice(0, 4000) + " (…)";
        if (m.raw && m.raw.length > 4000) m.raw = m.raw.slice(0, 4000);
      });
      (v.history || []).forEach((t) => { if (t.content.length > 2000) t.content = t.content.slice(0, 2000); });
      if (guard > 0) v.messages = v.messages.slice(Math.max(1, Math.floor(v.messages.length / 4)));
    }
    json = JSON.stringify(out);
  }
  try {
    if (json.length > CONV_STORE_MAX_CHARS) throw new Error("za duże");
    localStorage.setItem(CONV_STORE_KEY, json);
  } catch (e) {
    // Nieudany zapis (1.20.0): najpierw lżejsza wersja (20 ostatnich wiadomości,
    // bez kart). Kasowanie całego magazynu tylko ostateczność, z ostrzeżeniem.
    try {
      for (const v of Object.values(out)) {
        if (v.messages) v.messages = v.messages.slice(-20).map((m) => Object.assign({}, m, { card: null, node: undefined }));
        if (v.history) v.history = v.history.slice(-4);
      }
      localStorage.setItem(CONV_STORE_KEY, JSON.stringify(out));
    } catch (e2) {
      try { localStorage.removeItem(CONV_STORE_KEY); } catch (e3) { /* bez zapamiętywania */ }
      if (typeof showBanner === "function") showBanner("Przeglądarka nie pozwala zapisać rozmów. Po odświeżeniu mogą zniknąć.");
    }
  }
}

// Magazyn przeglądarki to dane z zewnątrz (stara wersja, ręczna edycja, inna
// karta): każde pole sprawdzane, nic nie przechodzi "na wiarę". Karty z
// magazynu przechodzą przez tę samą białą listę co przy zapisie.
const isObj = (x) => !!x && typeof x === "object" && !Array.isArray(x);
const strOrUndef = (x) => (typeof x === "string" ? x : undefined);

function applyStoredConversation(key, v) {
  const c = getConversation(key === "__general__" ? null : { id: key });
  c.messages = v.messages.filter((m) => isObj(m) && (m.role === "user" || m.role === "assistant") && typeof m.text === "string").map((m) => {
    const card = isObj(m.card) && typeof m.card.type === "string" ? cardForStore(m.card) : null;
    const node = isObj(m.node) && typeof m.node.title === "string" && typeof m.node.body === "string" ? m.node : null;
    return { role: m.role, text: m.text, raw: strOrUndef(m.raw), card, node, note: strOrUndef(m.note),
      nodeOutcome: strOrUndef(m.nodeOutcome), failed: m.failed === true,
      jobId: (m.failed === true || m.role === "user") ? strOrUndef(m.jobId) : undefined, askText: strOrUndef(m.askText) };
  });
  c.history = Array.isArray(v.history)
    ? v.history.filter((t) => isObj(t) && (t.role === "user" || t.role === "assistant") && typeof t.content === "string")
    : [];
  c.updated = v.updated || 0;
  // Karty "tak/nie" z magazynu są zawsze nieaktywne (serwer i tak już nie czeka).
  c.pendingAction = null;
  c.pendingClarify = null;
}

function loadConversations() {
  const data = readStoredConversations();
  if (Array.isArray(data)) return;
  for (const [key, v] of Object.entries(data)) {
    if (!isObj(v)) continue;
    if (typeof v.deleted === "number") { convTombstones.set(key, v.deleted); continue; }
    if (!Array.isArray(v.messages)) continue;
    applyStoredConversation(key, v);
  }
}

// Druga karta GREGAI zapisała rozmowy (1.19.0): bierzemy jej nowsze wersje
// rozmów, w których tu nic nie trwa, i odświeżamy otwartą, jeśli się zmieniła.
window.addEventListener("storage", (e) => {
  if (e.key !== CONV_STORE_KEY) return;
  const data = readStoredConversations();
  let activeChanged = false;
  for (const [key, v] of Object.entries(data)) {
    if (!v || typeof v !== "object") continue;
    const local = conversations.get(key);
    if (local && local.run) continue;
    const localAt = local ? local.updated || 0 : 0;
    if (v.deleted) {
      if (v.deleted > localAt && local) {
        conversations.delete(key);
        convTombstones.set(key, v.deleted);
        if (key === conversationKey(activeProject)) activeChanged = true;
      }
      continue;
    }
    if (!Array.isArray(v.messages) || (v.updated || 0) <= localAt) continue;
    applyStoredConversation(key, v);
    if (key === conversationKey(activeProject)) activeChanged = true;
  }
  if (activeChanged && typeof renderConversationMessages === "function") {
    renderConversationMessages(activeConversation(), activeProject);
  }
  if (typeof populateProjectList === "function") populateProjectList();
});

function forgetConversation(project) {
  const key = conversationKey(project);
  conversations.delete(key);
  convTombstones.set(key, Date.now());
  saveConversations();
}

// Rozmowy projektów, których węzła już nie ma w grafie (usunięty projekt),
// nie wiszą w magazynie przeglądarki.
function dropConversationsOfMissingProjects() {
  if (!graphData.nodes.length) return; // graf się nie wczytał - nic nie usuwamy na ślepo
  const ids = new Set(graphData.nodes.filter((n) => n.type === "Project").map((n) => n.id));
  let changed = false;
  for (const [key, c] of [...conversations]) {
    if (key === "__general__" || ids.has(key) || c.run) continue;
    conversations.delete(key);
    convTombstones.set(key, Date.now());
    changed = true;
  }
  if (changed) saveConversations();
}

// Zamiast prawdziwego DOM-u (karty tak/nie, karty sieci) pamiętamy tylko tekst
// dymków: wystarcza do odtworzenia wątku po powrocie, a ewentualne karty i tak
// mają sens tylko "na żywo", jedną wymianę (patrz pendingClarify/pendingAction).
// Ekran powitalny pustej rozmowy (1.13.0): prowadzi za rękę. Trzy kroki i
// kafelki na start - klik WYPEŁNIA pole albo otwiera właściwe miejsce
// (spinacz, szufladka Źródeł), niczego nie wysyła sam.
const WELCOME_STARTERS = [
  { ico: "📅", tone: "lemon", title: "Zaplanuj mój dzień", sub: "przygotuję prośbę, Ty wyślesz", fill: "Zaplanuj mi dzień na dziś" },
  { ico: "📎", tone: "sky", title: "Przeanalizuj plik", sub: "pdf, docx, xlsx, csv, tekst", action: "attach" },
  { ico: "📁", tone: "mint", title: "Dodaj folder ze źródłami", sub: "GREGAI przeczyta go tylko tu", action: "sources" },
  { ico: "🧠", tone: "lilac", title: "Przemyśl trudną decyzję", sub: "plusy, minusy i ryzyko", fill: "Pomóż mi podjąć decyzję: " },
  { ico: "🌐", tone: "pink", title: "Co dzieje się w mojej sieci?", sub: "urządzenia i zasięg", fill: "status sieci" },
];

function buildWelcome(project) {
  const root = document.createElement("div");
  root.className = "chat-empty welcome";
  const chip = project ? "Projekt" : "Twój asystent";
  // 1.32.19 (przygotowanie pod open source): wcześniej powitanie z imieniem autora
  // wpisanym na trwałe - widoczne u KAŻDEGO, kto sklonuje repo. Generyczne powitanie,
  // żeby ekran startowy nie ujawniał cudzych danych osobowych.
  const head = project ? escapeHtml(project.title) : "Cześć!";
  const sub = project
    ? "Widzę tu tylko notatki tego projektu - nic innego się nie wmiesza."
    : "Jestem GREGAI. Zrób pierwszy krok, a poprowadzę Cię dalej.";
  // 1.31.0: nagłówek jak plansza z napisami filmowymi (etykieta + wielki tytuł),
  // a trzy kroki na start są widoczne od razu - to jest prawdziwa kolejność.
  root.innerHTML =
    `<div class="lt welcome-lt"><span class="lt-chip">${chip}</span><h2 class="lt-title welcome-title">${head}</h2></div>` +
    `<p class="welcome-sub">${sub}</p>` +
    `<ol class="welcome-steps welcome-path">` +
    `<li><span><b>Wybierz kafelek</b> albo napisz własne pytanie.</span></li>` +
    `<li><span><b>Dołącz plik lub folder</b>, jeśli chodzi o Twoje dokumenty.</span></li>` +
    `<li><span><b>Patrz, jak myślę</b>: każdy krok widać na żywo.</span></li>` +
    `</ol>` +
    `<div class="welcome-grid"></div>` +
    `<details class="welcome-help"><summary>Skróty i podpowiedzi</summary>` +
    `<p class="welcome-keys">Komendy: wpisz <kbd>/</kbd> na początku wiadomości, np. /diagnoza, /plan, /badaj, /lekcja (pełna lista: /pomoc).</p>` +
    `<p class="welcome-keys">Pliki i foldery dołączysz też z menu <span class="welcome-menuicon" aria-hidden="true">☰</span> w rogu; „Zatrzymaj” przerwie odpowiedź w każdej chwili.</p>` +
    `<p class="welcome-keys"><b>Skróty:</b> <kbd>/</kbd> pole rozmowy · <kbd>↑</kbd> ostatnia wiadomość · ` +
    `<kbd>Esc</kbd> zatrzymuje odpowiedź · <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd> Rozmowa, Węzły, Nadzorca</p>` +
    `</details>`;
  const grid = root.querySelector(".welcome-grid");
  for (const t of WELCOME_STARTERS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `welcome-tile tone-${t.tone}`;
    b.innerHTML = `<span class="welcome-ico" aria-hidden="true">${t.ico}</span><span class="welcome-tt">${escapeHtml(t.title)}</span><span class="welcome-ts">${escapeHtml(t.sub)}</span>`;
    b.addEventListener("click", () => {
      const input = document.getElementById("chat-input");
      if (t.action === "attach") { document.getElementById("chat-attach").click(); return; }
      if (t.action === "sources") {
        setChatDrawerOpen(true);
        // 1.25.0: sekcje szuflady są domyślnie zwinięte (1.24.0) - otwórz "Foldery".
        const src = document.querySelector("#chat-drawer details.d-src");
        if (src) src.open = true;
        const si = document.getElementById("sources-input");
        if (si) si.focus();
        return;
      }
      input.value = t.fill || "";
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      input.dispatchEvent(new Event("input"));
    });
    if (grid.children.length >= 3) b.classList.add("welcome-tile-extra");
    grid.appendChild(b);
  }
  // 1.25.0: na telefonie najpierw trzy kafelki; reszta po "Więcej pomysłów".
  if (grid.querySelector(".welcome-tile-extra")) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "welcome-more";
    more.textContent = "Więcej pomysłów";
    more.addEventListener("click", () => { grid.classList.add("show-all"); more.remove(); });
    grid.after(more);
  }
  return root;
}

// "Co dalej?" (1.22.0): duże przyciski z następnym krokiem pod odpowiedzią narzędzia.
// Znikają po kliknięciu i przy każdej nowej wiadomości; nie są zapisywane w rozmowie.
function clearNextSteps() {
  document.querySelectorAll(".next-steps").forEach((el) => el.remove());
}

function appendNextSteps(items) {
  const row = document.createElement("div");
  row.className = "next-steps";
  row.setAttribute("role", "group");
  row.setAttribute("aria-label", "Co dalej?");
  const lead = document.createElement("span");
  lead.className = "next-steps-lead";
  lead.textContent = "Co dalej?";
  row.appendChild(lead);
  for (const it of items.slice(0, 3)) {
    if (!it || typeof it.label !== "string") continue;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "next-step";
    b.textContent = it.label;
    b.addEventListener("click", () => {
      const input = document.getElementById("chat-input");
      const form = document.getElementById("chat-form");
      if (activeRun()) return;
      // 1.23.0 (audyt): nie kasujemy tego, co piszesz, i nie wysyłamy cudzych załączników
      // z gotowym zdaniem przycisku.
      if (input.value.trim()) {
        showBanner("Najpierw wyślij albo wyczyść to, co piszesz.", { info: true, ms: 3500 });
        return;
      }
      clearNextSteps();
      const chatId = currentChatId();
      const hasFiles = typeof chatAttachments !== "undefined" && chatAttachments.some((a) => a.chat === chatId);
      if (hasFiles && typeof it.say === "string") { input.value = it.say; input.dispatchEvent(new Event("input")); input.focus(); return; }
      input.value = typeof it.say === "string" ? it.say : (typeof it.fill === "string" ? it.fill : "");
      input.dispatchEvent(new Event("input"));
      if (typeof it.say === "string" && form) form.requestSubmit();
      else { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
    row.appendChild(b);
  }
  if (row.children.length > 1) appendToChat(row);
}

function buildBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  markAlertBubble(bubble, role, text);
  bubble.innerHTML = renderMarkdownLite(text);
  if (role === "assistant") addCopyButton(bubble, text);
  return bubble;
}

// 1.31.0 (kolor = ważność): odpowiedź zaczynająca się od alertu straży albo zadania
// stałego („🔔 ...”, router._finish) dostaje czerwony znacznik - to nie zwykła rozmowa.
function markAlertBubble(bubble, role, text) {
  if (role === "assistant" && typeof text === "string" && text.trimStart().startsWith("🔔")) bubble.classList.add("alarm");
}

function buildNote(text) {
  const el = document.createElement("div");
  el.className = "chat-return-note";
  el.textContent = text;
  return el;
}

// Odtworzenie rozmowy z zapisanych wiadomości (1.19.0: z kartami i z trwającą
// odpowiedzią). Opcje kart "tak/nie" są klikalne tylko w OSTATNIEJ karcie i
// tylko wtedy, gdy serwer nadal czeka na odpowiedź (pendingAction/Clarify).
function renderConversationMessages(conv, project) {
  const messages = document.getElementById("chat-messages");
  messages.innerHTML = "";
  if (!conv.messages.length && !conv.run) {
    messages.appendChild(buildWelcome(project));
    hideNewReplyChip();
    offerServerHistory();
    paintGuide(conv);
    return;
  }
  let lastCardEl = null;
  const lastMsg = conv.messages[conv.messages.length - 1];
  for (const m of conv.messages) {
    const bubbleEl = buildBubble(m.role, m.text);
    messages.appendChild(bubbleEl);
    // Odbiór odpowiedzi po zerwanym połączeniu: tylko pod OSTATNIĄ porażką.
    if (m === lastMsg && m.jobId && !conv.run && (m.failed || m.role === "user")) {
      try { attachResumeButton(conv, project, m, bubbleEl); } catch (e) { console.error("odbiór:", e); }
    }
    lastCardEl = null;
    if (m.card) {
      try {
        const el = buildChatCard(m.card);
        if (el) { messages.appendChild(el); lastCardEl = el; }
      } catch (e) { console.error("karta:", e); }
    }
    if (m.node) {
      try { const nodeEl = buildSuggestedNodeCard(m.node, m); if (nodeEl) messages.appendChild(nodeEl); } catch (e) { console.error("sugestia węzła:", e); }
    }
    if (m.note) messages.appendChild(buildNote(m.note));
  }
  messages.querySelectorAll(".chat-card-option").forEach((row) => {
    const live = lastCardEl && lastCardEl.contains(row) && !conv.run && (conv.pendingAction || conv.pendingClarify);
    if (live) return;
    row.classList.add("used");
    row.setAttribute("aria-disabled", "true");
    row.tabIndex = -1;
  });
  if (conv.run && conv.pendingEl) messages.appendChild(conv.pendingEl);
  messages.scrollTop = messages.scrollHeight;
  hideNewReplyChip();
  paintInputHint(conv);
}

// 1.24.0: gdy GREGAI czeka na "tak/nie", pole mówi to wprost.
function paintInputHint(conv) {
  const input = document.getElementById("chat-input");
  paintGuide(conv);
  if (!input || (conv && conv.run)) return; // trwa odpowiedź: zostaje "Czekam na odpowiedź…"
  input.placeholder = conv && conv.pendingAction ? "Wybierz „Tak” albo „Nie”" : "Napisz wiadomość…";
}

// 1.31.0 (prośba Grzegorza: "niech aplikacja bardziej prowadzi za rękę"): jedno
// zdanie pod polem rozmowy mówi, co zrobić TERAZ, a kolor mówi, czyj jest ruch -
// turkus: Twój następny krok, bursztyn: GREGAI czeka na Twoją decyzję, błękit:
// GREGAI pracuje albo to tylko informacja. Pusta rozmowa dodatkowo podświetla
// pole wpisywania (trzy błyski i spokój - bez animacji w nieskończoność).
function paintGuide(conv) {
  const el = document.getElementById("chat-guide");
  if (!el) return;
  const input = document.getElementById("chat-input");
  const row = document.getElementById("chat-form");
  const typed = !!(input && input.value.trim());
  const empty = !conv || (!conv.messages.length && !conv.run);
  let ton = "sygnal";
  let text;
  if (conv && conv.run) {
    text = "GREGAI pracuje. Każdy krok widzisz w dymku powyżej; Esc albo „Zatrzymaj” przerywa.";
    ton = "blekit";
  } else if (conv && conv.pendingAction) {
    text = "GREGAI czeka na Twoją decyzję: wybierz „Tak” albo „Nie” na karcie powyżej.";
    ton = "bursztyn";
  } else if (conv && conv.pendingClarify) {
    text = "GREGAI dopytuje: wybierz opcję na karcie albo odpowiedz własnymi słowami.";
    ton = "bursztyn";
  } else if (typed && input.value.trim().startsWith("/")) {
    // 1.32.2 (audyt tura 7): na ekranie dotykowym nie ma strzałek, a Enter robi nową linię.
    text = touchScreen()
      ? "Komenda: dotknij jej na liście; /pomoc pokazuje wszystkie."
      : "Komenda: wybierz z listy strzałkami i Enterem; /pomoc pokazuje wszystkie.";
  } else if (typed) {
    text = touchScreen()
      ? "Wysyłasz przyciskiem obok pola, Enter to nowa linia. GREGAI przemyśli każde pytanie krok po kroku."
      : "Enter wysyła, Shift+Enter to nowa linia. GREGAI przemyśli każde pytanie krok po kroku.";
  } else if (empty) {
    text = "Zacznij tutaj: napisz pytanie albo wybierz kafelek powyżej.";
  } else {
    text = "Dopytaj, popraw („nie o to”) albo zacznij nowy temat.";
    ton = "blekit";
  }
  if (el.textContent !== text) el.textContent = text;
  el.dataset.ton = ton;
  if (row) row.classList.toggle("zaproszenie", empty && !typed);
}

// --- Przewijanie rozmowy (1.18.0, audyt interfejsu): nowy dymek/karta
// przewija na dół TYLKO wtedy, gdy byłeś przy końcu (do 120 px) przed jego
// dodaniem. Kto przewinął w górę, żeby czytać historię, zostaje tam, a na dole
// panelu pojawia się mały przycisk "↓ Nowa odpowiedź". Własna wiadomość
// (force) przewija zawsze - właśnie ją wysłałeś, chcesz widzieć, co dalej.
const CHAT_NEAR_BOTTOM_PX = 120;

function chatNearBottom(messages) {
  return messages.scrollHeight - messages.scrollTop - messages.clientHeight < CHAT_NEAR_BOTTOM_PX;
}

function appendToChat(el, { force = false } = {}) {
  const messages = document.getElementById("chat-messages");
  const near = force || chatNearBottom(messages);
  messages.appendChild(el);
  if (near) {
    messages.scrollTop = messages.scrollHeight;
    hideNewReplyChip();
  } else {
    showNewReplyChip();
  }
}

function newReplyChip() {
  let chip = document.getElementById("chat-new-reply");
  if (chip) return chip;
  const messages = document.getElementById("chat-messages");
  if (!messages || !messages.parentElement) return null;
  chip = document.createElement("button");
  chip.type = "button";
  chip.id = "chat-new-reply";
  chip.className = "chat-new-reply hidden";
  chip.textContent = "↓ Nowa odpowiedź";
  chip.addEventListener("click", () => {
    messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
    hideNewReplyChip();
  });
  messages.insertAdjacentElement("afterend", chip);
  messages.addEventListener("scroll", () => { if (chatNearBottom(messages)) hideNewReplyChip(); }, { passive: true });
  return chip;
}

function showNewReplyChip() {
  const chip = newReplyChip();
  if (chip) chip.classList.remove("hidden");
}

function hideNewReplyChip() {
  const chip = document.getElementById("chat-new-reply");
  if (chip) chip.classList.add("hidden");
}

// --- Kopiuj odpowiedź (1.18.0): mały przycisk w dymku GREGAI, widoczny po
// najechaniu albo fokusie klawiaturą. navigator.clipboard działa tylko w
// "bezpiecznym kontekście" (localhost, https) - przez sieć domową po zwykłym
// http zostaje stara droga przez zaznaczenie i execCommand("copy").
function plainFromMarkdown(text) {
  return String(text ?? "")
    .replace(/^[ \t]*(?:`{3,}|~{3,})[^\n]*$/gm, "")
    .replace(/\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g, (_, t, a) => (a || t).trim())
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .trim();
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch (e) { /* niżej zapasowa droga */ }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.className = "offscreen-copy";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  area.remove();
  return ok;
}

function addCopyButton(bubble, text) {
  if (!text || !text.trim()) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "chat-copy";
  btn.setAttribute("aria-label", "Kopiuj odpowiedź");
  btn.title = "Kopiuj odpowiedź";
  btn.textContent = "Kopiuj";
  btn.addEventListener("click", async () => {
    const ok = await copyText(plainFromMarkdown(text));
    btn.textContent = ok ? "Skopiowano" : "Nie udało się";
    btn.classList.toggle("done", ok);
    setTimeout(() => { btn.textContent = "Kopiuj"; btn.classList.remove("done"); }, 1600);
  });
  bubble.classList.add("has-copy");
  bubble.appendChild(btn);
}

function updateChatProjectBadge() {
  // 1.31.0: nazwa rozmowy jest tytułem nagłówka (jak napis pod etykietą na planszy filmowej).
  const title = document.getElementById("chat-title");
  if (title) title.textContent = activeProject ? activeProject.title : "Ogólna rozmowa";
  const badge = document.getElementById("chat-project-badge");
  if (!badge) return;
  if (activeProject) {
    badge.textContent = activeProject.title;
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
    badge.textContent = "";
  }
}

function setActiveProject(project) {
  // 1.19.0: szkic pola wpisywania zostaje w rozmowie, w której go pisałeś -
  // dawniej niedokończony tekst szedł do nowo wybranej rozmowy.
  const input = document.getElementById("chat-input");
  const prev = activeConversation();
  if (input && !prev.run) prev.draft = input.value;
  activeProject = project;
  projectRestored = true;  // wybór użytkownika wygrywa z zapamiętanym
  // 1.32.2 (audyt tura 7): otwarty projekt przeżywa odświeżenie strony (tylko id, ta przeglądarka).
  try {
    if (project && project.id) localStorage.setItem("gregai_projekt", project.id);
    else localStorage.removeItem("gregai_projekt");
  } catch (e) { /* tryb prywatny: bez zapamiętania */ }
  const conv = activeConversation();
  conv.unread = false;
  renderConversationMessages(conv, project);
  updateChatProjectBadge();
  populateProjectList();
  if (input) {
    input.value = conv.run ? "" : (conv.draft || "");
    input.style.height = "auto";
    if (input.value) input.style.height = Math.min(input.scrollHeight, 100) + "px";
  }
  setChatInputLocked(!!conv.run);
  restoreProgressFor(conv);
  // Źródła i załączniki są indywidualne dla rozmowy (1.9.1): inna rozmowa
  // = inna lista, a chipy wgrane w poprzedniej nie idą z wiadomością tej.
  // 1.19.0: chipy NIE znikają przy przełączeniu - każdy należy do swojej
  // rozmowy (a.chat) i wraca razem z nią; wgrywany plik nadal blokuje wysyłkę.
  if (typeof loadSources === "function") loadSources();
  if (typeof chatAttachments !== "undefined") renderAttachments();
  if (typeof showReturnNote === "function") showReturnNote();
  if (document.body.classList.contains("segment-chat")) document.getElementById("chat-input").focus();
}

// Dwa segmenty, nigdy oba naraz: "chat" (Rozmowa, domyślny i główny) i
// "nodes" (Węzły, podkategoria osiągalna tylko z szyny w Rozmowie). Samo
// przełączenie klasy na body - widoczność obu segmentów i kanwy grafu
// (fizyka węzłów ma się nie liczyć, gdy nikt na nią nie patrzy) to CSS.
// Cztery przyciski (po dwa w każdym rogu - patrz index.html), ten sam stan:
// aktywny = widok, na którym właśnie jesteś, reszta to zwykłe linki dalej.
function setSwitchActive(id, active) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.classList.toggle("active", active);
  if (active) btn.setAttribute("aria-current", "true");
  else btn.removeAttribute("aria-current");
}

// Od 1.11.0 trzy segmenty: "chat", "nodes" i "debug" (Nadzorca, dawny /debug
// w tej samej aplikacji; skrót w adresie: /#nadzorca). Ten sam przełącznik z
// trzema ikonami w każdym segmencie (rail-/nodes-/debug-switch-*).
function setSegment(name) {
  const seg = name === "nodes" ? "nodes" : name === "debug" ? "debug" : "chat";
  // 1.19.0 (dostępność): kliknięty przełącznik znika razem ze starym segmentem,
  // więc fokus przechodzi na przełącznik nowego segmentu, nie ginie w <body>.
  const ae = document.activeElement;
  const fromSwitch = !!(ae && ae.closest && ae.closest(".segment-switch"));
  document.body.classList.toggle("segment-nodes", seg === "nodes");
  document.body.classList.toggle("segment-debug", seg === "debug");
  document.body.classList.toggle("segment-chat", seg === "chat");
  for (const prefix of ["rail", "nodes", "debug"]) {
    for (const s of ["chat", "nodes", "debug"]) setSwitchActive(`${prefix}-switch-${s}`, s === seg);
  }
  // Krążenie kamery w Węzłach (graph.setAutoOrbit) tylko, gdy ten segment jest
  // widoczny - pod schowanym płótnem nie ma po co liczyć klatek.
  if (typeof graph !== "undefined" && graph && graph.setAutoOrbit) graph.setAutoOrbit(seg === "nodes" && document.visibilityState === "visible");
  if (seg === "chat") {
    const input = document.getElementById("chat-input");
    if (!input.disabled) input.focus();
    else if (fromSwitch) document.getElementById("rail-switch-chat").focus();
    refreshModelBadge();
  } else {
    if (seg === "debug" && window.GregaiDebug) window.GregaiDebug.show();
    if (fromSwitch) {
      const target = document.getElementById(`${seg}-switch-${seg}`);
      if (target) target.focus();
    }
  }
  if (seg === "debug") { if (location.hash !== "#nadzorca") history.replaceState(null, "", "#nadzorca"); }
  else if (location.hash === "#nadzorca") history.replaceState(null, "", location.pathname);
}

function navigateToNodesSegment() {
  setSegment("nodes");
}

function initChat() {
  // Przełącznik Rozmowa/Węzły: ta sama para przycisków w rogu obu paneli
  // (patrz index.html #chat-rail/.rail-top i #nodes-topbar) - tylko
  // przycisk prowadzący do DRUGIEGO widoku ma nasłuch, bo ten na aktualnym
  // widoku jest już aktywny i kliknięcie niczego by nie zmieniło.
  for (const prefix of ["rail", "nodes", "debug"]) {
    for (const seg of ["chat", "nodes", "debug"]) {
      const btn = document.getElementById(`${prefix}-switch-${seg}`);
      if (btn) btn.addEventListener("click", () => setSegment(seg));
    }
  }
  if (location.hash === "#nadzorca") setSegment("debug");
  window.addEventListener("hashchange", () => { if (location.hash === "#nadzorca") setSegment("debug"); });
  document.addEventListener("visibilitychange", () => {
    if (typeof graph !== "undefined" && graph && graph.setAutoOrbit) {
      graph.setAutoOrbit(document.body.classList.contains("segment-nodes") && document.visibilityState === "visible");
    }
  });
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  input.addEventListener("input", () => paintGuide(activeConversation()));
  const stopBtn = document.getElementById("chat-stop");
  if (stopBtn) stopBtn.addEventListener("click", () => {
    const run = activeRun();
    if (!run) return;
    stopBtn.disabled = true;
    stopBtn.lastChild.textContent = "\n        Zatrzymuję…\n      ";
    run.cancel();
  });
  setupChatDrawer();
  setupProgressPill();
  const guardPill = document.getElementById("chat-guard-pill");
  if (guardPill) guardPill.addEventListener("click", () => setSegment("debug"));
  // 1.24.0: szuflada "po kolei" naprawdę po kolei - otwarcie jednej sekcji zamyka inne.
  document.querySelectorAll("#chat-drawer details.drawer-section").forEach((d) => {
    d.addEventListener("toggle", () => {
      if (!d.open) return;
      // "Postęp" (d-prog) zostaje: jest ukryty do pierwszego Namysłu i musi się wtedy pokazać rozwinięty.
      document.querySelectorAll("#chat-drawer details.drawer-section").forEach((o) => { if (o !== d && o.open && !o.classList.contains("d-prog")) o.open = false; });
    });
  });
  loadConversations();
  renderConversationMessages(activeConversation(), activeProject);

  // 1.18.0: Esc w trakcie odpowiedzi = "Zatrzymaj". Tylko gdy nic innego nie
  // czeka na Esc - otwarte okno tworzenia, szuflada albo dymek Namysłu mają
  // pierwszeństwo (zamykają się same, rozmowa liczy dalej). Faza przechwytywania
  // na window: stan paneli sprawdzamy, ZANIM ich własne obsługi Esc je zamkną
  // (inaczej zamknięcie szuflady Esc zatrzymywało też odpowiedź).
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !activeRun() || e.defaultPrevented) return;
    if (!document.body.classList.contains("segment-chat")) return;
    const modal = document.getElementById("create-modal-overlay");
    if (modal && modal.classList.contains("visible")) return;
    const drawer = document.getElementById("chat-drawer");
    if (drawer && !drawer.classList.contains("hidden")) return;
    if (document.querySelector(".namysl-popover:not(.hidden)")) return;
    if (stopBtn && !stopBtn.disabled) { e.preventDefault(); stopBtn.click(); }
  }, true);

  // 1.18.0: [[wikilinki]] w odpowiedziach są klikalne (i działają z
  // klawiatury: Enter/spacja) - otwierają notatkę w Węzłach. Jedno nasłuchiwanie
  // na całej liście wiadomości, bo dymki powstają i znikają przy każdej zmianie
  // rozmowy.
  const messagesEl = document.getElementById("chat-messages");
  const openWikilink = (el) => {
    const title = el.dataset.noteTitle || "";
    const node = nodeByTitle(title);
    if (!node) { showBanner(`Nie ma notatki „${title}” w grafie.`, { info: true, ms: 4000 }); return; }
    navigateToNodesSegment();
    if (typeof graph !== "undefined" && graph) graph.focusNode(node.id);
  };
  messagesEl.addEventListener("click", async (e) => {
    const link = e.target.closest(".chat-wikilink");
    if (link) { openWikilink(link); return; }
    // 1.19.0: "Kopiuj kod" przy bloku kodu - dosłowna treść bloku.
    const codeBtn = e.target.closest(".chat-code-copy");
    if (codeBtn) {
      const code = codeBtn.closest(".chat-code");
      const ok = await copyText(code ? code.querySelector("code").textContent : "");
      codeBtn.textContent = ok ? "Skopiowano" : "Nie udało się";
      setTimeout(() => { codeBtn.textContent = "Kopiuj kod"; }, 1600);
    }
  });
  messagesEl.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const link = e.target.closest(".chat-wikilink");
    if (link) { e.preventDefault(); openWikilink(link); }
  });

  // 1.18.0: brak internetu w przeglądarce to sygnał, że koryto pójdzie do
  // modelu lokalnego (KORYTO_LOKALNIE=bez_internetu) - znacznik to mówi od razu,
  // zamiast czekać na 30-sekundowy odczyt.
  window.addEventListener("online", refreshModelBadge);
  window.addEventListener("offline", refreshModelBadge);

  // Odświeżaj znacznik "MODEL AKTYWNY" / "SŁOWA KLUCZOWE" co 30 sekund (i po każdej odpowiedzi),
  // niezależnie od tego, który segment jest akurat widoczny, uruchamiane raz,
  // nie przy każdym wejściu do Rozmowy, żeby nie mnożyć interwałów.
  if (!modelBadgeInterval) {
    modelBadgeInterval = setInterval(refreshModelBadge, 30000); // znacznik zmienia się rzadko; każde odpytanie budzi serwer i Ollamę
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || activeRun()) return;
    // 1.19.0 (audyt): plik w trakcie wgrywania nie może po cichu przepaść -
    // wiadomość czeka, aż się wgra.
    if (chatAttachments.some((a) => a.status === "uploading" && a.chat === currentChatId())) {
      showBanner("Poczekaj chwilę, aż plik się wgra - wtedy wyślij.", { info: true, ms: 4000 });
      return;
    }
    input.value = "";
    input.style.height = "auto";
    sendChatMessage(text);
  });

  setupCommandPopover(input, form);

  input.addEventListener("keydown", (e) => {
    // Autokorekta/IME nie wysyła niedokończonego tekstu; na ekranie dotykowym
    // Enter robi nową linię (nie ma Shifta), wysyła przycisk (1.20.0).
    if (e.isComposing) return;
    if (e.key === "Enter" && !e.shiftKey && !window.matchMedia("(pointer: coarse)").matches) {
      e.preventDefault();
      form.requestSubmit();
      return;
    }
    // 1.19.0: strzałka w górę w pustym polu wstawia ostatnio wysłaną wiadomość
    // tej rozmowy - do poprawienia i wysłania jeszcze raz.
    if (e.key === "ArrowUp" && !input.value) {
      const last = [...activeConversation().messages].reverse().find((m) => m.role === "user");
      if (!last) return;
      e.preventDefault();
      input.value = last.raw || String(last.text || "").replace(/\n📎 .*$/s, "");
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 100) + "px";
      input.setSelectionRange(input.value.length, input.value.length);
    }
  });

  // 1.19.0: skróty klawiszowe. "/" (gdy nic nie piszesz) - do pola rozmowy;
  // Alt+Shift+1/2/3 - Rozmowa / Węzły / Nadzorca (samo Alt+cyfra przełącza karty
  // przeglądarki na Linuksie). e.code, bo Shift+1 daje "!" w e.key.
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    const digit = { Digit1: "chat", Digit2: "nodes", Digit3: "debug" }[e.code];
    if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && digit) {
      e.preventDefault();
      setSegment(digit);
      return;
    }
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Otwarta szuflada albo okno: "/" nic nie robi (nie wyciąga fokusu spod nich).
      const modal = document.getElementById("create-modal-overlay");
      if (modal && modal.classList.contains("visible")) return;
      const drawer = document.getElementById("chat-drawer");
      if (drawer && !drawer.classList.contains("hidden")) return;
      if (document.querySelector(".modal-overlay.visible")) return;
      e.preventDefault();
      if (!document.body.classList.contains("segment-chat")) setSegment("chat");
      if (!input.disabled) {
        input.focus();
        // 1.32.0: "/" w pustym polu od razu zaczyna komendę i pokazuje listę.
        if (!input.value) { input.value = "/"; input.dispatchEvent(new Event("input")); }
      }
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 100) + "px";
  });

  refreshModelBadge();
}

async function refreshModelBadge() {
  if (document.hidden) return; // ukryta karta: nie budzimy Ollamy co 30 s
  const badge = document.getElementById("chat-model-badge");
  const headerDot = document.getElementById("header-dot");
  try {
    const res = await gregaiFetch("/api/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.model_active) {
      badge.textContent = "Model na laptopie: działa";
      badge.className = "chat-model-badge active";
      headerDot.className = "header-dot active";
    } else {
      badge.textContent = "Model na laptopie: wyłączony";
      badge.className = "chat-model-badge fallback";
      headerDot.className = "header-dot fallback";
    }
    applyNetworkHint(badge);
    paintGuardPill(data);
  } catch (e) {
    paintGuardPill(null);
    badge.textContent = serverFailStreak > 1 ? `Brak połączenia (${serverFailStreak}×)` : "Brak połączenia";
    badge.className = "chat-model-badge offline";
    badge.title = "Serwer GREGAI nie odpowiada. Sprawdź, czy usługa działa.";
    headerDot.className = "header-dot";
  }
}

// Przeglądarka bez sieci: serwer (lokalny) dalej odpowiada, ale sieciowe etapy
// koryta nie - dopisek do znacznika zamiast osobnej kontrolki.
// 1.24.0: pigułka w nagłówku rozmowy, widoczna także na telefonie: czy straż
// pilnuje i ile z miesięcznego budżetu na Claude już poszło.
function paintGuardPill(data) {
  const pill = document.getElementById("chat-guard-pill");
  if (!pill) return;
  if (!data) {
    // 1.29.0 (kontrola): na telefonie to jedyny widoczny stan - brak serwera mówimy wprost.
    pill.textContent = "⚠️ Brak połączenia z GREGAI";
    pill.dataset.level = "bad";
    pill.classList.remove("hidden");
    return;
  }
  // 1.32.7 (Grzegorz): bez napisu o czuwaniu i bez licznika USD - pigułka pokazuje się tylko,
  // gdy coś wymaga uwagi (straż wyłączona albo z kłopotem, limit Claude wydany).
  // Wydatki dalej widać w zakładce Debug.
  const usd = data.usd && data.usd.limit_miesiac ? data.usd : null;
  const parts = [];
  let level = "warn";
  if (data.straz === false) parts.push("🛡️ Straż wyłączona");
  else if (data.straz_blad) parts.push("🛡️ Straż ma kłopot");
  if (usd && usd.miesiac >= usd.limit_miesiac) { parts.push("limit Claude wydany, odpowiada darmowe AI"); level = "bad"; }
  if (!parts.length) { pill.classList.add("hidden"); return; }
  pill.textContent = parts.join(" · ");
  pill.dataset.level = level;
  pill.classList.remove("hidden");
}

function applyNetworkHint(badge) {
  if (!badge) return;
  const offline = navigator.onLine === false;
  badge.classList.toggle("net-offline", offline);
  badge.title = offline ? "Brak internetu - odpowiada model lokalny na tym komputerze." : "";
  if (offline && !badge.textContent.includes("bez sieci")) badge.textContent += " · bez sieci";
}

function appendTypingIndicator() {
  const messages = document.getElementById("chat-messages");
  const empty = messages.querySelector(".chat-empty");
  if (empty) empty.remove();
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble assistant pending";
  // 1.18.0: czytnik ekranu nie ma ogłaszać każdego odświeżenia osi faz (co
  // ~1,5 s) i tykania licznika - dymek jest "zajęty", dopóki nie zniknie.
  bubble.setAttribute("aria-busy", "true");
  bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  appendToChat(bubble, { force: true });
  return bubble;
}

function appendChatBubble(role, text) {
  const messages = document.getElementById("chat-messages");
  const empty = messages.querySelector(".chat-empty");
  if (empty) empty.remove();
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  markAlertBubble(bubble, role, text);
  bubble.innerHTML = renderMarkdownLite(text);
  if (role === "assistant") addCopyButton(bubble, text);
  appendToChat(bubble, { force: role === "user" });
  return bubble;
}

function appendChatCard(card) {
  const el = buildChatCard(card);
  if (el) appendToChat(el);
  return el;
}

// Karta jako element (1.19.0): ten sam wygląd przy odpowiedzi na żywo i przy
// odtwarzaniu rozmowy (powrót do niej, odświeżenie strony).
function buildChatCard(card) {
  if (!card) return null;
  const el = document.createElement("div");
  el.className = "chat-card";
  // 1.31.0: kolor ważności karty (kadr.css) - rodzaj karty jako klasa ct-<rodzaj>.
  if (typeof card.type === "string" && /^[a-z_]{1,32}$/.test(card.type)) el.classList.add("ct-" + card.type);
  const rows = [];

  if (card.type === "network_status") {
    renderNetworkStatusCard(card, rows);
  } else if (card.type === "clarify") {
    el.classList.add("chat-card-clarify");
    renderClarifyCard(card, rows);
  } else if (card.type === "confirm") {
    el.classList.add("chat-card-clarify");
    renderConfirmCard(card, rows);
  } else if (card.type === "zadanie") {
    renderTaskCard(card, rows);
  } else if (card.type === "sysop") {
    renderSysopCard(card, rows);
  } else if (card.type === "market_quote") {
    renderMarketQuoteCard(card, rows);
  } else if (card.type === "market_history") {
    renderMarketHistoryCard(card, rows);
  } else if (card.type === "save_note") {
    renderSaveNoteCard(card, rows);
  } else if (card.type === "wiki_lookup") {
    renderWikiLookupCard(card, rows);
  } else if (card.type === "self_status") {
    renderSelfStatusCard(card, rows);
  } else if (card.type === "research_web") {
    renderResearchWebCard(card, rows);
  } else if (card.type === "weather") {
    renderWeatherCard(card, rows);
  } else if (card.type === "diagnoza") {
    renderDiagnosisCard(card, rows);
  } else if (card.type === "namysl") {
    el.classList.add("chat-card-namysl");
    renderNamyslCard(card, rows);
  } else if (card.type === "skrot") {
    // Karta odtworzona z pamięci przeglądarki: bez treści wyniku (1.19.0).
    rows.push(`<div class="chat-card-row chat-card-dim">${escapeHtml(card.label || "karta narzędzia")} (szczegóły tylko w trakcie rozmowy, nie są zapisywane w przeglądarce)</div>`);
  } else {
    if (Array.isArray(card.results)) {
      for (const r of card.results.slice(0, 5)) {
        const label = r.title || r.name || "";
        rows.push(`<div class="chat-card-row">${escapeHtml(label)}${r.source ? ": " + escapeHtml(r.source) : ""}</div>`);
      }
    }
    if (Array.isArray(card.items)) {
      for (const it of card.items.slice(0, 5)) {
        rows.push(`<div class="chat-card-row">${escapeHtml(it.title || "")}${it.reason ? ": " + escapeHtml(it.reason) : ""}</div>`);
      }
    }
    if (Array.isArray(card.devices)) {
      rows.push(`<div class="chat-card-row">${card.devices.length} ${pluralPl(card.devices.length, "urządzenie", "urządzenia", "urządzeń")} w sieci</div>`);
    }
    // Podsumowanie dnia i przegląd grafu: najbardziej połączone notatki i alerty sieci.
    if (Array.isArray(card.top_hubs) && card.top_hubs.length) {
      rows.push(`<div class="chat-card-section">Najbardziej połączone</div>`);
      for (const h of card.top_hubs.slice(0, 5)) {
        rows.push(`<div class="chat-card-row">${escapeHtml(h.title || "")} <span class="chat-card-dim">(${escapeHtml(h.connections ?? 0)} ${pluralPl(h.connections ?? 0, "połączenie", "połączenia", "połączeń")})</span></div>`);
      }
    }
    if (Array.isArray(card.network_alerts) && card.network_alerts.length) {
      rows.push(`<div class="chat-card-section">Alerty sieci</div>`);
      for (const a of card.network_alerts.slice(0, 3)) {
        rows.push(`<div class="chat-card-row chat-card-dim">${escapeHtml(alertText(a))}</div>`);
      }
    }
  }

  if (!rows.length) return; // nic wartego pokazania osobno, speech wystarczy
  el.innerHTML = rows.join("");

  if (card.type === "namysl") {
    // Zwinięta do jednej linii; kliknięcie rozwija pełny zapis faz.
    const toggle = el.querySelector(".namysl-card-toggle");
    const body = el.querySelector(".namysl-card-body");
    if (toggle && body) {
      const flip = () => {
        const open = el.classList.toggle("open");
        body.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
      };
      toggle.addEventListener("click", flip);
    }
  }

  if (card.type === "clarify" || card.type === "confirm") {
    el.querySelectorAll(".chat-card-option").forEach((row) => {
      const choose = () => {
        if (activeRun()) return; // już czeka na odpowiedź, nie dubluj wysyłki
        if (row.classList.contains("used")) return; // karta z wcześniejszej wymiany
        const text = row.dataset.clarifyText;
        if (!text) return;
        row.classList.add("chosen"); // widać, co wybrałeś, także po wyszarzeniu karty
        sendChatMessage(text);
      };
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.addEventListener("click", choose);
      row.addEventListener("keydown", onActivateKey(choose));
    });
  }

  return el;
}

// --- Karta "propozycja węzła": GREGAI rozpoznał w odpowiedzi fakt warty
// zapisania dla aktywnego projektu (agent/main.py: NOWY_WEZEL, parsowane z
// TEJ SAMEJ odpowiedzi rozmowy, bez drugiego zapytania do modelu) i czeka na
// decyzję. "Zapisz" woła ten sam /api/note/create co formularz Węzłów, z
// [[wikilinkiem]] do projektu, żeby węzeł wszedł do JEGO podgrafu (patrz
// agent/vault.py: project_scope) - "Odrzuć" nic nie wysyła, karta po prostu gaśnie.
function appendSuggestedNodeCard(suggestion, holder) {
  const el = buildSuggestedNodeCard(suggestion, holder);
  if (el) appendToChat(el);
  return el;
}

// 1.19.0: karta propozycji jest zapisana przy swojej wiadomości (holder.node),
// więc wraca po przełączeniu rozmowy i po odświeżeniu; decyzja (holder.nodeOutcome)
// też - zapisana albo odrzucona propozycja nie pokazuje znów przycisków.
function buildSuggestedNodeCard(suggestion, holder) {
  if (!suggestion || !suggestion.title || !suggestion.body) return null;
  const el = document.createElement("div");
  el.className = "chat-card chat-card-suggest";
  el.innerHTML = `
    <div class="chat-card-section">Zapisać jako węzeł w projekcie „${escapeHtml(suggestion.project || "")}”?</div>
    <div class="chat-card-suggest-title">${escapeHtml(suggestion.title)}</div>
    <div class="chat-card-suggest-body">${escapeHtml(suggestion.body)}</div>
    <div class="chat-card-suggest-actions">
      <button type="button" class="chat-card-suggest-btn save">Zapisz</button>
      <button type="button" class="chat-card-suggest-btn reject">Odrzuć</button>
    </div>
  `;

  const saveBtn = el.querySelector(".save");
  const rejectBtn = el.querySelector(".reject");
  const finish = (text, isError, remember = true) => {
    const actions = el.querySelector(".chat-card-suggest-actions");
    if (actions) actions.remove();
    const note = document.createElement("div");
    note.className = isError ? "chat-card-suggest-outcome text-danger" : "chat-card-dim chat-card-suggest-outcome";
    note.textContent = text;
    el.appendChild(note);
    if (holder && remember && !isError) { holder.nodeOutcome = text; saveConversations(); }
  };
  if (holder && holder.nodeOutcome) { finish(holder.nodeOutcome, false, false); return el; }
  rejectBtn.addEventListener("click", () => finish("Odrzucono."));
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    rejectBtn.disabled = true;
    saveBtn.textContent = "Zapisuję…";
    try {
      // 1.27.0 (audyt): karta mogła przeleżeć w przeglądarce, a projekt zmienić nazwę -
      // bierzemy AKTUALNY tytuł po id z grafu; znaki [ ] | # (stare tytuły) neutralizujemy.
      const live = suggestion.project_id && graphData && Array.isArray(graphData.nodes)
        ? graphData.nodes.find((n) => n.id === suggestion.project_id) : null;
      const projTitle = String((live && live.title) || suggestion.project || "").replace(/[\[\]|#]/g, " ").trim();
      const text = projTitle ? `${suggestion.body}\n\nNależy do: [[${projTitle}]]` : suggestion.body;
      const res = await gregaiFetch("/api/note/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: suggestion.title, type: "Note", text }),
      });
      const data = await res.json();
      if (data.error) {
        finish(`Błąd zapisu: ${data.error}`, true);
        return;
      }
      finish(suggestion.project ? `Zapisano w projekcie „${suggestion.project}”.` : "Zapisano.");
      refreshGraphData();
    } catch (err) {
      finish(`Błąd zapisu: ${err.message}`, true);
    }
  });
  return el;
}

// --- Karta network_status: urządzenia (online/offline, producent z MAC),
// stan routera (operator/sygnał/dane w tym miesiącu/wifi/bateria), ostatnie
// alerty. Mowa (chat bubble) ma tylko najważniejsze 2-3 zdania, cały
// szczegół jest tutaj, żeby nic z tego, co teraz oblicza network_status,
// nie przepadło (patrz tools.py/siec.py/router_bridge.py). -----------
function renderNetworkStatusCard(card, rows) {
  const devices = Array.isArray(card.devices) ? card.devices : [];
  if (devices.length) {
    const online = escapeHtml(card.online_count ?? devices.filter((d) => d.online).length);
    const total = escapeHtml(card.total_count ?? devices.length);
    rows.push(`<div class="chat-card-section">Urządzenia: ${online} z ${total} online</div>`);
    for (const d of devices.slice(0, 10)) {
      const dotClass = d.online ? "chat-card-dot online" : "chat-card-dot offline";
      const ip = escapeHtml(d.ip || "");
      const metaBits = [];
      if (d.vendor) metaBits.push(escapeHtml(d.vendor));
      if (d.online) {
        if (ip) metaBits.push(ip);
      } else {
        metaBits.push(d.last_seen ? `offline od ${escapeHtml(formatWhen(d.last_seen))}` : "offline");
      }
      const meta = metaBits.length
        ? `<div class="chat-card-device-meta">${metaBits.join(" · ")}</div>`
        : "";
      rows.push(
        `<div class="chat-card-row chat-card-device">` +
          `<div class="chat-card-device-head">` +
            `<span class="${dotClass}"></span>` +
            `<span class="chat-card-device-name">${escapeHtml(d.hostname || "(brak nazwy)")}</span>` +
          `</div>${meta}` +
        `</div>`
      );
    }
  }

  const r = card.router;
  if (r && !r.error) {
    const bits = [];
    if (r.operator) bits.push(escapeHtml(r.operator));
    if (r.network_type_label) bits.push(escapeHtml(r.network_type_label));
    if (r.wifi_ssid) bits.push(`Wi-Fi: ${escapeHtml(r.wifi_ssid)}`);
    if (r.month && r.month.download_mb != null) {
      bits.push(`${escapeHtml(r.month.download_mb)} MB ↓ / ${escapeHtml(r.month.upload_mb ?? 0)} MB ↑ (ten miesiąc)`);
    }
    if (r.battery_percent != null) bits.push(`Bateria: ${escapeHtml(String(r.battery_percent))}%`);
    if (bits.length) {
      rows.push(`<div class="chat-card-section">Router</div>`);
      rows.push(`<div class="chat-card-row">${bits.join(" · ")}</div>`);
    }
  } else if (r && r.error) {
    rows.push(`<div class="chat-card-row chat-card-dim">Router: ${escapeHtml(r.error)}</div>`);
  }

  const alerts = Array.isArray(card.alerts) ? card.alerts : [];
  if (alerts.length) {
    rows.push(`<div class="chat-card-section">Ostatnie alerty</div>`);
    for (const a of alerts.slice(0, 3)) {
      rows.push(`<div class="chat-card-row chat-card-dim">${escapeHtml(alertText(a))}</div>`);
    }
  }
}

// Liczba do pokazania człowiekowi: separator tysięcy spacją, 2 miejsca po
// przecinku (albo więcej dla groszowych krypto), bez wykładnika.
function fmtPrice(v) {
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  const dec = Math.abs(n) >= 1 ? 2 : 6;
  return n.toLocaleString("pl-PL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

// Karta "market_quote": od 1.30.20 dane to płaski słownik {symbol, price,
// currency} (krypto z Coinbase, reszta z Yahoo Finance) - jedno źródło prawdy,
// bez pól CSV Stooq (ten padł). Bez tej funkcji karta spadłaby do ogólnej
// ścieżki, która nie rozpoznaje tych pól, więc cena ginęłaby z karty.
function renderMarketQuoteCard(card, rows) {
  const data = card.data;
  if (!data || typeof data !== "object") return; // notowanie nieudane (ok=False): sama wypowiedź wystarcza
  const symbol = escapeHtml(card.symbol || data.symbol || data.base || card.query || "");
  rows.push(`<div class="chat-card-section">Notowanie${symbol ? ": " + symbol : ""}</div>`);
  // 1.30.20 (Yahoo/Coinbase): price+currency; zapas - stare pola CSV/amount.
  const price = data.price != null ? data.price : (data.amount != null ? data.amount : data.Close);
  const cur = data.currency || data.cur || "";
  if (price != null) {
    rows.push(`<div class="chat-card-row">Cena: <strong>${escapeHtml(fmtPrice(price))}${cur ? " " + escapeHtml(cur) : ""}</strong></div>`);
  }
  if (card.source) rows.push(`<div class="chat-card-row chat-card-dim">źródło: ${escapeHtml(card.source)}</div>`);
}

// Zwięzły wykres liniowy SVG z szeregu dziennego (bez żadnej biblioteki -
// czysty SVG, działa offline w WebView). `points`: [{t,o,h,l,c}]. Rysuje
// linię zamknięć, delikatne wypełnienie pod nią i podpisy min/max. Zwraca
// HTML (string) albo "" gdy za mało danych.
function sparklineSvg(points, opts) {
  if (!Array.isArray(points) || points.length < 2) return "";
  const W = 460, H = 150, padL = 6, padR = 6, padT = 10, padB = 18;
  const cs = points.map((p) => Number(p.c)).filter((v) => isFinite(v));
  if (cs.length < 2) return "";
  let lo = Math.min(...cs), hi = Math.max(...cs);
  if (hi === lo) { hi += 1; lo -= 1; }
  const n = points.length;
  const x = (i) => padL + (i * (W - padL - padR)) / (n - 1);
  const y = (v) => padT + (H - padT - padB) * (1 - (Number(v) - lo) / (hi - lo));
  let line = "", area = "";
  points.forEach((p, i) => {
    const px = x(i).toFixed(1), py = y(p.c).toFixed(1);
    line += (i ? "L" : "M") + px + " " + py + " ";
    area += (i ? "L" : "M") + px + " " + py + " ";
  });
  area += `L${x(n - 1).toFixed(1)} ${(H - padB).toFixed(1)} L${x(0).toFixed(1)} ${(H - padB).toFixed(1)} Z`;
  const up = cs[cs.length - 1] >= cs[0];
  const stroke = up ? "#39d98a" : "#ff6b6b";
  const fill = up ? "rgba(57,217,138,0.12)" : "rgba(255,107,107,0.12)";
  const cur = opts && opts.currency ? " " + escapeHtml(opts.currency) : "";
  return (
    `<svg class="mh-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="wykres ceny">` +
    `<path d="${area}" fill="${fill}" stroke="none"/>` +
    `<path d="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>` +
    `<text class="mh-tick" x="${padL}" y="${(padT + 2).toFixed(0)}">${escapeHtml(fmtPrice(hi))}${cur}</text>` +
    `<text class="mh-tick" x="${padL}" y="${(H - padB + 13).toFixed(0)}">${escapeHtml(fmtPrice(lo))}${cur}</text>` +
    `</svg>`
  );
}

// Karta "market_history" (1.30.20): miesięczny szereg z Yahoo - podsumowanie
// (otwarcie/zamknięcie/min/max/zmiana%) + wykres liniowy SVG. Pokazuje się i w
// bezpośrednim pytaniu o historię, i wpleciona w kartę Namysłu (card.wykresy).
function renderMarketHistoryCard(card, rows) {
  const data = card && card.data;
  if (!data || typeof data !== "object") return;
  const symbol = escapeHtml(card.symbol || data.symbol || card.query || "");
  const cur = data.currency || "";
  const chg = Number(data.change_pct);
  const chgTxt = isFinite(chg) ? `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "";
  const chgCls = isFinite(chg) ? (chg >= 0 ? "mh-up" : "mh-down") : "";
  rows.push(`<div class="chat-card-section">Historia${symbol ? ": " + symbol : ""}${data.days ? ` · ${data.days} dni` : ""}</div>`);
  const svg = sparklineSvg(data.points, { currency: cur });
  if (svg) rows.push(`<div class="mh-chart-wrap">${svg}</div>`);
  if (data.first != null && data.last != null) {
    rows.push(
      `<div class="chat-card-row">` +
      `otwarcie <strong>${escapeHtml(fmtPrice(data.first))}</strong> → ` +
      `zamknięcie <strong>${escapeHtml(fmtPrice(data.last))}</strong>${cur ? " " + escapeHtml(cur) : ""}` +
      (chgTxt ? ` <span class="${chgCls}">(${chgTxt})</span>` : "") +
      `</div>`
    );
  }
  const mm = [];
  if (data.min != null) mm.push(`min ${escapeHtml(fmtPrice(data.min))}`);
  if (data.max != null) mm.push(`max ${escapeHtml(fmtPrice(data.max))}`);
  if (mm.length) rows.push(`<div class="chat-card-row chat-card-dim">${mm.join(" · ")}</div>`);
  // Pochodne % policzone w kodzie (1.30.21) - pokazane wprost, żeby model i
  // człowiek widzieli te same liczby (max/min względem otwarcia, zmienność).
  const pctTxt = (v) => (v != null && isFinite(Number(v)) ? `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}%` : null);
  const der = [];
  const mv = pctTxt(data.max_vs_open_pct); if (mv) der.push(`max vs otwarcie ${mv}`);
  const nv = pctTxt(data.min_vs_open_pct); if (nv) der.push(`min vs otwarcie ${nv}`);
  if (data.avg_daily_abs_pct != null && isFinite(Number(data.avg_daily_abs_pct))) der.push(`śr. dzienna zmienność ${Number(data.avg_daily_abs_pct).toFixed(2)}%`);
  if (der.length) rows.push(`<div class="chat-card-row chat-card-dim">${der.join(" · ")}</div>`);
  if (card.source) rows.push(`<div class="chat-card-row chat-card-dim">źródło: ${escapeHtml(card.source)}</div>`);
}

// Karta "save_note" (1.30.22): potwierdzenie zapisania odpowiedzi jako węzła
// w grafie (type: Wiedza). Sama wypowiedź już to mówi, karta daje zwięzły ślad
// (tytuł + plik + adnotacja o niezweryfikowaniu). Błąd/brak treści: bez karty
// treści, wypowiedź wystarcza.
function renderSaveNoteCard(card, rows) {
  if (!card.title) return;
  rows.push(`<div class="chat-card-section">Dodane do grafu${card.duplicate ? " (już było)" : ""}</div>`);
  rows.push(`<div class="chat-card-row"><strong>${escapeHtml(card.title)}</strong> <span class="chat-card-dim">· węzeł typu Wiedza</span></div>`);
  if (card.file) rows.push(`<div class="chat-card-row chat-card-dim">${escapeHtml(card.file)}</div>`);
  rows.push(`<div class="chat-card-row chat-card-dim">informacje niezweryfikowane - sprawdź, zanim na nich polegniesz</div>`);
}

// Karta "wiki_lookup": bez niej, tak jak market_quote wyżej, karta spada
// do ogólnej ścieżki, która nie rozpoznaje query/title/extract/found/
// cached/source - cały zapisany do banku wiedzy opis ginął, a w czacie
// zostawało tylko PIERWSZE ZDANIE (speech = _first_sentence(extract)).
// Nieudane wyszukanie (found=false) nie dostaje karty: speech już mówi
// dokładnie, co się stało (brak artykułu, WARP rozłączony, błąd sieci).
// Audyt 2026-10-19 runda 2: dokończone, ten sam wzorzec co market_quote.
function renderWikiLookupCard(card, rows) {
  if (!card.found || !card.extract) return;
  const title = escapeHtml(card.title || card.query || "");
  rows.push(`<div class="chat-card-section">Wikipedia${card.cached ? " · z banku wiedzy" : ""}</div>`);
  if (title) rows.push(`<div class="chat-card-row"><strong>${title}</strong></div>`);
  // pre-wrap (.chat-card-prose): extract ma własne podziały akapitów, a dla
  // notatki z cache (bank wiedzy) kończy się linią "Źródło: …" - zwykły
  // chat-card-row by je sklził w jedną linię bez odstępów.
  rows.push(`<div class="chat-card-row chat-card-prose">${escapeHtml(card.extract)}</div>`);
  // Przy świeżym pobraniu (nie z cache) adres źródła jest osobnym polem
  // (card.source) - przy cache jest już wpisany w samym extract (patrz
  // tools.py:_save_wiki_note), więc tu nie dubluje się.
  if (card.source) rows.push(`<div class="chat-card-row chat-card-dim">${escapeHtml(card.source)}</div>`);
}

// Karta "self_status": liczby i wnioski (routes/topic_words/wiki_notes/
// pending_questions/journal_notes/pct/conclusions) są już CAŁE w mowie
// (speech = wszystkie "parts" + "conclusions" z tools.py:self_status w
// jednej, pełnej wypowiedzi, nie tylko streszczenie jak w network_status) -
// jedyne pole, o którym mowa w ogóle nie wspomina, to most_recent_route.
// Dlatego ta karta pokazuje tylko to jedno pole, zamiast powtarzać resztę
// drugi raz w innej formie.
function renderSelfStatusCard(card, rows) {
  const r = card.most_recent_route;
  if (!r || !r.tool) return;
  rows.push(`<div class="chat-card-section">Ostatnio wyuczony wzorzec</div>`);
  const words = Array.isArray(r.words) && r.words.length
    ? ` <span class="chat-card-dim">(${r.words.map(escapeHtml).join(", ")})</span>`
    : "";
  rows.push(`<div class="chat-card-row"><strong>${escapeHtml(r.tool)}</strong>${words}</div>`);
  if (r.example) rows.push(`<div class="chat-card-row chat-card-dim">„${escapeHtml(r.example)}”</div>`);
}

// Karta "research_web": bez niej, karta spada do ogólnej ścieżki wyżej, która
// szuka card.results[].title/name + card.results[].source - research_web
// wypełnia results[].title i .snippet (NIE .source), więc generyczna ścieżka
// pokazywała gołe tytuły bez żadnej treści, a fragment wyniku (snippet z
// DuckDuckGo) nigdzie się nie pojawiał - mowa wspomina tylko tytuł PIERWSZEGO
// wyniku, bez jego treści, więc pozostałe 4 wyniki były całkowicie bez opisu.
// Audyt 2026-10-19 (runda 3): dokończone, ten sam wzorzec co market_quote/wiki_lookup.
function renderResearchWebCard(card, rows) {
  if (!Array.isArray(card.results) || !card.results.length) return; // błąd albo brak wyników: sama wypowiedź już to mówi
  // 1.30.11: wyniki z sieci jako czytelne kafelki-źródła (tytuł-odnośnik, fragment,
  // domena), zamiast gołych linijek. Tytuł klikalny TYLKO gdy adres jest http(s)
  // (bez tego ryzyko javascript:); otwiera się w nowej karcie.
  rows.push(`<div class="chat-card-section">Z internetu</div>`);
  rows.push(`<div class="web-results">`);
  for (const r of card.results.slice(0, 5)) {
    const title = escapeHtml(r.title || "(bez tytułu)");
    let host = "", safeUrl = "";
    if (r.url && /^https?:\/\//i.test(r.url)) {
      safeUrl = r.url;
      try { host = new URL(r.url).hostname.replace(/^www\./, ""); } catch (_) { host = ""; }
    }
    const head = safeUrl
      ? `<a class="web-title" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<div class="web-title">${title}</div>`;
    const snippet = r.snippet ? `<div class="web-snippet">${escapeHtml(r.snippet)}</div>` : "";
    const src = host ? `<div class="web-source"><span class="web-source-ico" aria-hidden="true"></span>${escapeHtml(host)}</div>` : "";
    rows.push(`<div class="web-result">${head}${snippet}${src}</div>`);
  }
  rows.push(`</div>`);
}

// 1.32.0: komendy ukośnikowe - podpowiedzi po wpisaniu "/" na początku pola. Lista
// z serwera (/api/komendy, agent/komendy.py: jedno źródło), wczytana raz, leniwie.
let cmdList = null;
let cmdPromise = null;
let cmdIndex = 0;

function touchScreen() {
  try { return window.matchMedia("(pointer: coarse)").matches; } catch (e) { return false; }
}

function foldText(s) {
  return String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/ł/g, "l");
}

// 1.32.2 (audyt tura 7): JEDNA wspólna obietnica wczytania. Dawniej drugi znak wpisany w
// trakcie wczytywania dostawał od razu rozwiązane "return", malował się od nowa, znów
// wołał wczytanie... w nieskończonej pętli bez oddania sterowania: karta zamarzała.
function loadCommands() {
  if (cmdList) return Promise.resolve(cmdList);
  if (!cmdPromise) {
    cmdPromise = gregaiFetch("/api/komendy")
      .then((res) => res.json())
      .then((data) => { cmdList = Array.isArray(data.komendy) ? data.komendy : []; return cmdList; })
      .catch(() => { cmdPromise = null; return null; });
  }
  return cmdPromise;
}

function cmdMatches(value) {
  const m = /^\/(\S*)$/.exec(value || "");
  if (!m || !cmdList) return [];
  const q = foldText(m[1]);
  return cmdList.filter((c) => foldText(c.nazwa).startsWith(q));
}

function hideCommandPopover() {
  const pop = document.getElementById("cmd-popover");
  if (pop) { pop.classList.add("hidden"); pop.innerHTML = ""; }
}

function chooseCommand(c, input) {
  input.value = "/" + c.nazwa + (c.argument ? " " : "");
  hideCommandPopover();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  paintGuide(activeConversation());
}

function paintCommandPopover(input) {
  const pop = document.getElementById("cmd-popover");
  if (!pop) return;
  if (!/^\/\S*$/.test(input.value || "")) { hideCommandPopover(); return; }
  if (!cmdList) {
    // Maluj ponownie tylko wtedy, gdy lista naprawdę przyszła (błąd sieci = bez listy, bez pętli).
    loadCommands().then((got) => { if (got && cmdList) paintCommandPopover(input); });
    return;
  }
  const list = cmdMatches(input.value);
  if (!list.length) { hideCommandPopover(); return; }
  cmdIndex = Math.min(cmdIndex, list.length - 1);
  pop.innerHTML = "";
  list.forEach((c, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "cmd-item" + (i === cmdIndex ? " active" : "");
    b.setAttribute("role", "option");
    b.setAttribute("aria-selected", i === cmdIndex ? "true" : "false");
    b.innerHTML = `<span class="cmd-name">${escapeHtml(c.skladnia)}</span><span class="cmd-desc">${escapeHtml(c.opis)}</span>`;
    b.addEventListener("mousedown", (e) => e.preventDefault()); // fokus zostaje w polu
    b.addEventListener("click", () => chooseCommand(c, input));
    pop.appendChild(b);
  });
  pop.classList.remove("hidden");
  // 1.32.2 (audyt tura 7): lista zawsze NAD polem wpisywania, liczona od jego prawdziwej
  // pozycji - stałe "bottom" w CSS nachodziło na pole i Wyślij, gdy podpowiedź pod polem
  // zawija się na telefonie w dwie linie.
  const form = document.getElementById("chat-form");
  const parent = pop.offsetParent;
  if (form && parent) {
    const gap = parent.getBoundingClientRect().bottom - form.getBoundingClientRect().top + 8;
    pop.style.bottom = Math.max(0, Math.round(gap)) + "px";
  }
}

function setupCommandPopover(input, form) {
  input.addEventListener("input", () => { cmdIndex = 0; paintCommandPopover(input); });
  input.addEventListener("blur", () => setTimeout(hideCommandPopover, 120));
  // Faza capture: strzałki/Enter/Tab obsługujemy, ZANIM zwykły Enter wyśle "/pl".
  input.addEventListener("keydown", (e) => {
    const pop = document.getElementById("cmd-popover");
    if (!pop || pop.classList.contains("hidden")) return;
    const list = cmdMatches(input.value);
    if (!list.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      e.stopImmediatePropagation();
      cmdIndex = (cmdIndex + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length;
      paintCommandPopover(input);
    } else if (e.key === "Enter" || e.key === "Tab") {
      const exact = list.find((c) => "/" + c.nazwa === input.value.trim());
      // Pełna nazwa komendy bez argumentu + Enter = wyślij od razu (np. /pomoc).
      if (e.key === "Enter" && exact && !exact.argument) { hideCommandPopover(); return; }
      e.preventDefault();
      e.stopImmediatePropagation();
      chooseCommand(list[cmdIndex] || list[0], input);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      hideCommandPopover();
    }
  }, true);
  form.addEventListener("submit", hideCommandPopover);
}

// 1.32.0: karta diagnozy internetu (agent/diagnoza.py) - warstwa po warstwie.
function renderDiagnosisCard(card, rows) {
  if (!Array.isArray(card.warstwy) || !card.warstwy.length) return;
  rows.push(`<div class="chat-card-section">Internet krok po kroku</div>`);
  for (const l of card.warstwy) {
    const cls = l.ok === true ? "diag-ok" : l.ok === false ? "diag-bad" : "diag-skip";
    const state = l.ok === true ? "OK" : l.ok === false ? "BŁĄD" : "-";
    rows.push(`<div class="chat-card-row diag-row ${cls}"><span class="diag-state">${state}</span>` +
      `<span class="diag-name">${escapeHtml(l.nazwa || "")}</span>` +
      `<span class="diag-detail">${escapeHtml(l.szczegoly || "")}</span>` +
      (l.rada && l.ok === false ? `<code class="diag-fix">${escapeHtml(l.rada)}</code>` : "") + `</div>`);
  }
}

// 1.30.31: pogoda z Open-Meteo (agent/pogoda.py) - teraz, dni i godziny dzisiaj co 3 h.
function renderWeatherCard(card, rows) {
  if (!Array.isArray(card.dni) || !card.dni.length) return; // błąd: sama wypowiedź mówi, co nie wyszło
  rows.push(`<div class="chat-card-section">Pogoda: ${escapeHtml(card.miasto || card.query || "")}</div>`);
  const num = (v, unit) => (v === null || v === undefined || v === "") ? "?" : escapeHtml(String(v)) + unit;
  if (card.teraz && typeof card.teraz === "object") {
    const t = card.teraz;
    rows.push(`<div class="chat-card-row">Teraz: <strong>${num(t.temp, "°C")}</strong>${t.odczuwalna != null ? " (odczuwalna " + num(t.odczuwalna, "°C") + ")" : ""}${t.opis ? ", " + escapeHtml(t.opis) : ""}${t.wiatr != null ? ", wiatr " + num(t.wiatr, " km/h") : ""}</div>`);
  }
  const names = ["Dziś", "Jutro", "Pojutrze"];
  card.dni.slice(0, 3).forEach((d, i) => {
    rows.push(`<div class="chat-card-row">${names[i] || escapeHtml(d.data || "")}: ${num(d.min, "")} - ${num(d.max, "°C")}${d.opis ? ", " + escapeHtml(d.opis) : ""}${d.opady_proc != null ? ", opady " + num(d.opady_proc, "%") : ""}${d.wiatr_max != null ? ", wiatr do " + num(d.wiatr_max, " km/h") : ""}</div>`);
  });
  if (Array.isArray(card.godziny) && card.godziny.length) {
    rows.push(`<div class="chat-card-section">Dziś godzinowo</div>`);
    for (const h of card.godziny.slice(0, 8)) {
      rows.push(`<div class="chat-card-row">${escapeHtml(h.godz || "")}: ${num(h.temp, "°C")}${h.opady_proc != null ? ", opady " + num(h.opady_proc, "%") : ""}${h.wiatr != null ? ", wiatr " + num(h.wiatr, " km/h") : ""}${h.opis ? ", " + escapeHtml(h.opis) : ""}</div>`);
    }
  }
  const d0 = card.dni[0] || {};
  if (d0.wschod) rows.push(`<div class="chat-card-row chat-card-dim">Słońce: wschód ${escapeHtml(d0.wschod)}, zachód ${escapeHtml(d0.zachod || "?")}</div>`);
  rows.push(`<div class="chat-card-row chat-card-dim">źródło: ${escapeHtml(card.source || "open-meteo.com")}</div>`);
}

// --- Namysł (1.9.0, agent/namysl.py) ------------------------------------

const NAMYSL_PHASE_LABELS = {
  rozpoznanie: "Rozpoznanie",
  zbieranie: "Zbieranie materiału",
  szkic: "Szkic odpowiedzi",
  krytyka: "Krytyka",
  poprawa: "Poprawa",
  sprawdzenie: "Sprawdzenie",
};
const NAMYSL_PHASES = ["rozpoznanie", "zbieranie", "szkic", "krytyka", "poprawa", "sprawdzenie"];

function formatSeconds(s) {
  // Audyt 1.32.1: zaokrąglamy PRZED podziałem (59,96 s dawało „60 s”, 119,6 s - „1m 60s”)
  // i po polsku, z przecinkiem.
  const n = Math.max(0, Number(s) || 0);
  if (n < 9.95) return `${n.toFixed(1).replace(".", ",")} s`;
  const whole = Math.round(n);
  if (whole < 60) return `${whole} s`;
  const m = Math.floor(whole / 60);
  return `${m}m ${String(whole % 60).padStart(2, "0")}s`;
}

// Karta "Jak myślałem" pod odpowiedzią: ten sam zapis, który leciał na żywo,
// tylko już kompletny - fazy (kto, ile), źródła, uwagi recenzenta i
// sprawdzenia. Zwinięta, żeby nie przykrywać odpowiedzi; rozwijana klikiem.
function renderNamyslCard(card, rows) {
  const fazy = Array.isArray(card.fazy) ? card.fazy : [];
  const n = fazy.filter((f) => !(f.uwaga || "").startsWith("pominięta")).length;
  const who = [...new Set(fazy.map((f) => f.kto).filter(Boolean))];
  // Czas od wysłania (klient_s, mierzony w przeglądarce) jest tym, co czuje
  // użytkownik; czas serwera (czas_s, od startu Namysłu) dopisany tylko, gdy
  // różni się o więcej niż 3 s - wtedy coś między nimi warto wyjaśnić.
  const fazySum = fazy.reduce((acc, f) => acc + (Number(f.sekund) || 0), 0);
  const shown = (typeof card.klient_s === "number") ? card.klient_s : card.czas_s;
  let czas = formatSeconds(shown);
  if (typeof card.klient_s === "number" && typeof card.czas_s === "number" && Math.abs(card.czas_s - card.klient_s) > 3) {
    czas += ` (namysł na serwerze ${formatSeconds(card.czas_s)}, fazy ${formatSeconds(fazySum)})`;
  }
  // 1.30.20: wykresy z market_history pokazujemy WPROST (nie chowamy pod "Jak
  // myślałem") - to treść analizy, którą użytkownik chce zobaczyć od razu.
  if (Array.isArray(card.wykresy) && card.wykresy.length) {
    for (const ch of card.wykresy.slice(0, 3)) {
      const chartRows = [];
      renderMarketHistoryCard(ch, chartRows);
      if (chartRows.length) rows.push(`<div class="chat-card-subcard">${chartRows.join("")}</div>`);
    }
  }
  // 1.30.13: nagłówek-przycisk + oś czasu (.ntl-*), wspólna z narracją na żywo.
  // Odznaka skupienia (1.30.22): waga uwagi 1-4 nadana tej wiadomości. 3-4
  // pokazujemy wprost (ważne/krytyczne); 1-2 to codzienność, bez odznaki.
  const skupLabels = { 3: "skupienie 3/4", 4: "skupienie 4/4" };
  const skupBadge = (card.skupienie && skupLabels[card.skupienie])
    ? `<span class="ntl-skup ntl-skup-${card.skupienie}">${skupLabels[card.skupienie]}</span>` : "";
  rows.push(
    `<button type="button" class="namysl-card-toggle" aria-expanded="false">` +
      `<span class="ntl-title">Jak myślałem</span>` +
      skupBadge +
      `<span class="ntl-meta">${escapeHtml(`${n} ${pluralPl(n, "faza", "fazy", "faz")}`)}${who.length ? " · " + escapeHtml(who.join(", ")) : ""}</span>` +
      `<span class="ntl-timer">${escapeHtml(czas)}</span>` +
      `<span class="namysl-card-chevron">›</span></button>`
  );
  const body = [];
  if (card.cel) body.push(`<div class="ntl-goal">${escapeHtml(card.cel)}${card.rodzaj ? ` <span class="ntl-who">${escapeHtml(card.rodzaj)}</span>` : ""}</div>`);
  if (fazy.length) {
    const steps = fazy.map((f) => {
      const st = (f.uwaga || "").startsWith("pominięta") ? "skip" : "done";
      const sub = f.uwaga ? `<div class="ntl-sub">${escapeHtml(f.uwaga)}</div>` : "";
      const whoTag = f.kto ? `<span class="ntl-who">${escapeHtml(f.kto)}</span>` : "";
      const t = f.sekund ? `<span class="ntl-time">${escapeHtml(formatSeconds(f.sekund))}</span>` : `<span class="ntl-time"></span>`;
      return `<li class="ntl-step ${st}"><span class="ntl-dot"></span>` +
        `<div class="ntl-body"><div class="ntl-name">${escapeHtml(NAMYSL_PHASE_LABELS[f.nazwa] || f.nazwa)}</div>${sub}${whoTag}</div>${t}</li>`;
    }).join("");
    body.push(`<ol class="ntl-steps">${steps}</ol>`);
  }
  const foot = [];
  const chipRow = (label, items) => `<div class="ntl-foot-row"><span class="ntl-foot-label">${label}</span>${items.map((z) => `<span class="ntl-chip">${escapeHtml(z)}</span>`).join("")}</div>`;
  if (Array.isArray(card.pytania) && card.pytania.length) foot.push(chipRow("Pytania pomocnicze", card.pytania));
  if (Array.isArray(card.zrodla) && card.zrodla.length) foot.push(chipRow("Źródła", card.zrodla));
  if (Array.isArray(card.problemy) && card.problemy.length) foot.push(chipRow("Uwagi recenzenta", card.problemy));
  if (Array.isArray(card.uwagi) && card.uwagi.length) foot.push(chipRow("Uwagi sprawdzenia", card.uwagi));
  if (card.pulapki) foot.push(`<div class="ntl-foot-row"><span class="ntl-foot-label">Pułapki</span><span class="ntl-foot-text">${escapeHtml(card.pulapki)}</span></div>`);
  if (card.powod) foot.push(`<div class="ntl-foot-row ntl-dim">Dlaczego namysł: ${escapeHtml(card.powod)}${card.material_prywatny ? (card.material_do_sieci ? " · materiał prywatny poszedł do sieciowych AI (Twoja zgoda w ustawieniach)" : " · materiał prywatny liczony tylko lokalnie") : ""}</div>`);
  if (foot.length) body.push(`<div class="ntl-foot">${foot.join("")}</div>`);
  rows.push(`<div class="namysl-card-body" hidden>${body.join("")}</div>`);
}

// Oś faz na żywo. Rysowana w dymku "pisze…" z listy zdarzeń backendu
// (GET /api/chat/progress). Stan każdej fazy wynika ze zdarzeń
// start/koniec/pominieta; opis bieżącej fazy to ostatnie zdarzenie.
function renderNamyslLive(container, events, elapsedMs, forceFinished = false) {
  if (!container || !events.length) return;
  let live = container.querySelector(".namysl-live");
  if (!live) {
    live = document.createElement("div");
    live.className = "namysl-live";
    container.appendChild(live);
  }
  const first = events[0];
  const phases = (first && Array.isArray(first.fazy) && first.fazy.length) ? first.fazy : NAMYSL_PHASES;
  const labels = Object.assign({}, NAMYSL_PHASE_LABELS, (first && first.labels) || {});
  const state = {};
  const sub = {};
  const secs = {};
  const who = {};  // 1.30.13: kto (dostawca) robił fazę - do ramki "kto" i nagłówka
  const acts = {}; // 1.30.15: konkretne podkroki fazy (etykiety zdarzeń "info") - oś na żywo
  let current = null;
  let last = null;
  for (const ev of events) {
    if (!ev || !ev.faza) continue;
    last = ev;
    if (ev.faza === "namysl") continue;
    if (ev.kto) who[ev.faza] = ev.kto;
    if (ev.etap === "start") { state[ev.faza] = "active"; current = ev.faza; sub[ev.faza] = ev.label; }
    else if (ev.etap === "koniec") { state[ev.faza] = "done"; sub[ev.faza] = ev.label; secs[ev.faza] = ev.sekund; if (current === ev.faza) current = null; }
    else if (ev.etap === "pominieta") { state[ev.faza] = "skipped"; sub[ev.faza] = ev.detail; }
    else if (ev.etap === "info") { sub[ev.faza] = ev.label; if (ev.label) (acts[ev.faza] = acts[ev.faza] || []).push(ev.label); }
  }
  // 1.18.0: "zakończony" także wtedy, gdy wywołujący WIE, że odpowiedź już
  // przyszła (forceFinished), a ostatnie zdarzenie "namysl/koniec" jeszcze nie
  // dotarło - inaczej panel "Postęp" zostawał na zawsze "w toku".
  const finished = forceFinished || (last && last.faza === "namysl" && last.etap === "koniec");
  // 1.30.13: dla fazy AKTYWNEJ pokazujemy bogatszy, bieżący opis (last.detail),
  // a nie samą etykietę - to on jest "podarunkiem", zdaniami.
  if (current && last && last.detail && last.faza === current) sub[current] = last.detail;
  // Kto brał udział (do nagłówka), w kolejności pojawiania się.
  const whoSeen = [];
  for (const f of phases) { if (who[f] && !whoSeen.includes(who[f])) whoSeen.push(who[f]); }
  const head = `<div class="ntl-head"><span class="ntl-title">${finished ? "Namysł zakończony" : "Namysł w toku"}</span>` +
    (whoSeen.length ? `<span class="ntl-meta">${escapeHtml(whoSeen.join(", "))}</span>` : "") +
    `<span class="ntl-timer">${escapeHtml(formatSeconds(elapsedMs / 1000))}</span></div>`;
  // 1.30.13 (zgłoszenie Grzegorza): oś "rośnie" z postępem - pokazujemy TYLKO fazy,
  // które już się zaczęły (active/done/skipped). Dalsze są schowane, aż ruszą.
  const list = `<ol class="ntl-steps">` + phases.filter((f) => state[f]).map((f) => {
    const st = state[f] === "active" ? "active" : state[f] === "skipped" ? "skip" : "done";
    // 1.30.15: jeśli faza ma konkretne podkroki (np. zbieranie: "Szukam w sieci: …",
    // "Sprawdzam notowanie: …"), pokaż je rozpisane; inaczej jedno-liniowy opis fazy.
    const a = acts[f];
    let detail;
    if (a && a.length) {
      const shown = a.slice(-8);
      detail = `<div class="ntl-acts">` + shown.map((x, i) =>
        `<div class="ntl-act${st === "active" && i === shown.length - 1 ? " now" : ""}">${escapeHtml(x)}</div>`).join("") + `</div>`;
    } else {
      detail = sub[f] ? `<div class="ntl-sub">${escapeHtml(sub[f])}</div>` : "";
    }
    const whoTag = who[f] ? `<span class="ntl-who">${escapeHtml(who[f])}</span>` : "";
    const t = secs[f] != null ? `<span class="ntl-time">${escapeHtml(formatSeconds(secs[f]))}</span>`
            : (st === "active" ? `<span class="ntl-time">…</span>` : `<span class="ntl-time"></span>`);
    return `<li class="ntl-step ${st}"><span class="ntl-dot"></span>` +
      `<div class="ntl-body"><div class="ntl-name">${escapeHtml(labels[f] || f)}</div>${detail}${whoTag}</div>${t}</li>`;
  }).join("") + `</ol>`;
  // 1.17.16 (zgłoszenie Grzegorza): oś faz odświeża się co ~1,5 s i za każdym
  // razem przewijała rozmowę na sam dół - w trakcie Namysłu nie dało się
  // przeczytać historii. Przewijamy tylko, gdy użytkownik i tak był przy końcu
  // (do 120 px od dołu) PRZED podmianą treści; kto przewinął wyżej, zostaje tam.
  const scroller = container.parentElement;
  const wasNearBottom = !scroller || (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight) < 120;
  live.innerHTML = head + list;
  if (scroller && wasNearBottom) scroller.scrollTop = scroller.scrollHeight;
}

// --- Panel "Postęp" (1.16.2): szuflada w panelu "Ta rozmowa" + pigułka w
// nagłówku. Ten sam strumień zdarzeń Namysłu co .namysl-live w dymku
// "pisze..." (poll() niżej woła renderNamyslLive() DRUGI raz, na inny
// kontener) - nic tu nie zgaduje faz na nowo, tylko pokazuje ten sam
// przebieg w miejscu, które zostaje widoczne i po tym, jak dymek zniknie. ---
let pillHideTimer = null;
// 1.17.9 (zgłoszenie Grzegorza: licznik Namysłu "2..3..5..7..9"): czas na
// plakietce i na osi faz odświeżał się tylko wtedy, gdy wracał odczyt postępu
// (co ~2 s), więc skakał o dwie sekundy. Osobny tykacz co sekundę liczy od
// chwili startu zapytania; odczyt postępu tylko podaje mu punkt odniesienia.
let pillTickTimer = null;
let pillStartedAt = 0;

function stopPillTick() {
  if (pillTickTimer) { clearInterval(pillTickTimer); pillTickTimer = null; }
}

function tickPillTimers() {
  const secs = (Date.now() - pillStartedAt) / 1000;
  const timer = document.getElementById("progress-pill-timer");
  if (timer) timer.textContent = formatSeconds(secs);
  document.querySelectorAll(".namysl-live-timer").forEach((el) => { el.textContent = formatSeconds(secs); });
}

function resetProgressPanel() {
  if (pillHideTimer) { clearTimeout(pillHideTimer); pillHideTimer = null; }
  stopPillTick();
  const live = document.getElementById("drawer-progress-live");
  if (live) live.innerHTML = "";
  const empty = document.getElementById("drawer-progress-empty");
  if (empty) empty.classList.remove("hidden");
  const section = document.getElementById("drawer-progress");
  if (section) section.classList.add("hidden");
  setDrawerCount("drawer-count-prog", 0);
  const pill = document.getElementById("progress-pill");
  if (pill) { pill.classList.add("hidden"); pill.classList.remove("done"); }
}

// Po przełączeniu rozmowy (1.19.0): panel "Postęp" i plakietka pokazują
// postęp TEJ rozmowy - dawniej zostawały fazy Namysłu z poprzedniej.
function restoreProgressFor(conv) {
  resetProgressPanel();
  const p = conv && conv.progress;
  if (!p || !p.events || !p.events.length) return;
  const elapsed = p.finished ? p.elapsedMs : Date.now() - p.startedAt;
  renderProgressPanel(p.events, elapsed, !!p.finished);
  if (p.finished) {
    const pill = document.getElementById("progress-pill");
    if (pill) pill.classList.add("hidden");
    if (pillHideTimer) { clearTimeout(pillHideTimer); pillHideTimer = null; }
  }
}

function renderProgressPanel(events, elapsedMs, finished) {
  if (!events.length) return;
  renderNamyslLive(document.getElementById("drawer-progress-live"), events, elapsedMs, !!finished);
  const empty = document.getElementById("drawer-progress-empty");
  if (empty) empty.classList.add("hidden");
  const section = document.getElementById("drawer-progress");
  if (section) section.classList.remove("hidden");
  const doneCount = events.filter((e) => e && e.etap === "koniec" && e.faza !== "namysl").length;
  setDrawerCount("drawer-count-prog", doneCount);

  const pill = document.getElementById("progress-pill");
  const label = document.getElementById("progress-pill-label");
  const timer = document.getElementById("progress-pill-timer");
  if (pill && label && timer) {
    pill.classList.remove("hidden");
    pill.classList.toggle("done", !!finished);
    // 1.18.0: plakietka mówi, KTÓRA faza trwa, nie tylko że coś trwa.
    const phase = finished ? "" : currentPhaseLabel(events);
    label.textContent = finished ? "Namysł zakończony" : (phase ? `Namysł: ${phase}` : "Namysł w toku");
    timer.textContent = formatSeconds(elapsedMs / 1000);
    pillStartedAt = Date.now() - elapsedMs;
    if (finished) stopPillTick();
    else if (!pillTickTimer) pillTickTimer = setInterval(tickPillTimers, 1000);
    // Po zakończeniu plakietka znika sama po chwili (zgłoszenie Grzegorza,
    // 1.17.3) - pełny zapis zostaje w panelu "Postęp". Nowa wiadomość
    // (resetProgressPanel) i tak ją czyści, więc timer jest tylko wygodą.
    if (pillHideTimer) { clearTimeout(pillHideTimer); pillHideTimer = null; }
    if (finished) pillHideTimer = setTimeout(() => { pill.classList.add("hidden"); pillHideTimer = null; }, 6000);
  }
}

function currentPhaseLabel(events) {
  const first = events[0];
  const labels = Object.assign({}, NAMYSL_PHASE_LABELS, (first && first.labels) || {});
  let current = null;
  for (const ev of events) {
    if (!ev || !ev.faza || ev.faza === "namysl") continue;
    if (ev.etap === "start") current = ev.faza;
    else if (ev.etap === "koniec" && current === ev.faza) current = null;
  }
  return current ? (labels[current] || current) : "";
}

function setupProgressPill() {
  const pill = document.getElementById("progress-pill");
  if (!pill) return;
  pill.addEventListener("click", () => {
    setChatDrawerOpen(true);
    const section = document.getElementById("drawer-progress");
    if (section) section.open = true;
  });
}

// --- Załączniki (spinacz): wgrane pliki czekają jako chipy i idą z
// następną wiadomością (payload.files). Treść pliku nigdy nie trafia do
// wiadomości - serwer czyta ją sam z data/wgrane (agent/analiza.py).
const chatAttachments = []; // {name, size, status}

function renderAttachments() {
  const box = document.getElementById("chat-attachments");
  if (!box) return;
  const chat = currentChatId();
  box.innerHTML = chatAttachments.map((a, i) => (a.chat !== chat ? "" :
    `<span class="chat-attachment ${a.status === "uploading" ? "uploading" : a.status === "failed" ? "failed" : ""}" title="${escapeHtml(a.error || a.name)}">` +
      `<span class="chat-attachment-name">${escapeHtml(a.name)}</span>` +
      `<span class="chat-attachment-size">${escapeHtml(a.status === "uploading" ? "wgrywam…" : a.status === "failed" ? (a.error ? String(a.error).slice(0, 60) : "błąd") : formatBytes(a.size))}</span>` +
      `<button type="button" class="chat-attachment-remove" data-index="${i}" aria-label="Usuń załącznik">×</button></span>`)
  ).join("");
  box.querySelectorAll(".chat-attachment-remove").forEach((btn) => {
    btn.addEventListener("click", () => { chatAttachments.splice(Number(btn.dataset.index), 1); renderAttachments(); });
  });
}

function formatBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] || "");
    r.onerror = () => reject(r.error || new Error("odczyt pliku"));
    r.readAsDataURL(file);
  });
}

// Id rozmowy dla Źródeł i wgranych (1.9.1): slug projektu albo "ogolna" -
// dokładnie to, co /api/chat dostaje jako `project` (agent/sources.py:
// chat_id). Każda rozmowa ma własne foldery i własny katalog wgranych.
function currentChatId() {
  return activeProject && activeProject.id ? activeProject.id : "ogolna";
}

async function uploadAttachment(file) {
  const entry = { name: file.name, size: file.size, status: "uploading", chat: currentChatId() };
  chatAttachments.push(entry);
  renderAttachments();
  // 1.29.0 (kontrola): za duży plik odrzucamy od razu, zanim telefon zakoduje 30 MB.
  if (file.size > 25 * 1024 * 1024) {
    entry.status = "failed";
    entry.error = "za duży (najwyżej 25 MB)";
    renderAttachments();
    return;
  }
  try {
    const data_base64 = await readFileBase64(file);
    const res = await gregaiFetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat: entry.chat, name: file.name, data_base64 }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    entry.name = data.name; // nazwa nadana przez serwer (data + bezpieczna nazwa)
    entry.size = data.size;
    entry.status = "ok";
  } catch (e) {
    entry.status = "failed";
    entry.error = e && e.message ? e.message : "nie udało się wgrać";
  }
  renderAttachments();
}

function setupAttachments() {
  const btn = document.getElementById("chat-attach");
  const input = document.getElementById("chat-file-input");
  if (!btn || !input) return;
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...(input.files || [])];
    input.value = "";
    for (const f of files) await uploadAttachment(f);
  });
}

// --- Ustawienia Namysłu (serwer: data/namysl.json) ------------------------
let namyslSettings = { tryb: "zawsze", material_do_sieci: false };

function paintNamyslButton() {
  const btn = document.getElementById("namysl-btn");
  const label = document.getElementById("namysl-btn-label");
  if (!btn || !label) return;
  // 1.32.7: jeden tryb - dokładne myślenie, zawsze włączone.
  label.textContent = "Dokładne myślenie";
  btn.classList.add("on");
}

async function loadNamyslSettings() {
  try {
    const res = await gregaiFetch("/api/namysl/settings");
    const data = await res.json();
    if (data && !data.error) namyslSettings = data;
  } catch (e) { /* bez ustawień zostaje dokładne myślenie, bez zgody */ }
  const consent = document.getElementById("namysl-consent");
  if (consent) consent.checked = !!namyslSettings.material_do_sieci;
  paintNamyslButton();
}

async function saveNamyslSettings(patch) {
  const status = document.getElementById("namysl-status");
  try {
    const res = await gregaiFetch("/api/namysl/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    namyslSettings = data;
    paintNamyslButton();
    if (status) status.textContent = "Zapisane.";
    setTimeout(() => { if (status && status.textContent === "Zapisane.") status.textContent = ""; }, 2500);
  } catch (e) {
    if (status) status.textContent = "Nie udało się zapisać: " + (e && e.message ? e.message : "błąd");
  }
}

function setupNamyslControl() {
  const btn = document.getElementById("namysl-btn");
  const pop = document.getElementById("namysl-popover");
  const consent = document.getElementById("namysl-consent");
  if (!btn || !pop) return;
  const close = () => { pop.classList.add("hidden"); btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = pop.classList.toggle("hidden") === false;
    btn.setAttribute("aria-expanded", String(open));
    if (open && consent) consent.focus();  // 1.29.0: fokus w środku okienka
  });
  pop.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || pop.classList.contains("hidden")) return;
    const inside = pop.contains(document.activeElement);
    close();
    if (inside) btn.focus();  // 1.29.0: Esc wraca na przycisk, nie gubi fokusu
  });
  if (consent) consent.addEventListener("change", () => saveNamyslSettings({ material_do_sieci: consent.checked }));
  loadNamyslSettings();
}

// --- "Gdzie skończyliśmy" (serwer: agent/rozmowa.py, 1.10.0) ------------------
// Po przerwie (>= 2 h od ostatniej tury tej rozmowy) jeden przyciemniony dymek
// z 1-3 zdaniami z ostatniego streszczenia: cel, ostatnio, następny krok. Bez
// modelu, więc natychmiast; raz na otwarcie rozmowy (nie przy każdej wiadomości).
const returnNoteShown = new Set();

async function showReturnNote() {
  const chat = currentChatId();
  if (returnNoteShown.has(chat)) return;
  returnNoteShown.add(chat);
  try {
    const res = await gregaiFetch(`/api/rozmowa/powrot?chat=${encodeURIComponent(chat)}`);
    const data = await res.json();
    if (!data || !data.pokaz || !data.tekst || chat !== currentChatId()) return;
    const messages = document.getElementById("chat-messages");
    const empty = messages.querySelector(".chat-empty");
    if (empty) empty.remove();
    const el = document.createElement("div");
    el.className = "chat-return-note";
    el.textContent = data.tekst;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  } catch (e) { /* brak notki o powrocie to nie błąd rozmowy */ }
}

// --- Rozmowa z innego urządzenia (1.23.0) ------------------------------------
// localStorage jest per przeglądarka. Gdy ta rozmowa jest tu pusta, a serwer
// pamięta jej tury (np. pisałeś z laptopa, a teraz z telefonu), proponujemy
// jednym dotknięciem je wczytać. Odpowiedzi narzędzi serwer trzyma tylko jako
// skrót, więc tak też się pokażą.
const serverHistoryOffered = new Set();

async function offerServerHistory() {
  const chat = currentChatId();
  const project = activeProject;
  const conv = activeConversation();
  if (serverHistoryOffered.has(chat) || conv.messages.length || conv.run) return;
  serverHistoryOffered.add(chat);
  let turns = [];
  try {
    const res = await gregaiFetch(`/api/rozmowa/tury?chat=${encodeURIComponent(chat)}`);
    const data = await res.json().catch(() => ({}));
    turns = Array.isArray(data.tury) ? data.tury : [];
  } catch (e) { return; }
  if (!turns.length || chat !== currentChatId() || conv.messages.length || conv.run) return;
  const messages = document.getElementById("chat-messages");
  const box = document.createElement("div");
  box.className = "chat-return-note server-history";
  const txt = document.createElement("span");
  txt.textContent = `Ta rozmowa ma ${turns.length} wiadomości zapisanych w GREGAI (np. z innego urządzenia). `;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "next-step";
  btn.textContent = "Pokaż je tutaj";
  btn.addEventListener("click", () => {
    if (conv.messages.length || conv.run) { box.remove(); return; }
    for (const t of turns) {
      const text = t.tool ? "(odpowiedź narzędzia - pełna treść została na urządzeniu, na którym padło pytanie)" : String(t.tekst || "");
      if (text) convPush(conv, { role: t.role === "user" ? "user" : "assistant", text });
    }
    saveConversations();
    if (activeConversation() === conv) renderConversationMessages(conv, project);
  });
  box.append(txt, btn);
  messages.insertBefore(box, messages.firstChild);
}

// --- Źródła (serwer: data/sources.json, agent/sources.py) -----------------
function renderSources(status, forChat) {
  const list = document.getElementById("sources-list");
  if (!list) return;
  // Odpowiedź z innej rozmowy (użytkownik przełączył wątek, zanim wróciła)
  // nie może nadpisać listy bieżącej. Porównujemy id z chwili ZAPYTANIA, nie
  // echo serwera (serwer może je znormalizować).
  if (forChat && forChat !== currentChatId()) return;
  const rows = (status && Array.isArray(status.foldery)) ? status.foldery : [];
  if (!rows.length) {
    list.innerHTML = `<li class="empty">Ta rozmowa nie ma jeszcze folderów. Dodaj np. ~/Dokumenty/Faktury, a GREGAI będzie mógł czytać i analizować pliki stamtąd - tylko w tej rozmowie.</li>`;
  } else {
    // Pełna ścieżka w podpowiedzi; na liście początek skrócony do "…/", żeby
    // widoczny był KONIEC (nazwa folderu), bo to po nim się go rozpoznaje.
    const short = (path) => {
      const parts = String(path || "").split("/").filter(Boolean);
      return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : path;
    };
    list.innerHTML = rows.map((r) =>
      `<li class="${r.ok ? "" : "bad"}" title="${escapeHtml(r.ok ? r.sciezka : r.sciezka + " - " + r.why)}"><span class="sources-path">${escapeHtml(short(r.sciezka))}</span>` +
      `<button type="button" class="sources-remove" data-path="${escapeHtml(r.sciezka)}" aria-label="Usuń źródło">×</button></li>`
    ).join("");
    list.querySelectorAll(".sources-remove").forEach((b) => b.addEventListener("click", () => changeSources({ usun: b.dataset.path })));
  }
  renderDrawerUploads(status);
  const st = document.getElementById("sources-status");
  if (st) {
    st.classList.remove("bad");
    st.textContent = (status && Array.isArray(status.wgrane) && status.wgrane.length)
      ? `Wgrane w tej rozmowie: ${status.wgrane.length} ${pluralPl(status.wgrane.length, "plik", "pliki", "plików")}.`
      : "";
  }
}

async function loadSources() {
  const chat = currentChatId();
  try {
    const res = await gregaiFetch(`/api/sources?chat=${encodeURIComponent(chat)}`);
    const data = await res.json();
    if (!data.error) renderSources(data, chat);
  } catch (e) { /* szyna bez źródeł to nie błąd rozmowy */ }
}

async function changeSources(payload) {
  const st = document.getElementById("sources-status");
  const chat = currentChatId();
  try {
    const res = await gregaiFetch("/api/sources", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ chat }, payload)),
    });
    const data = await res.json();
    if (data.status) renderSources(data.status, chat);
    if (st) {
      st.classList.toggle("bad", !data.ok);
      st.textContent = data.ok ? (payload.dodaj ? "Dodano. W tej rozmowie GREGAI może czytać pliki z tego folderu." : "Usunięto.") : (data.why || data.error || "Nie udało się.");
    }
    return !!data.ok;
  } catch (e) {
    if (st) { st.classList.add("bad"); st.textContent = "Brak połączenia z GREGAI."; }
    return false;
  }
}

// --- Panel "Ta rozmowa" (1.12.0, trzy paski w prawym górnym rogu): wszystko
// podczepione do bieżącej rozmowy - Źródła, wgrane pliki, pamięć rozmowy - i
// kosz usuwający rozmowę razem z jej plikami. ---
function setChatDrawerOpen(open) {
  const drawer = document.getElementById("chat-drawer");
  const btn = document.getElementById("chat-menu-btn");
  if (!drawer || !btn) return;
  const wasOpen = !drawer.classList.contains("hidden");
  drawer.classList.toggle("hidden", !open);
  btn.setAttribute("aria-expanded", String(open));
  if (open) { loadSources(); loadDrawerMemory(); }
  // 1.19.0 (dostępność): otwarta szuflada (role=dialog) dostaje fokus, a po
  // zamknięciu fokus wraca do przycisku menu - dawniej Tab chodził po
  // kafelkach ukrytych pod szufladą.
  if (open && !wasOpen) {
    const close = document.getElementById("chat-drawer-close");
    if (close) close.focus();
  } else if (!open && wasOpen && drawer.contains(document.activeElement)) {
    btn.focus();
  }
}

async function loadDrawerMemory() {
  const el = document.getElementById("drawer-memory");
  if (!el) return;
  const chat = currentChatId();
  try {
    const res = await gregaiFetch(`/api/rozmowa/powrot?chat=${encodeURIComponent(chat)}`);
    const d = await res.json();
    if (chat !== currentChatId()) return;
    const sm = d && d.streszczenie;
    const text = sm && typeof sm === "object" ? (sm.streszczenie || "") : (typeof sm === "string" ? sm : "");
    const turns = sm && typeof sm === "object" ? sm.tur : null;
    el.classList.toggle("empty", !text);
    setDrawerCount("drawer-count-mem", turns || 0);
    el.textContent = text
      ? text + (turns ? `\n\n(${turns} ${pluralPl(turns, "tura zapisana", "tury zapisane", "tur zapisanych")} w tej rozmowie)` : "")
      : "GREGAI jeszcze nie streścił tej rozmowy - robi to w tle co kilka wymian.";
  } catch (e) { el.textContent = ""; }
}

function setDrawerCount(id, n) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = String(n);
  el.classList.toggle("zero", !n);
}

function renderDrawerUploads(status) {
  const ul = document.getElementById("drawer-uploads");
  if (!ul) return;
  const files = status && Array.isArray(status.wgrane) ? status.wgrane : [];
  setDrawerCount("drawer-count-up", files.length);
  setDrawerCount("drawer-count-src", status && Array.isArray(status.foldery) ? status.foldery.length : 0);
  ul.innerHTML = files.length
    ? files.map((n) => `<li title="${escapeHtml(n)}">📎 ${escapeHtml(n)}</li>`).join("")
    : `<li class="empty">Brak. Dołącz plik spinaczem przy polu wpisywania - zostanie tylko w tej rozmowie.</li>`;
}

async function deleteConversation(project) {
  const key = project ? project.id : null;
  const label = project ? project.title : "Ogólna rozmowa";
  const target = conversations.get(conversationKey(project));
  if (target && target.run) {
    alert(target === activeConversation()
      ? "Najpierw zatrzymaj trwającą odpowiedź (przycisk Zatrzymaj)."
      : `W rozmowie „${label}” trwa jeszcze odpowiedź. Otwórz ją i zatrzymaj odpowiedź albo poczekaj, aż się skończy.`);
    return;
  }
  const what = project
    ? `Usunąć rozmowę „${label}” razem z jej plikami? Zniknie historia, streszczenie, wgrane pliki i lista źródeł tej rozmowy. Notatka projektu w Węzłach i Twoje foldery zostają.`
    : "Wyczyścić Ogólną rozmowę razem z jej plikami? Zniknie historia, streszczenie, wgrane pliki i lista źródeł. Notatki i Twoje foldery zostają.";
  if (!confirm(what)) return;
  const chat = project ? project.id : "ogolna";
  try {
    const res = await gregaiFetch("/api/rozmowa/usun", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat }),
    });
    const d = await res.json();
    if (!d.ok) { alert(d.error || "Nie udało się usunąć rozmowy."); return; }
  } catch (e) { alert("Brak połączenia z GREGAI - rozmowa nie została usunięta."); return; }
  forgetConversation(project);
  for (let i = chatAttachments.length - 1; i >= 0; i--) if (chatAttachments[i].chat === chat) chatAttachments.splice(i, 1);
  renderAttachments();
  returnNoteShown.delete(chat);
  if ((activeProject ? activeProject.id : null) === key) {
    renderConversationMessages(activeConversation(), activeProject);
    loadSources();
    loadDrawerMemory();
    const note = document.querySelector(".chat-return-note");
    if (note) note.remove();
  }
  setChatDrawerOpen(false);
}

function setupChatDrawer() {
  const btn = document.getElementById("chat-menu-btn");
  const close = document.getElementById("chat-drawer-close");
  const del = document.getElementById("drawer-delete");
  if (btn) btn.addEventListener("click", () => {
    const drawer = document.getElementById("chat-drawer");
    setChatDrawerOpen(drawer.classList.contains("hidden"));
  });
  if (close) close.addEventListener("click", () => setChatDrawerOpen(false));
  // 1.19.0: Tab krąży w obrębie otwartej szuflady (jak w oknie dialogowym).
  const drawerEl = document.getElementById("chat-drawer");
  if (drawerEl) drawerEl.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    // Tylko to, co naprawdę da się zogniskować: widoczne, i nie w zwiniętym
    // <details> (poza samym <summary>) - inaczej "ostatni" element był ukryty
    // i Tab uciekał z szuflady.
    const items = [...drawerEl.querySelectorAll("button, [href], input, select, textarea, summary, [tabindex]:not([tabindex='-1'])")]
      .filter((el) => {
        if (el.disabled || !el.getClientRects().length) return false;
        const closed = el.closest("details:not([open])");
        return !closed || (el.tagName === "SUMMARY" && el.parentElement === closed);
      });
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  if (del) del.addEventListener("click", () => deleteConversation(activeProject));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    // Esc zamyka tylko wierzchnią warstwę (1.20.0): nad szufladą stoi okno tworzenia.
    const modal = document.getElementById("create-modal-overlay");
    if (modal && modal.classList.contains("visible")) return;
    setChatDrawerOpen(false);
  });
}

function setupSources() {
  const form = document.getElementById("sources-form");
  const input = document.getElementById("sources-input");
  if (!form || !input) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = input.value.trim();
    if (!path) return;
    if (await changeSources({ dodaj: path })) input.value = "";
  });
  loadSources();
}

function alertText(a) {
  const who = a.hostname || a.ip || "nieznane urządzenie";
  if (a.type === "urzadzenie_wrocilo") return `„${who}” wróciło po ${a.absent_days} dniach`;
  if (a.type === "nowe_urzadzenie") return `Nowe w sieci: „${who}”`;
  return who;
}

// --- Karta "confirm": GREGAI chce wykonać zmianę w systemie i pyta o zgodę.
// Dwa klikalne wiersze wysyłają "tak"/"nie" jako zwykłą wiadomość (ten
// sam mechanizm co clarify), a backend rozpoznaje je po pending_action.
function renderConfirmCard(card, rows) {
  const desc = revealHidden(card.arg ? `${card.tool} | ${card.arg}` : card.tool || "");
  // Polecenie w osobnym bloku, wiernie: sekcja karty ma wersaliki i rozstrzelone
  // litery, a wielkość liter w poleceniu ma znaczenie (-r a -R, -f a -F).
  // 1.24.0: najpierw zdanie po ludzku, polecenie dopiero po rozwinięciu.
  rows.push(`<div class="chat-card-row chat-card-ask">Zrobię to: <b>${escapeHtml(card.label || "zmiana w systemie")}</b>. Zgadzasz się?</div>`);
  rows.push(`<details class="chat-card-details"><summary>Pokaż dokładne polecenie</summary><pre class="chat-card-pre chat-card-cmd">${escapeHtml(desc)}</pre></details>`);
  if (Array.isArray(card.steps) && card.steps.length) {
    rows.push(`<div class="chat-card-row chat-card-dim">Dotychczas: ${card.steps.length} ${pluralPl(card.steps.length, "krok wykonany", "kroki wykonane", "kroków wykonanych")}</div>`);
  }
  rows.push(
    `<div class="chat-card-yesno">` +
    `<div class="chat-card-row chat-card-option yes" data-clarify-text="tak" title="Wykonaj">` +
      `<span class="chat-card-option-num">✓</span><span>Tak, zrób to</span></div>` +
    `<div class="chat-card-row chat-card-option no" data-clarify-text="nie" title="Anuluj">` +
      `<span class="chat-card-option-num">✕</span><span>Nie</span></div>` +
    `</div>`
  );
}

// --- Karta "zadanie": przebieg pętli agenta krok po kroku (narzędzie,
// poziom, wynik), żeby było widać PROCES, nie tylko odpowiedź.
function renderTaskCard(card, rows) {
  rows.push(`<div class="chat-card-section">Zadanie: ${escapeHtml(card.status || "")}</div>`);
  const steps = Array.isArray(card.steps) ? card.steps : [];
  steps.forEach((s, i) => {
    const mark = s.ok === false ? "✕" : "✓";
    const tier = s.tier && s.tier !== "read" ? ` <span class="chat-card-dim">[${escapeHtml(s.tier)}]</span>` : "";
    rows.push(`<div class="chat-card-row">${i + 1}. ${mark} <code>${escapeHtml(s.tool)}${s.arg ? " | " + escapeHtml(s.arg) : ""}</code>${tier}` +
      (s.summary ? `<div class="chat-card-dim">${escapeHtml(s.summary)}</div>` : "") + `</div>`);
  });
}

// --- Karta "sysop": surowe wyjście narzędzia systemowego (logi, lista
// usług, polecenie), w stałej szerokości, przewijalne.
function renderSysopCard(card, rows) {
  if (!card.output) return;
  rows.push(`<div class="chat-card-section">${escapeHtml(card.tool || "system")}</div>`);
  rows.push(`<pre class="chat-card-pre">${escapeHtml(String(card.output).slice(0, 6000))}</pre>`);
}

// --- Karta clarify: dwa konteksty do wyboru, gdy pytanie jest naprawdę
// dwuznaczne między dwoma narzędziami (patrz capabilities.check_ambiguity).
// Sama treść jest już w mowie (chat bubble), to tylko wizualne
// wyróżnienie opcji, żeby wybór był czytelny na pierwszy rzut oka.
function renderClarifyCard(card, rows) {
  const options = Array.isArray(card.options) ? card.options : [];
  options.forEach((opt, i) => {
    const text = opt.context || opt.key || "";
    rows.push(
      `<div class="chat-card-row chat-card-option" data-clarify-text="${escapeHtml(text)}" title="Kliknij, żeby wybrać">` +
        `<span class="chat-card-option-num">${i + 1}</span>` +
        `<span>${escapeHtml(text)}</span>` +
      `</div>`
    );
  });
}

function formatWhen(iso) {
  if (!iso) return "nieznane";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    return iso;
  }
}

function setChatInputLocked(locked) {
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  input.disabled = locked;
  sendBtn.disabled = locked;
  // Podczas pracy modelu "Wyślij" ustępuje miejsca przyciskowi "Zatrzymaj".
  const stopBtn = document.getElementById("chat-stop");
  if (stopBtn) {
    stopBtn.classList.toggle("hidden", !locked);
    stopBtn.disabled = false;
    stopBtn.lastChild.textContent = "\n        Zatrzymaj\n      ";
  }
  sendBtn.classList.toggle("hidden", locked);
  if (locked) { input.placeholder = "Czekam na odpowiedź…"; paintGuide(activeConversation()); }
  else paintInputHint(activeConversation());
  if (!locked) {
    // Nie kradnij fokusu: w trakcie oczekiwania użytkownik mógł przejść do
    // segmentu Węzły i zacząć pisać w edytorze notatki. Fokus wraca do czatu
    // tylko gdy segment Rozmowy jest akurat widoczny, i tylko z "nigdzie"
    // albo z samego panelu czatu.
    const panel = document.getElementById("chat-panel");
    const active = document.activeElement;
    const nowhere = !active || active === document.body;
    const chatVisible = document.body.classList.contains("segment-chat");
    if (chatVisible && (nowhere || panel.contains(active))) input.focus();
  }
}

// Opcje kart "tak/nie" i doprecyzowań dotyczą TYLKO ostatniego pytania serwera
// (pending_action/pending_clarify żyją jedną wiadomość): po każdej nowej
// wiadomości starsze karty przestają być klikalne.
function retireCardOptions() {
  const rows = [...document.querySelectorAll(".chat-card-option:not(.used)")];
  rows.forEach((row) => {
    row.classList.add("used");
    row.setAttribute("aria-disabled", "true");
    row.tabIndex = -1;
  });
  return rows;
}

// Odbiór wyniku zadania czatu. Serwer trzyma zakończone zadanie godzinę
// (agent/main.py: CHAT_JOB_TTL), więc chwilowy błąd połączenia nie może
// zgubić wyniku (np. zatwierdzonej zmiany): ponawiamy to samo zapytanie
// kilka razy z rosnącą przerwą, zanim uznamy, że serwera nie ma.
async function waitForChatJob(job) {
  let pause = 1500;
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await gregaiFetch("/api/chat/wait", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job }),
      });
      return await res.json();
    } catch (e) {
      if (attempt >= 4) throw e;
      await new Promise((done) => setTimeout(done, pause));
      pause *= 2;
    }
  }
}

// {cancelled, jobId, cancel()} trwającej odpowiedzi żyje w SWOJEJ rozmowie
// (conv.run, 1.19.0) - patrz activeRun().

async function sendChatMessage(text, { retry = false, clientId = null, files = null } = {}) {
  // Przechwycone RAZ, na start: odpowiedź należy do TEJ rozmowy, nawet gdy w
  // międzyczasie przełączysz się na inną (1.19.0). `shown()` mówi, czy jest
  // akurat otwarta - tylko wtedy cokolwiek rysujemy na ekranie.
  const project = activeProject;
  const key = conversationKey(project);
  const conv = getConversation(project);
  clearNextSteps();
  if (conv.run) return;
  const shown = () => conversationKey(activeProject) === key;
  const chatId = currentChatId();
  retireCardOptions();
  // Załączniki idą z TĄ wiadomością (tylko te wgrane poprawnie) i znikają z
  // paska: następna wiadomość zaczyna bez nich. 1.19.0: plik jeszcze w trakcie
  // wgrywania ZOSTAJE (dawniej znikał po cichu i nie szedł nigdzie).
  // 1.23.0 (audyt): ponowienie idzie z TYMI SAMYMI plikami, co pierwsza próba.
  const attachedNames = Array.isArray(files) ? files.slice()
    : chatAttachments.filter((a) => a.status === "ok" && a.chat === chatId).map((a) => a.name);
  for (let i = chatAttachments.length - 1; i >= 0; i--) {
    if (chatAttachments[i].chat === chatId && chatAttachments[i].status !== "uploading") chatAttachments.splice(i, 1);
  }
  renderAttachments();
  const shownText = attachedNames.length ? text + "\n📎 " + attachedNames.join(", ") : text;
  if (!retry) {
    appendChatBubble("user", shownText);
    convPush(conv, { role: "user", text: shownText, raw: text });
    saveConversations();
  }
  const pending = appendTypingIndicator();
  conv.pendingEl = pending;
  // Zatrzymanie (1.12.0): przycisk "Zatrzymaj" ustawia run.cancelled i, gdy
  // zadanie ma już id (po pierwszej odpowiedzi serwera, najwyżej 2 s),
  // woła POST /api/chat/cancel. Serwer kończy pracę przy najbliższej granicy
  // fazy; wynik pojedynczego wywołania modelu w toku jest wyrzucany.
  const run = { cancelled: false, jobId: null };
  conv.run = run;
  conv.draft = "";
  setChatInputLocked(true);
  populateProjectList();
  const cancelJob = async () => {
    if (!run.jobId) return;
    try {
      await gregaiFetch("/api/chat/cancel", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job: run.jobId }),
      });
    } catch (e) { /* serwer i tak odrzuci wynik, gdy nikt go nie odbiera */ }
  };
  // 1.29.0 (kontrola): Stop, zanim serwer nadał zadaniu numer (zawieszone /api/chat),
  // przerywa samo żądanie - dawniej przycisk wisiał na "Zatrzymuję…" bez końca.
  run.abort = (typeof AbortController === "function") ? new AbortController() : null;
  run.cancel = () => {
    run.cancelled = true;
    if (!run.jobId && run.abort) run.abort.abort();
    cancelJob();
  };
  // Zgłoszenie Grzegorza (2026-10-19, potem zrzut ekranu Claude Code jako
  // wzór wyglądu, potem jeszcze tego samego dnia wieczorem): "Model jeszcze
  // liczy…" samo w sobie nic nie mówiło o tym, co faktycznie się dzieje, a
  // etykiety z 1.8.8 (niżej: PENDING_STAGES) i tak były tylko ZGADYWANIEM z
  // upływu czasu, bo serwer wysyła TYLKO jedno blokujące zapytanie na
  // odpowiedź - bez żadnego sygnału NA ŻYWO z samego modelu. Grzegorz:
  // "niech ten segment będzie jak taki narrator, który nieustannie nadzoruje
  // i opisuje co robi bądź myśli AI w danym momencie". 1.8.9: narrator czyta
  // PRAWDZIWY stan backendu z /api/system_info (ten sam, co panel /debug:
  // warp.connected, juggler.mode/configured, cloud.enabled) - TO zapytanie
  // idzie do WŁASNEGO serwera GREGAI (localhost), nie do internetu, więc
  // odpowiada od razu, nawet gdy WARP akurat jest rozłączony. Z tego da się
  // uczciwie powiedzieć, czy pytanie POSZŁO do sieci (koryto: Claude, potem
  // darmowa pula) czy
  // od razu lokalnie - a to też TRAFNIEJSZE niż stare etykiety, bo 1.8.9
  // (agent/router.py) zmieniło samą trasę: lokalny model wkracza już
  // WYŁĄCZNIE, gdy sieciowe AI zawiodły albo zadziałał bezpiecznik WARP, nie
  // jako skrót dla "łatwego" pytania. Elapsed-time niżej dalej dopowiada to,
  // czego /api/system_info nie wie (czy TO KONKRETNE zapytanie już dostało
  // odpowiedź od sieci, czy nadal czeka) - połączenie obu daje narrację
  // bliższą prawdzie niż czysty zegar. Pasek pojawia się po 20s (jak dotąd):
  // przy zwykłej, szybkiej odpowiedzi z sieci (zwykle sekundy) nie ma po co
  // go migać.
  const STAGE_DELAYS = [20000, 55000, 150000];
  const requestStart = Date.now();
  const formatElapsed = (ms) => {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m}m ${String(s).padStart(2, "0")}s`;
  };
  let statusEl = null, labelEl = null, timerEl = null, detailEl = null;
  let tickInterval = null;
  let pendingStageIndex = -1;
  let expanded = false;
  // Najświeższy odczyt /api/system_info (null, dopóki żaden się nie udał):
  // każdy etap dopytuje o nowy, bo rozmowa czekająca kilka minut mogła w
  // międzyczasie zobaczyć, że WARP wrócił albo dostawca się wyczerpał.
  let lastInfo = null;
  // Zdarzenia Namysłu (1.9.0) - deklarowane tutaj, PRZED zegarami starego
  // narratora, żeby addPendingNote mógł je sprawdzić w każdej chwili.
  // 1.18.0 (audyt): odpytywanie to łańcuch setTimeout (następne dopiero po
  // odpowiedzi poprzedniego - nigdy dwa naraz), a progressFinished odcina
  // każdą spóźnioną odpowiedź: po końcu nic już nie wznowi plakietki ani
  // tykacza.
  let progressTimer = null;
  let progressFinished = false;
  let progressEvents = [];
  // Postęp tej rozmowy (1.19.0): panel i plakietka pokazują go tylko wtedy,
  // gdy rozmowa jest otwarta; po powrocie do niej restoreProgressFor odtwarza.
  conv.progress = { events: progressEvents, startedAt: requestStart, finished: false, elapsedMs: 0 };
  // Ustawiane po pierwszym pending_job (niżej); do tego czasu nie ma czego kończyć.
  let finishProgress = async () => { progressFinished = true; };
  // Panel "Postęp" (1.16.2): nowa wymiana zaczyna od zera, inaczej zostałby
  // tu przebieg Namysłu z POPRZEDNIEJ wiadomości, nawet gdy ta nowa w ogóle
  // nie wejdzie w Namysł.
  resetProgressPanel();

  const updateTimer = () => {
    if (timerEl) timerEl.textContent = formatElapsed(Date.now() - requestStart);
  };

  async function fetchNetworkState() {
    try {
      const res = await gregaiFetch("/api/system_info");
      lastInfo = await res.json();
    } catch (e) {
      // Brak odczytu (np. serwer akurat zajęty tą samą rozmową w jednym
      // wątku - patrz agent/main.py: _CHAT_LOCK): narrator wraca do
      // ogólnego, uczciwego opisu z describeRoute(null) niżej, pasek
      // statusu nigdy się od tego nie wywala.
    }
    return lastInfo;
  }

  // Jedna, prawdziwa trasa TEGO pytania (sieć czy lokalnie) - z realnego
  // stanu backendu (agent/main.py: /api/system_info), nie z zegara.
  function describeRoute(info) {
    if (!info) {
      return {
        network: null,
        label: "Liczy",
        detail: "Nie udało się na bieżąco sprawdzić, czy to pytanie idzie teraz do sieci czy liczy je lokalny model - w każdym razie GREGAI nad nim pracuje.",
      };
    }
    const warpOk = !!(info.warp && info.warp.connected);
    const jugglerPool = (info.juggler && info.juggler.mode !== "off" && info.juggler.configured) || [];
    const jugglerOn = warpOk && jugglerPool.length > 0;
    const cloudOn = warpOk && !!(info.cloud && info.cloud.enabled);
    if (!warpOk) {
      const warpReason = (info.warp && info.warp.reason) || "WARP rozłączony";
      return {
        network: false,
        label: "Liczy lokalnie (bez internetu)",
        detail: `Internet jest teraz zablokowany (${warpReason}) - z zasady bezpieczeństwa GREGAI nigdy nie wychodzi do sieci bez połączonego WARP, więc to pytanie liczy od początku do końca lokalny model na tym laptopie, bez karty graficznej. To jedyny powód, dla którego GREGAI w ogóle liczy lokalnie: gdy internet/WARP wróci, następne pytanie znowu najpierw spróbuje sieci.`,
      };
    }
    // Koryto (1.17.0, agent/koryto.py): kolejność etapów z serwera, tylko te,
    // które faktycznie mają czym odpowiedzieć (klucz, limit, WARP).
    const kolejnosc = (info.koryto && Array.isArray(info.koryto.kolejnosc)) ? info.koryto.kolejnosc : ["anthropic", "darmowe", "lokalnie"];
    const etapy = kolejnosc.filter((e) => (e === "anthropic" && cloudOn) || (e === "darmowe" && jugglerOn) || e === "lokalnie");
    const pierwszy = etapy[0];
    if (pierwszy === "anthropic") {
      return {
        network: true,
        label: "Pyta Claude",
        detail: `Internet działa (WARP połączony), więc to pytanie najpierw dostaje Claude (${(info.cloud && info.cloud.model) || "Anthropic"}) - zwykle to kilka sekund. Dalej w korycie: ${etapy.slice(1).map((e) => e === "darmowe" ? `darmowa pula (${jugglerPool.join(", ")})` : "lokalny model na tym komputerze (tylko gdyby zniknął internet)").join(", potem ") || "nic"}.`,
      };
    }
    if (pierwszy === "darmowe") {
      return {
        network: true,
        label: "Pyta darmowe modele w sieci",
        detail: `Internet działa (WARP połączony), więc to pytanie najpierw dostają darmowi dostawcy w sieci: ${jugglerPool.join(", ")} - zwykle to kwestia sekund. Dalej w korycie: ${etapy.slice(1).map((e) => e === "anthropic" ? "Claude" : "lokalny model na tym komputerze (tylko gdyby zniknął internet)").join(", potem ") || "nic"}.`,
      };
    }
    if (pierwszy === "lokalnie" && etapy.length > 1) {
      return {
        network: false,
        label: "Liczy lokalnie (z wyboru)",
        detail: `W korycie (KORYTO w .env) lokalny model stoi przed etapami sieciowymi, więc to pytanie najpierw liczy ten komputer; sieć (${etapy.slice(1).map((e) => e === "anthropic" ? "Claude" : "darmowa pula").join(", ")}) dopiero gdyby zawiódł.`,
      };
    }
    return {
      network: false,
      label: "Liczy lokalnie",
      detail: "Sieciowe etapy koryta (Claude i darmowa pula) są wyłączone albo bez skonfigurowanego klucza w tej instalacji, więc to pytanie od razu liczy lokalny model na tym komputerze, bez karty graficznej.",
    };
  }

  // Warstwa 2: to, co SAMA trasa nie wie - czy TO KONKRETNE, już trwające
  // zapytanie zaczyna wyglądać na dłuższe niż typowe. Stage 0 (pierwsze
  // pojawienie się paska, 20s) pokazuje samą trasę; 1 i 2 dopowiadają, co to
  // znaczy, że mimo tej trasy wciąż czekamy - zmierzone wartości na tym CPU:
  // patrz agent/router.py, komentarz przy ROUTER_MODEL (2026-10-07) i przy
  // RICH_TIMEOUT.
  // 1.18.0: KORYTO_LOKALNIE=bez_internetu (domyślnie) - lokalny model liczy
  // TYLKO bez internetu. O lokalnej rezerwie przy działającej sieci mówimy
  // jedynie, gdy serwer zgłasza tryb "zawsze".
  const localAlways = (info) => !!(info && info.koryto && info.koryto.lokalnie === "zawsze");
  function narrate(stageIndex, info) {
    const route = describeRoute(info);
    if (stageIndex <= 0) return route;
    if (route.network === true) {
      // Trasa sieciowa, a mimo to czekamy długo: koryto (agent/koryto.py,
      // juggler.chat) próbuje etapów i dostawców PO KOLEI, więc to może być
      // po prostu kolejny w kolejce - albo w tle już spadło do lokalnego zapasu.
      // Stąd ostrożne "pewnie", nie twierdzenie.
      return {
        ...route,
        label: stageIndex === 1 ? "Wciąż czeka na sieć" : "Pewnie już lokalnie",
        detail: route.detail + (stageIndex === 1
          ? " To już dłużej niż typowa odpowiedź z sieci (kilka sekund) - pewnie właśnie próbuje kolejnego dostawcy z listy (po Claude darmowa pula)."
          : (localAlways(info)
            ? " Po tak długim czekaniu sieciowi dostawcy najpewniej zawiedli i w tle liczy to teraz lokalny model jako ostatnia rezerwa - na tym procesorze, bez karty graficznej, to może potrwać kilka minut."
            : " Po tak długim czekaniu sieć odpowiada wyjątkowo wolno albo kolejni dostawcy odmawiają. Lokalny model wkracza tylko bez internetu, więc przy działającej sieci to wciąż czekanie na odpowiedź z sieci.")),
      };
    }
    // Lokalnie (z wyboru w konfiguracji albo bo właśnie zadziałał bezpiecznik
    // WARP): etap 2/3 dodaje, co lokalny model fizycznie robi teraz.
    if (stageIndex === 1) {
      return {
        ...route,
        label: "Model się rozgrzewa",
        detail: route.detail + " Zwykle w tym momencie dzieje się jedno z dwóch: model dopiero wczytuje się z dysku do pamięci (tylko przy pierwszym pytaniu po starcie usługi), albo już przetwarza Twoją wiadomość razem z całą instrukcją systemową (kilka tysięcy słów) - samo to przetworzenie potrafi zająć pół minuty, zanim napisze pierwsze słowo odpowiedzi.",
      };
    }
    return {
      ...route,
      label: "Pisze odpowiedź",
      detail: route.detail + " To już najpewniej pisanie odpowiedzi, słowo po słowie - na tym sprzęcie to tempo rzędu pojedynczych słów na sekundę, więc dłuższa odpowiedź to realnie kilka minut. To nie zawieszenie.",
    };
  }

  let pendingGone = false;
  const buildStatusWidget = () => {
    // 1.19.0: dymek odłączony od ekranu (inna rozmowa otwarta) też się buduje -
    // wróci na ekran przy powrocie do tej rozmowy.
    if (statusEl || pendingGone) return;
    statusEl = document.createElement("div");
    statusEl.className = "pending-status";
    statusEl.setAttribute("role", "button");
    statusEl.setAttribute("tabindex", "0");
    statusEl.setAttribute("aria-expanded", "false");
    statusEl.innerHTML =
      '<span class="pending-status-dot"></span>' +
      '<span class="pending-status-label"></span>' +
      '<span class="pending-status-timer"></span>' +
      '<span class="pending-status-chevron">›</span>';
    labelEl = statusEl.querySelector(".pending-status-label");
    timerEl = statusEl.querySelector(".pending-status-timer");
    detailEl = document.createElement("div");
    detailEl.className = "pending-status-detail";
    detailEl.hidden = true;
    const toggle = () => {
      expanded = !expanded;
      detailEl.hidden = !expanded;
      statusEl.setAttribute("aria-expanded", String(expanded));
      statusEl.classList.toggle("expanded", expanded);
      if (pending.parentElement) pending.parentElement.scrollTop = pending.parentElement.scrollHeight;
    };
    statusEl.addEventListener("click", toggle);
    statusEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
    pending.appendChild(statusEl);
    pending.appendChild(detailEl);
    tickInterval = setInterval(updateTimer, 1000);
    updateTimer();
  };

  const applyNarration = (stageIndex, info) => {
    if (!labelEl) return;
    const { label, detail } = narrate(stageIndex, info);
    labelEl.textContent = label;
    detailEl.textContent = detail;
  };

  // addPendingNote() (bez argumentu): użyte też w pętli długiego odpytywania
  // niżej (CHAT_WAIT) - tam ma tylko DOPILNOWAĆ, że pasek istnieje i pokazuje
  // OSTATNI już osiągnięty etap, nigdy cofać do wcześniejszego. Pokazuje
  // najpierw to, co już wie (lastInfo, bez czekania na sieć), a dopiero gdy
  // świeży odczyt /api/system_info wróci, dopisuje narrację na nowo - ale
  // tylko jeśli w międzyczasie nie doszliśmy już do NOWSZEGO etapu (inaczej
  // wolniejsza odpowiedź starego etapu nadpisałaby właśnie wyświetlony nowy).
  const addPendingNote = () => {
    if (pendingStageIndex < 0) return;
    // Namysł melduje fazy sam (progressEvents niżej): stary narrator z zegara
    // nie ma wtedy wstawać obok osi faz i mówić drugiej, zgadywanej wersji.
    if (progressEvents.length) return;
    buildStatusWidget();
    const myStage = pendingStageIndex;
    applyNarration(myStage, lastInfo);
    fetchNetworkState().then((info) => {
      if (pendingStageIndex !== myStage) return;
      applyNarration(myStage, info);
    });
  };
  const pendingTimers = STAGE_DELAYS.map((delay, i) =>
    setTimeout(() => { pendingStageIndex = i; addPendingNote(); }, delay)
  );
  const clearPendingTimers = () => {
    pendingTimers.forEach(clearTimeout);
    if (tickInterval) clearInterval(tickInterval);
  };

  try {
    // Serwer oddaje numer zadania po ok. 2 s; 25 s ciszy = zerwane połączenie (Stop działa i tak).
    const chatTimer = run.abort ? setTimeout(() => { run.timedOut = true; run.abort.abort(); }, 25000) : null;
    const res = await gregaiFetch("/api/chat", {
      method: "POST",
      signal: run.abort ? run.abort.signal : undefined,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        // Idempotencja (1.20.0): ponowienie TEJ SAMEJ wiadomości po zgubionej odpowiedzi
        // wraca do tego samego zadania na serwerze zamiast je dublować.
        client_id: run.clientId = clientId || (window.crypto && crypto.randomUUID ? crypto.randomUUID() : "c" + Date.now() + Math.random().toString(36).slice(2)),
        history: conv.history,
        pending_clarify: conv.pendingClarify,
        pending_action: conv.pendingAction,
        // JSON.stringify pomija klucz o wartości undefined: Ogólna rozmowa
        // nie wysyła "project" wcale, backend widzi dokładnie to, co dotąd.
        project: project ? project.id : undefined,
        // Załączniki wgrane spinaczem (nazwy z data/wgrane) - serwer czyta
        // je sam; tu idą tylko nazwy. Lista czyszczona po wysłaniu.
        files: attachedNames.length ? attachedNames : undefined,
      }),
    });
    if (chatTimer) clearTimeout(chatTimer);
    let data = await res.json().catch(() => ({ error: "Serwer odpowiedział błędem " + res.status }));
    if (data && data.error) data._status = res.status;
    // Długa odpowiedź (duży model na CPU, patrz agent/main.py: CHAT_WAIT):
    // serwer oddaje {"pending_job": id} już po 2 s (CHAT_FIRST_WAIT), a my
    // pytamy dalej, aż odpowiedź będzie gotowa. Równolegle (1.9.0) co 1,5 s
    // odczytujemy zdarzenia Namysłu (GET /api/chat/progress) i rysujemy oś
    // faz z opisem tego, co dzieje się teraz - zamiast zgadywania z zegara.
    const renderProgress = (finished) => {
      if (!progressEvents.length) return;
      const elapsed = Date.now() - requestStart;
      conv.progress.events = progressEvents;
      if (!finished) renderNamyslLive(pending, progressEvents, elapsed);
      if (shown()) renderProgressPanel(progressEvents, elapsed, finished);
    };
    // Jeden odczyt: since = ile już mamy; doklejamy tylko to, czego jeszcze
    // nie ma (gdyby serwer oddał coś drugi raz, nie zdubluje się na osi).
    const fetchProgress = async (jobId, final = false) => {
      const since = progressEvents.length;
      const r = await gregaiFetch(`/api/chat/progress?job=${encodeURIComponent(jobId)}&since=${since}`);
      const d = await r.json();
      // Po końcu przyjmujemy już tylko ten jeden, ostatni odczyt z finishProgress.
      if (progressFinished && !final) return d;
      if (Array.isArray(d.events) && d.events.length) {
        const fresh = d.events.slice(Math.max(0, progressEvents.length - since));
        if (fresh.length) progressEvents = progressEvents.concat(fresh);
        // Backend melduje fazy: stary narrator (zgadywanie z zegara) schodzi
        // z drogi, żeby nie mówić dwóch rzeczy naraz.
        if (statusEl) { statusEl.hidden = true; detailEl.hidden = true; }
      }
      return d;
    };
    // Jeden łańcuch naraz także przy kolejnym pending_job (przegląd 1.18.0):
    // żywy łańcuch tylko przełącza się na nowe zadanie.
    let chainAlive = false;
    let chainJob = null;
    const startProgress = (jobId) => {
      chainJob = jobId;
      if (chainAlive || progressFinished) return;
      chainAlive = true;
      const poll = async () => {
        progressTimer = null;
        if (progressFinished) { chainAlive = false; return; }
        const polledJob = chainJob;
        let done = false;
        try {
          const d = await fetchProgress(polledJob);
          if (progressFinished) { chainAlive = false; return; }
          renderProgress(false);
          done = !!d.done && polledJob === chainJob;
        } catch (e) { /* chwilowy brak odczytu postępu nie przerywa czekania */ }
        if (!done && !progressFinished) progressTimer = setTimeout(poll, 1500);
        else chainAlive = false;
      };
      progressTimer = setTimeout(poll, 0);
    };
    // Koniec czekania (odpowiedź, zatrzymanie albo błąd): flaga PRZED
    // czymkolwiek asynchronicznym, potem ostatni odczyt (najwyżej 1,5 s),
    // żeby panel "Postęp" dostał komplet faz, i stan "zakończony".
    finishProgress = async () => {
      if (progressFinished) return;
      progressFinished = true;
      if (progressTimer) { clearTimeout(progressTimer); progressTimer = null; }
      const elapsed = Date.now() - requestStart;
      if (run.jobId) {
        try {
          await Promise.race([fetchProgress(run.jobId, true), new Promise((ok) => setTimeout(ok, 1500))]);
        } catch (e) { /* bez ostatniego odczytu zostaje to, co już było */ }
      }
      // Odpowiedź jest już pokazana, a pole odblokowane; jeśli w tym czasie
      // ruszyła NOWA wiadomość albo otwarta jest inna rozmowa, ich panel nie
      // może dostać faz tej (1.23.0: sprawdzenie PRZED nadpisaniem postępu).
      if (conv.run && conv.run !== run) return;
      conv.progress = { events: progressEvents, startedAt: requestStart, finished: true, elapsedMs: elapsed };
      if (progressEvents.length && shown()) renderProgressPanel(progressEvents, elapsed, true);
    };
    while (data && data.pending_job) {
      run.jobId = data.pending_job;
      // 1.29.0 (kontrola): numer zadania zapisany przy pytaniu - po odświeżeniu strony
      // w trakcie odpowiedzi da się ją odebrać ("Odpowiedź mogła już przyjść").
      if (!retry) {
        const q = conv.messages.slice().reverse().find((m) => m.role === "user" && m.raw === text);
        if (q && !q.jobId) { q.jobId = run.jobId; q.askText = text; saveConversations(); }
      }
      if (run.cancelled) { await cancelJob(); data = { anulowano: true }; break; }
      addPendingNote();
      startProgress(data.pending_job);
      data = await waitForChatJob(data.pending_job);
    }
    // 1.17.3 (zgłoszenie Grzegorza): odpowiedź zwykle przychodzi przez
    // waitForChatJob ZANIM odpytywanie postępu zobaczy "done" - plakietka
    // "Namysł w toku" z licznikiem zostawała na nagłówku po zakończeniu.
    // Stan końcowy ustawiamy więc tutaj, na każdej drodze wyjścia z czekania.
    if (shown()) stopPillTick();
    const finishing = finishProgress();

    clearPendingTimers();
    pendingGone = true;
    pending.remove();
    conv.pendingEl = null;
    // 1.19.0 (audyt): odpowiedź, która przyszła, ZANIM zatrzymanie zadziałało
    // (pierwsze 2 s, gdy zadanie nie ma jeszcze id), jest prawdziwa: serwer ją
    // zapisał, a "tak" już się wykonało. Pokazujemy ją z dopiskiem, zamiast
    // twierdzić, że nic się nie stało.
    // 1.23.0 (audyt): rozmowę usunięto w innej karcie, gdy tu trwała odpowiedź -
    // nie wskrzeszamy jej dopisaniem i zapisem.
    if (conversationDeletedSince(key, requestStart)) {
      if (conversations.get(key) === conv) conversations.delete(key);
      if (shown()) renderConversationMessages(getConversation(project), project);
      return;
    }
    const arrivedBeforeStop = run.cancelled && data && !data.anulowano && !data.error && !data.pending_job
      && typeof data.speech === "string";
    if ((run.cancelled && !arrivedBeforeStop) || (data && data.anulowano)) {
      // Zatrzymane: wymiana nie trafia do historii wysyłanej modelowi, a
      // pytanie o zgodę (jeśli czekało) wraca do kliknięcia.
      const stopped = "Zatrzymano na Twoje polecenie. Nic z tej wymiany nie zostało zapamiętane.";
      // 1.19.0 (przegląd): po zatrzymaniu karta "tak/nie" gaśnie na stałe i
      // rozmowa przestaje czekać na odpowiedź - ten sam stan na ekranie, po
      // przełączeniu i po odświeżeniu. Zgodę trzeba dać od nowa.
      conv.pendingAction = null;
      conv.pendingClarify = null;
      if (shown()) { appendChatBubble("assistant", stopped); paintInputHint(conv); }
      convPush(conv, { role: "assistant", text: stopped });
      return;
    }
    if (data.error) {
      // Odpowiedź z błędem (np. za dużo rozmów naraz) nie była odpowiedzią na pytanie o zgodę:
      // oczekująca karta zostaje, inaczej "tak" po błędzie nigdy by jej nie potwierdziło.
      // 1.23.0 (audyt): dawniej kod mimo tego komentarza zerował oba pola.
      const errText = `Błąd: ${data.error}` + (conv.pendingAction ? " Pytanie o zgodę nadal czeka: napisz „tak” albo „nie”." : "");
      const errBubble = shown() ? appendChatBubble("assistant", errText) : null;
      // 1.29.0 (kontrola): przy przeciążeniu (429) albo błędzie serwera (5xx) jedno dotknięcie
      // ponawia TO SAMO pytanie (ten sam client_id, więc bez dublowania).
      const st = data._status || 0;
      if (errBubble && (st === 429 || st >= 500) && !/^\s*(tak|nie|ok|wykonaj|zr[oó]b|potwierdzam)\b/i.test(text)) {
        const again = document.createElement("button");
        again.type = "button";
        again.className = "chat-retry";
        again.textContent = "Spróbuj ponownie";
        again.addEventListener("click", () => {
          if (conv.run || !shown()) return;
          errBubble.remove();
          sendChatMessage(text, { retry: true, clientId: run.clientId, files: attachedNames });
        });
        errBubble.appendChild(again);
      }
      convPush(conv, { role: "assistant", text: errText, failed: true });
      return;
    }
    conv.pendingClarify = data.pending_clarify || null;
    conv.pendingAction = data.pending_action || null;
    if (shown()) paintInputHint(conv);

    // Błąd w rysowaniu karty nie może udawać błędu połączenia ani gubić historii.
    // 1.17.7 (zgłoszenie Grzegorza: "minęło 10 s, a karta mówi 33 s"): karta
    // "Jak myślałem" pokazuje czas zmierzony TUTAJ, od wysłania do odpowiedzi -
    // to jest czas, który widzi użytkownik; czas serwera (czas_s) zostaje do
    // porównania, gdy się różni (patrz renderNamyslCard).
    if (data.card && data.card.type === "namysl") data.card.klient_s = Math.round((Date.now() - requestStart) / 100) / 10;
    const lateNote = arrivedBeforeStop ? "Ta odpowiedź przyszła, zanim zatrzymanie zadziałało - została zapisana." : undefined;
    const speech = data.speech || "(brak odpowiedzi)";
    const answerMsg = { role: "assistant", text: speech, card: data.card || null, node: data.suggested_node || null, note: lateNote };
    // 1.32.14: pytanie ma już odpowiedź - numer zadania nie jest potrzebny (przycisk "Sprawdź" po
    // odświeżeniu nie odbierze jej drugi raz pod późniejszą rozmową).
    try {
      const qDone = conv.messages.slice().reverse().find((m) => m.role === "user" && m.raw === text);
      if (qDone) { delete qDone.jobId; delete qDone.askText; }
    } catch (e) { /* bez znaczenia dla odpowiedzi */ }
    convPush(conv, answerMsg);
    if (shown()) {
      appendChatBubble("assistant", speech);
      try { appendChatCard(data.card); } catch (e) { console.error("karta:", e); }
      // Propozycja nowego węzła (tylko rozmowa przypisana do projektu, patrz
      // agent/main.py: _extract_suggested_node) - nigdy zapisywana sama, zawsze
      // czeka na "Zapisz" w interfejsie.
      if (data.suggested_node) {
        try { appendSuggestedNodeCard(data.suggested_node, answerMsg); } catch (e) { console.error("sugestia węzła:", e); }
      }
      if (lateNote) appendToChat(buildNote(lateNote));
      if (Array.isArray(data.next) && data.next.length && !conv.pendingAction && !conv.pendingClarify) {
        try { appendNextSteps(data.next); } catch (e) { console.error("następne kroki:", e); }
      }
    } else {
      conv.unread = true;
    }

    conv.history.push({ role: "user", content: text });
    // tool: odpowiedź z narzędzia (notatki, sieć, system). Zostaje w historii dla
    // lokalnych modeli, ale serwer nie wysyła jej do sieci (router._cloud_history).
    // provider: nazwa dostawcy z koryta (Claude albo darmowa pula), który odpowiedział -
    // serwer odczytuje ją z poprzedniej tury, żeby trzymać się TEGO SAMEGO dostawcy w
    // ramach jednej rozmowy (router._last_juggler_provider, "lepkość", 2026-10-19).
    conv.history.push({ role: "assistant", content: data.speech || "", tool: data.kind !== "chat", sig: data.sig || null, provider: data.provider || null });
    // Najwyżej 10 wiadomości (router.py: HISTORY_TURNS). Po przekroczeniu
    // zostają ostatnie 4, zamiast przesuwać okno przy każdej wiadomości:
    // historia rośnie tylko na końcu, więc Ollama trzyma jej początek w
    // pamięci podręcznej i liczy tylko nową wymianę.
    if (conv.history.length > 10) conv.history = conv.history.slice(-4);

    const badge = document.getElementById("chat-model-badge");
    const headerDot = document.getElementById("header-dot");
    // 1.32.2 (audyt tura 7): odpowiedź narzędzia (np. /pomoc) nie mówi nic o modelu na
    // laptopie - plakietkę zmienia tylko odpowiedź rozmowy, resztę robi odczyt /api/status.
    if (data.kind === "chat" && data.model_active) {
      badge.textContent = "Model na laptopie: działa";
      badge.className = "chat-model-badge active";
      if (headerDot) headerDot.className = "header-dot active";
    } else if (data.kind === "chat") {
      badge.textContent = "Model na laptopie: wyłączony";
      badge.className = "chat-model-badge fallback";
      if (headerDot) headerDot.className = "header-dot fallback";
    }
    applyNetworkHint(badge);
    // Czat zapisał notatkę (pamięć, Wikipedia): pokaż ją w grafie bez przeładowania.
    if (data.graph_changed) refreshGraphData();
    // Bez await (przegląd 1.18.0): ostatni odczyt postępu (do 1,5 s) domyka
    // panel w tle, pole wpisywania odblokowuje się od razu z odpowiedzią.
    finishing.catch(() => {});
  } catch (e) {
    if (shown()) stopPillTick();
    if (run.cancelled && !run.jobId) {
      // Stop przed nadaniem numeru zadania: żądanie przerwane, nic się nie wykonało.
      finishProgress();
      clearPendingTimers();
      pendingGone = true;
      pending.remove();
      conv.pendingEl = null;
      const stopped = "Zatrzymano na Twoje polecenie. Nic z tej wymiany nie zostało zapamiętane.";
      conv.pendingAction = null;
      conv.pendingClarify = null;
      if (shown()) { appendChatBubble("assistant", stopped); paintInputHint(conv); }
      convPush(conv, { role: "assistant", text: stopped });
      return;
    }
    finishProgress();
    clearPendingTimers();
    pendingGone = true;
    pending.remove();
    conv.pendingEl = null;
    // 1.17.17: po zatwierdzeniu restartu samego GREGAI połączenie znika z
    // definicji (usługa właśnie wstaje) - to nie błąd, tylko skutek polecenia.
    const pa = conv.pendingAction || {};
    const selfRestart = /^\s*(tak|ok|wykonaj|zr[oó]b)/i.test(text) && pa.tool === "sys_service_action" && /restart\s+gregai/i.test(pa.arg || "");
    // Jak przy zatrzymaniu: po porażce połączenia pytanie o zgodę gaśnie.
    conv.pendingAction = null;
    conv.pendingClarify = null;
    if (shown()) paintInputHint(conv);
    const failText = selfRestart
      ? "Restartuję się na Twoje polecenie. Odśwież stronę za kilka sekund."
      : "Nie udało się połączyć z serwerem.";
    // 1.19.0 (audyt): porażka też trafia do zapisanej rozmowy - dawniej po
    // powrocie widać było dwa pytania pod rząd i jedną odpowiedź.
    const failMsg = { role: "assistant", text: failText, failed: true, jobId: (!selfRestart && run.jobId) ? run.jobId : undefined, askText: text };
    convPush(conv, failMsg);
    const failBubble = shown() ? appendChatBubble("assistant", failText) : buildBubble("assistant", failText);
    // 1.18.0: "Spróbuj ponownie" wysyła TO SAMO pytanie jeszcze raz - tylko gdy
    // serwer nie przyjął jeszcze zadania (brak jobId: błąd przy wysyłaniu) i to
    // nie było potwierdzenie karty ("tak"). Gdy zadanie już ruszyło, mogło się
    // wykonać (zapis, polecenie) - ponowienie zrobiłoby to drugi raz.
    const confirmWord = /^\s*(tak|ok|wykonaj|zr[oó]b|potwierdzam)\b/i.test(text);
    if (!selfRestart && !run.jobId && !confirmWord) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "chat-retry";
      retry.textContent = "Spróbuj ponownie";
      retry.addEventListener("click", () => {
        if (conv.run || !shown()) return;
        // Ponowienie zastępuje porażkę: ten sam dymek pytania, bez drugiej kopii.
        const at = conv.messages.lastIndexOf(failMsg);
        if (at >= 0) { conv.messages.splice(at, 1); conv.updated = Date.now(); }
        failBubble.remove();
        sendChatMessage(text, { retry: true, clientId: run.clientId, files: attachedNames });
      });
      failBubble.appendChild(retry);
    }
    // 1.20.0: zadanie ruszyło, ale połączenie zerwało się w trakcie czekania (uśpiony
    // telefon, zmiana sieci). Serwer trzyma wynik godzinę, więc można go odebrać BEZ
    // ponawiania pytania (ponowienie mogłoby wykonać zapis drugi raz).
    if (!selfRestart && run.jobId) attachResumeButton(conv, project, failMsg, failBubble);
  } finally {
    if (conv.run === run) conv.run = null;
    if (shown()) setChatInputLocked(false);
    saveConversations();
    populateProjectList();
  }
}
