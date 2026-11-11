/* theme.js (1.42.0)
 *
 * Seed motywu PRZED pierwszym malowaniem: skrypt jest ładowany w <head>,
 * przed arkuszami CSS. Zapobiega mignięciu ciemnego tła u osób z jasnym
 * systemem. Wybór: localStorage["gregai.theme"] = auto | light | dark.
 * Ręczny wybór ma pierwszeństwo; "auto" słucha prefers-color-scheme.
 */
(function () {
  "use strict";

  var KEY = "gregai.theme";
  var media = null;
  try { media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null; } catch (e) { media = null; }

  function read() {
    try {
      var v = String(localStorage.getItem(KEY) || "auto").toLowerCase();
      return (v === "light" || v === "dark" || v === "auto") ? v : "auto";
    } catch (e) { return "auto"; }
  }

  function resolved(mode) {
    if (mode === "light" || mode === "dark") return mode;
    return (media && media.matches) ? "light" : "dark";
  }

  function apply(mode) {
    mode = mode || read();
    var visual = resolved(mode);
    var root = document.documentElement;
    var previous = root.getAttribute("data-theme");
    root.setAttribute("data-theme", visual);
    root.setAttribute("data-theme-mode", mode);
    if (previous !== visual) {
      try {
        root.dispatchEvent(new CustomEvent("gregai:theme-change", {
          bubbles: true,
          detail: { theme: visual, mode: mode },
        }));
      } catch (e) { /* starsza przeglądarka bez CustomEvent */ }
    }
    return visual;
  }

  function save(mode) {
    try { localStorage.setItem(KEY, mode); } catch (e) { /* tryb prywatny */ }
    return apply(mode);
  }

  function next(mode) {
    return mode === "auto" ? "light" : mode === "light" ? "dark" : "auto";
  }

  function iconFor(mode, visual) {
    if (mode === "auto") return "◐";
    return visual === "light" ? "☀" : "☾";
  }

  function labelFor(mode, visual) {
    if (mode === "auto") return "Motyw: auto (" + (visual === "light" ? "jasny" : "ciemny") + "). Kliknij: jasny";
    if (mode === "light") return "Motyw: jasny. Kliknij: ciemny";
    return "Motyw: ciemny. Kliknij: auto";
  }

  function syncButtons() {
    var mode = read();
    var visual = resolved(mode);
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      var el = buttons[i];
      el.textContent = iconFor(mode, visual);
      el.setAttribute("title", labelFor(mode, visual));
      el.setAttribute("aria-label", labelFor(mode, visual));
      el.setAttribute("data-theme-mode", mode);
      el.setAttribute("data-theme-resolved", visual);
    }
  }

  function cycle() {
    var visual = save(next(read()));
    syncButtons();
    return visual;
  }

  function bind() {
    syncButtons();
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].dataset.themeBound === "1") continue;
      buttons[i].dataset.themeBound = "1";
      buttons[i].addEventListener("click", cycle);
    }
  }

  apply(read());

  if (media) {
    var onChange = function () { if (read() === "auto") { apply("auto"); syncButtons(); } };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  window.GregAITheme = { get: read, set: save, cycle: cycle, apply: apply, sync: syncButtons };
})();
