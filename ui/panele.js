/* ============================================================================
   1.35.1 - ZADANIA i NOTATKI (dwa nowe segmenty).
   Vanilla JS, zero build. Korzysta z globalnych funkcji ui/app.js, które są
   ładowane PO tym pliku (wywołania dopiero po DOMContentLoaded):
   gregaiFetch, escapeHtml, typeLabelPl, renderMarkdownLite, setSegment,
   showBanner, visualClick.

   Backend: GET /api/standing, POST /api/standing/nowe|pauza|usun|wyczysc,
   GET /api/notes, GET /api/note?id=, GET /api/graph.
   ========================================================================== */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (typeof escapeHtml === "function"
    ? escapeHtml(String(s == null ? "" : s))
    : String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const label = (t) => (typeof typeLabelPl === "function" ? typeLabelPl(t) : (t || ""));
  const flash = (v) => { try { if (typeof visualClick === "function") visualClick(v); } catch (e) { /* brak warstwy */ } };
  const api = (url, opts) => (typeof gregaiFetch === "function" ? gregaiFetch(url, opts) : fetch(url, opts));

  function fmtDate(sec) {
    const n = Number(sec);
    if (!n) return "—";
    try {
      return new Date(n * 1000).toLocaleString("pl-PL", {
        day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
      });
    } catch (e) { return "—"; }
  }

  function emptyBox(text) {
    return `<div class="panele-empty">${esc(text)}</div>`;
  }

  function markdown(text) {
    if (typeof renderMarkdownLite === "function") return renderMarkdownLite(String(text || ""));
    return `<p>${esc(text)}</p>`;
  }

  /* ======================================================================
     ZADANIA STAŁE
     ====================================================================== */
  const zad = { lista: [], filtr: "aktywne", wybrane: null, zaladowane: 0 };

  function zadStatusLabel(status) {
    if (status === "aktywne") return "AKTYWNE";
    if (status === "wstrzymane") return "PAUZA";
    return "WYKONANE";
  }

  function renderZadania() {
    const box = $("zadania-lista");
    if (!box) return;
    const items = zad.lista.filter((z) => z.status === zad.filtr);
    if (!items.length) {
      box.innerHTML = emptyBox("Brak zadań w tym filtrze.");
      return;
    }
    box.innerHTML = items.map((z) => {
      const st = z.status === "aktywne" ? "ok" : z.status === "wstrzymane" ? "warn" : "off";
      const ostatnie = z.ostatnie ? String(z.ostatnie).replace("T", " ").slice(0, 16) : "jeszcze nie sprawdzane";
      return `<article class="zad-card" data-plik="${esc(z.plik)}" tabindex="0" role="button" aria-label="${esc(z.nazwa)}">
        <div class="zad-card-head"><span class="zad-name">${esc(z.nazwa)}</span><span class="zad-status ${st}">${zadStatusLabel(z.status)}</span></div>
        <p class="zad-command">${esc(String(z.zlecenie || "").slice(0, 180))}</p>
        <p class="zad-meta">co ${esc(String(z.interwal_minut || "?"))} min · ostatnie: ${esc(ostatnie)}</p>
        <div class="zad-actions">
          ${z.status !== "zakończone" ? `<button type="button" class="inspector-btn secondary" data-akcja="pauza" data-stan="${z.status === "aktywne" ? "wstrzymane" : "aktywne"}">${z.status === "aktywne" ? "Pauza" : "Start"}</button>` : ""}
          <button type="button" class="inspector-btn danger" data-akcja="usun">Usuń</button>
        </div>
      </article>`;
    }).join("");
    box.querySelectorAll(".zad-card").forEach((card) => {
      const pick = () => {
        const z = zad.lista.find((x) => x.plik === card.dataset.plik);
        if (z) renderZadanieSzczegoly(z);
      };
      card.addEventListener("click", pick);
      card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
  }

  function renderZadanieSzczegoly(z) {
    zad.wybrane = z ? z.plik : null;
    const box = $("zadanie-szczegoly");
    const empty = $("zadania-pusty");
    if (!box) return;
    if (!z) {
      box.classList.add("hidden");
      if (empty) empty.classList.remove("hidden");
      return;
    }
    if (empty) empty.classList.add("hidden");
    box.classList.remove("hidden");
    const historia = Array.isArray(z.dziennik) ? z.dziennik : [];
    box.innerHTML = `
      <div class="panele-detail-head">
        <div class="lt"><span class="lt-chip">${esc(zadStatusLabel(z.status))}</span><h2 class="lt-title">${esc(z.nazwa)}</h2></div>
        <button type="button" class="insp-close" id="zad-close" aria-label="Zamknij szczegóły">✕</button>
      </div>
      <p class="panele-lead">${esc(z.zlecenie || "")}</p>
      <div class="meta-grid">
        <div><span>Interwał</span><b>co ${esc(String(z.interwal_minut || "?"))} min</b></div>
        <div><span>Utworzono</span><b>${esc(String(z.utworzono || "—").replace("T", " ").slice(0, 16))}</b></div>
        <div><span>Ostatnie</span><b>${esc(String(z.ostatnie || "—").replace("T", " ").slice(0, 16))}</b></div>
        <div><span>Następne</span><b>${esc(String(z.nastepne || "—").replace("T", " ").slice(0, 16))}</b></div>
        <div><span>Alerty</span><b>${esc(String(z.alertow || 0))}</b></div>
      </div>
      <h3 class="panele-h3">Historia wykonania</h3>
      <ul class="zad-history">
        ${historia.length ? historia.map((h) => `<li class="${h.wynik === "alert" ? "warn" : "ok"}">
          <time>${esc(String(h.ts || "?").replace("T", " ").slice(0, 16))}</time>
          <span class="zad-history-wynik">${h.wynik === "alert" ? "ALERT" : "OK"}</span>
          <span class="zad-history-opis">${esc(h.opis || "")}</span></li>`).join("") : `<li class="off">Brak wpisów.</li>`}
      </ul>
      <div class="inspector-btn-row">
        <button type="button" class="inspector-btn secondary" id="zad-clear">Wyczyść historię</button>
        <button type="button" class="inspector-btn danger" id="zad-delete">Usuń zadanie</button>
      </div>
      <p class="note-edit-status" id="zad-detail-status"></p>
    `;
    const close = $("zad-close");
    if (close) close.addEventListener("click", () => renderZadanieSzczegoly(null));
    const clear = $("zad-clear");
    if (clear) clear.addEventListener("click", async () => {
      clear.disabled = true;
      try {
        await api("/api/standing/wyczysc", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plik: z.plik }),
        });
        flash(0.02);
        await loadZadania(true);
        const fresh = zad.lista.find((x) => x.plik === z.plik);
        renderZadanieSzczegoly(fresh || null);
      } catch (e) {
        const st = $("zad-detail-status");
        if (st) st.textContent = "Nie udało się wyczyścić historii.";
        clear.disabled = false;
      }
    });
    const del = $("zad-delete");
    if (del) del.addEventListener("click", () => zadAction(z.plik, "usun"));
  }

  async function zadAction(plik, akcja, stan) {
    try {
      if (akcja === "pauza") {
        await api("/api/standing/pauza", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plik, stan }),
        });
      } else if (akcja === "usun") {
        await api("/api/standing/usun", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plik }),
        });
      }
      flash(0.03);
      await loadZadania(true);
      if (akcja === "usun") {
        // 1.35.1: zadanie jest notatką w grafie - bez tego węzeł zostawał
        // w Węzłach do najbliższego odświeżenia.
        if (typeof refreshGraphData === "function") {
          try { await refreshGraphData(); } catch (e) { /* graf odświeży się sam */ }
        }
        if (zad.wybrane === plik) renderZadanieSzczegoly(null);
      }
    } catch (e) {
      if (typeof showBanner === "function") showBanner("Nie udało się zmienić zadania.", { info: true, ms: 5000 });
    }
  }

  async function loadZadania(force) {
    if (!force && Date.now() - zad.zaladowane < 3000) return;
    try {
      const res = await api("/api/standing");
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      zad.lista = Array.isArray(data.zadania) ? data.zadania : [];
      zad.zaladowane = Date.now();
      renderZadania();
      if (zad.wybrane) {
        const fresh = zad.lista.find((z) => z.plik === zad.wybrane);
        if (fresh) renderZadanieSzczegoly(fresh);
      }
    } catch (e) {
      const box = $("zadania-lista");
      if (box) box.innerHTML = emptyBox("Nie udało się wczytać zadań.");
    }
  }

  function initZadania() {
    document.querySelectorAll("[data-zad-filtr]").forEach((btn) => {
      btn.addEventListener("click", () => {
        zad.filtr = btn.dataset.zadFiltr || "aktywne";
        document.querySelectorAll("[data-zad-filtr]").forEach((b) => {
          b.setAttribute("aria-pressed", String((b.dataset.zadFiltr || "aktywne") === zad.filtr));
        });
        renderZadania();
      });
    });
    const box = $("zadania-lista");
    if (box) box.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-akcja]");
      if (btn) {
        e.stopPropagation();
        const card = btn.closest(".zad-card");
        if (card) zadAction(card.dataset.plik, btn.dataset.akcja, btn.dataset.stan);
      }
    });
    const add = $("btn-zadanie-nowe");
    const form = $("zadanie-form");
    if (add && form) add.addEventListener("click", () => {
      form.classList.remove("hidden");
      const n = $("zad-nazwa");
      if (n) n.focus();
    });
    const cancel = $("zad-anuluj");
    if (cancel && form) cancel.addEventListener("click", () => form.classList.add("hidden"));
    if (form) form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const nazwa = ($("zad-nazwa") || {}).value || "";
      const komenda = ($("zad-komenda") || {}).value || "";
      const min = ($("zad-interwal") || {}).value || "60";
      const status = $("zad-status");
      if (!komenda.trim()) {
        if (status) status.textContent = "Podaj komendę albo warunek alertu.";
        return;
      }
      const instruction = `${nazwa.trim() ? nazwa.trim() + ". " : ""}${komenda.trim()} co ${min} minut`;
      if (status) status.textContent = "Dodaję…";
      try {
        const res = await api("/api/standing/nowe", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ komenda: instruction }),
        });
        const data = await res.json();
        if (data.error || !data.ok) {
          if (status) status.textContent = data.error || data.speech || "Nie udało się dodać zadania.";
          return;
        }
        flash(0.03);
        form.reset();
        form.classList.add("hidden");
        zad.filtr = "aktywne";
        await loadZadania(true);
      } catch (err) {
        if (status) status.textContent = "Nie udało się dodać zadania.";
      }
    });
  }

  /* ======================================================================
     NOTATKI
     ====================================================================== */
  const note = { lista: [], typy: new Set(), wybrana: null, timer: null, graf: null };

  function renderNotatki() {
    const list = $("notatki-lista");
    if (!list) return;
    const typ = ($("notatki-typ") || {}).value || "";
    const okres = ($("notatki-data") || {}).value || "";
    const maxAge = okres === "dzis" ? 86400 : okres === "tydzien" ? 7 * 86400 : okres === "miesiac" ? 31 * 86400 : 0;
    const now = Date.now() / 1000;
    const items = note.lista.filter((n) => {
      if (typ && n.typ !== typ) return false;
      if (maxAge && (!n.modyfikacja || now - n.modyfikacja > maxAge)) return false;
      return true;
    });
    const count = $("notatki-liczba");
    if (count) count.textContent = `${items.length} / ${note.lista.length}`;
    if (!items.length) {
      list.innerHTML = emptyBox("Brak notatek w tym filtrze.");
      return;
    }
    list.innerHTML = items.map((n) => `<li class="note-row" data-id="${esc(n.id)}" tabindex="0" role="button">
      <span class="note-row-title">${esc(n.tytul || "")}</span>
      <span class="note-row-meta">${esc(label(n.typ))}${n.modyfikacja ? " · " + esc(fmtDate(n.modyfikacja).slice(0, 10)) : ""}</span>
    </li>`).join("");
    list.querySelectorAll(".note-row").forEach((row) => {
      const open = () => openNotatka(row.dataset.id);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
  }

  function refreshNoteTypes() {
    const sel = $("notatki-typ");
    if (!sel) return;
    const current = sel.value;
    const types = [...note.typy].sort((a, b) => label(a).localeCompare(label(b), "pl"));
    sel.innerHTML = `<option value="">wszystkie</option>` +
      types.map((t) => `<option value="${esc(t)}">${esc(label(t))}</option>`).join("");
    if (types.includes(current)) sel.value = current;
  }

  async function loadNotatki(q) {
    const list = $("notatki-lista");
    if (list) list.innerHTML = emptyBox("Wczytuję…");
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (q && q.trim().length >= 2) params.set("q", q.trim());
      const res = await api(`/api/notes?${params.toString()}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      note.lista = Array.isArray(data.notatki) ? data.notatki : [];
      if (!q || q.trim().length < 2) {
        note.typy = new Set(note.lista.map((n) => n.typ).filter(Boolean));
        refreshNoteTypes();
      }
      renderNotatki();
    } catch (e) {
      if (list) list.innerHTML = emptyBox("Nie udało się wczytać notatek.");
    }
  }

  async function loadGraf() {
    if (note.graf) return note.graf;
    try {
      const data = await (await api("/api/graph")).json();
      const byId = new Map((data.nodes || []).map((n) => [n.id, n]));
      const incoming = new Map();
      for (const e of data.edges || []) {
        if (!incoming.has(e.target)) incoming.set(e.target, []);
        const src = byId.get(e.source);
        if (src) incoming.get(e.target).push(src);
      }
      note.graf = { byId, incoming };
    } catch (e) { note.graf = { byId: new Map(), incoming: new Map() }; }
    return note.graf;
  }

  async function openNotatka(id) {
    note.wybrana = id;
    const empty = $("notatki-pusty");
    const art = $("notatka-tresc");
    const meta = $("notatka-meta");
    try {
      const data = await (await api(`/api/note?id=${encodeURIComponent(id)}`)).json();
      if (note.wybrana !== id) return;
      if (data.error) {
        if (empty) { empty.textContent = data.error; empty.classList.remove("hidden"); }
        return;
      }
      if (empty) empty.classList.add("hidden");
      if (art) art.classList.remove("hidden");
      if (meta) meta.classList.remove("hidden");
      const tytul = $("notatka-tytul");
      if (tytul) tytul.textContent = data.title || "";
      const body = $("notatka-body");
      if (body) body.innerHTML = markdown(data.body || "");
      const typ = $("notatka-typ");
      if (typ) typ.textContent = label(data.type);
      const utw = $("notatka-utworzono");
      if (utw) utw.textContent = "—";
      const zm = $("notatka-zmieniono");
      if (zm) zm.textContent = fmtDate(data.modyfikacja);
      const tagBox = $("notatka-tagi");
      if (tagBox) {
        const tags = [...String(data.body || "").matchAll(/(?:^|\s)#([\p{L}\d_-]{2,})/gu)].map((m) => m[1]);
        const unique = [...new Set(tags)];
        tagBox.innerHTML = unique.length
          ? unique.map((t) => `<span class="tag-chip">#${esc(t)}</span>`).join("")
          : `<span class="panele-dim">brak tagów</span>`;
      }
      const bl = $("notatka-backlinki");
      if (bl) {
        const g = await loadGraf();
        const incoming = (g.incoming.get(id) || []).sort((a, b) => a.title.localeCompare(b.title, "pl"));
        bl.innerHTML = incoming.length
          ? incoming.map((n) => `<li><button type="button" class="backlink" data-id="${esc(n.id)}">← ${esc(n.title)}</button></li>`).join("")
          : `<li class="panele-dim">Brak backlinków.</li>`;
        bl.querySelectorAll("[data-id]").forEach((btn) => btn.addEventListener("click", () => openNotatka(btn.dataset.id)));
      }
      const toChat = $("notatka-do-rozmowy");
      if (toChat) {
        toChat.onclick = () => {
          if (typeof setSegment === "function") setSegment("chat");
          const input = $("chat-input");
          if (input) {
            const mention = `[[${data.title}]]`;
            const start = input.selectionStart == null ? input.value.length : input.selectionStart;
            const end = input.selectionEnd == null ? start : input.selectionEnd;
            input.value = input.value.slice(0, start) + mention + input.value.slice(end);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
          }
          flash(0.02);
        };
      }
      document.querySelectorAll("#notatki-lista .note-row").forEach((r) => {
        r.classList.toggle("active", r.dataset.id === id);
      });
    } catch (e) {
      if (empty) { empty.textContent = "Nie udało się wczytać notatki."; empty.classList.remove("hidden"); }
    }
  }

  function initNotatki() {
    const search = $("notatki-szukaj");
    if (search) search.addEventListener("input", () => {
      clearTimeout(note.timer);
      note.timer = setTimeout(() => loadNotatki(search.value), 250);
    });
    ["notatki-typ", "notatki-data"].forEach((id) => {
      const el = $(id);
      if (el) el.addEventListener("change", renderNotatki);
    });
  }

  /* ======================================================================
     Start i wystawienie API dla app.js
     ====================================================================== */
  window.GregaiZadania = { show: () => loadZadania(false) };
  window.GregaiNotatki = { show: () => loadNotatki(($("notatki-szukaj") || {}).value || "") };

  window.addEventListener("DOMContentLoaded", () => {
    if ($("zadania-segment")) {
      initZadania();
      setInterval(() => {
        if (!document.hidden && document.body.classList.contains("segment-zadania")) loadZadania(true);
      }, 20000);
    }
    if ($("notatki-segment")) initNotatki();
  });
})();
