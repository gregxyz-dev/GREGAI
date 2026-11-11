/* health.js (1.44.0) - czyta /api/health co 10 s, renderuje bez inline stylów. */
(function () {
  "use strict";

  var KEY = "gregai_token";
  var timer = null;

  function token() {
    try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }

  function clear(el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
  }

  function row(list, label, value, tone) {
    if (!list) return;
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    dd.textContent = value == null || value === "" ? "—" : String(value);
    if (tone) dd.className = tone;
    list.appendChild(dt);
    list.appendChild(dd);
  }

  function fill(id, rows) {
    var list = document.getElementById(id);
    if (!list) return;
    clear(list);
    rows.forEach(function (item) { row(list, item[0], item[1], item[2]); });
  }

  function fmtDuration(seconds) {
    if (seconds == null || isNaN(Number(seconds))) return "—";
    var s = Math.max(0, Math.floor(Number(seconds)));
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60), sec = s % 60;
    return d ? d + "d " + h + "h " + m + "m" : (h ? h + "h " + m + "m" : m + "m " + sec + "s");
  }

  function setStatus(ok, text) {
    var el = document.getElementById("health-status");
    if (!el) return;
    el.textContent = text;
    el.className = "health-status" + (ok ? "" : " bad");
  }

  function render(data) {
    setStatus(!!data.ok, data.ok ? "OK" : "uwaga");
    var version = document.getElementById("health-version");
    if (version) version.textContent = "wersja " + (data.version || "?");
    var updated = document.getElementById("health-updated");
    if (updated) updated.textContent = "odczyt " + (data.generated_at || "");

    var service = data.service || {};
    fill("health-service", [
      ["stan", service.active ? "działa" : "nie działa", service.active ? "ok" : "bad"],
      ["systemd", service.state || "—"],
      ["pid", service.pid || "—"],
      ["uptime", service.uptime || fmtDuration(service.uptime_s)],
    ]);

    var system = data.system || {};
    var memory = system.memory || {};
    fill("health-system", [
      ["uptime", system.uptime || fmtDuration(system.uptime_s)],
      ["obciążenie", (system.loadavg || []).join(" / ")],
      ["CPU", (system.cpu_count || "?") + " rdzeni"],
      ["RAM", (memory.used_pct == null ? "—" : memory.used_pct + "%") + " zajęte"],
    ]);

    var koryto = data.koryto || {};
    var spent = koryto.spent_usd || {};
    fill("health-koryto", [
      ["kolejność", (koryto.order || []).join(" → ")],
      ["lokalnie", koryto.local_mode || "—"],
      ["wydano dziś", (spent.dzien == null ? "—" : spent.dzien + " USD") +
        (spent.limit_dzien ? " / " + spent.limit_dzien + " USD" : "")],
    ]);
    var host = document.getElementById("health-providers");
    if (host) {
      clear(host);
      (koryto.providers || []).forEach(function (p) {
        var li = document.createElement("li");
        var name = document.createElement("strong");
        name.textContent = p.name || "?";
        var state = document.createElement("span");
        state.textContent = (p.enabled ? "OK" : "OFF") + " · " +
          (p.calls_today == null ? "?" : p.calls_today) + "/" +
          (p.daily_limit == null ? "?" : p.daily_limit);
        state.className = p.enabled ? "ok" : "bad";
        li.appendChild(name);
        li.appendChild(state);
        host.appendChild(li);
      });
    }

    var vault = data.vault || {};
    fill("health-vault", [
      ["węzły", vault.notes],
      ["krawędzie", vault.edges],
      ["osierocone linki", vault.orphans, vault.orphans ? "bad" : "ok"],
      ["duplikaty", vault.duplicates, vault.duplicates ? "bad" : "ok"],
      ["bez krawędzi", vault.isolated],
      ["zmiana", vault.last_change || "—"],
    ]);

    var wezly = data.wezly || {};
    fill("health-wezly", [
      ["włączone", wezly.enabled ? "tak" : "nie", wezly.enabled ? "ok" : ""],
      ["dziś", (wezly.utworzone_dzis == null ? "—" : wezly.utworzone_dzis) + " / " +
        (wezly.max_day == null ? "?" : wezly.max_day)],
      ["cooldown", wezly.cooldown_left_s ? fmtDuration(wezly.cooldown_left_s) : "brak"],
    ]);

    var profil = data.profil || {};
    fill("health-profil", [
      ["profil", profil.exists ? "zapisany" : "brak (onboarding)"],
      ["ton", profil.ton || "—"],
      ["dowęzłowywanie", profil.auto_dowezlywanie ? "tak" : "nie"],
      ["profil do sieci", profil.profil_do_sieci ? "tak" : "nie"],
    ]);

    var err = document.getElementById("health-error");
    if (err) err.textContent = "";
  }

  function fail(message) {
    setStatus(false, "błąd");
    var err = document.getElementById("health-error");
    if (err) err.textContent = String(message || "Nie udało się odczytać /api/health");
  }

  async function load() {
    var headers = {};
    var saved = token();
    if (saved) headers["X-Gregai-Token"] = saved;
    try {
      var response = await fetch("/api/health", { headers: headers, cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      render(await response.json());
    } catch (e) {
      fail(e && e.message ? e.message : e);
    }
  }

  function boot() {
    load();
    if (timer) clearInterval(timer);
    timer = setInterval(load, 10000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
