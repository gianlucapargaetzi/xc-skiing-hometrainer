// static/js/viewer.js – in jeder Seite eingebunden.
// Am Gerät (localhost): meldet x-ski, welche Seite gerade angezeigt wird.
// Auf jedem anderen Gerät (Zuschauer): sperrt alle Bedienelemente. Während eines Trainings wechselt er
// automatisch auf die Seite, die am Gerät offen ist; ohne Training zeigt er nur «Warten auf Training».
// Der Server lehnt Steuerbefehle von Zuschauern zusätzlich selbst ab.
(function () {
  "use strict";
  const isTop = window.top === window;
  const here = () => location.pathname + location.search;

  function lockControls() {
    const css = document.createElement("style");
    css.textContent =
      "button, input, select, textarea, a.nav-link, .tile, .item, dialog { pointer-events: none !important; }" +
      "button, input, select, textarea { opacity: .55 !important; }" +
      "#xski-viewer-badge { position: fixed; right: 10px; bottom: 10px; z-index: 100001; background: #12324a; color: #fff;" +
      " font: 600 15px sans-serif; padding: 7px 12px; border-radius: 10px; opacity: .92; pointer-events: none; }";
    document.head.appendChild(css);
    document.documentElement.classList.add("xski-viewer");
    if (isTop) {
      const badge = document.createElement("div");
      badge.id = "xski-viewer-badge";
      badge.textContent = "Nur Ansicht – gesteuert wird am x-ski";
      (document.body || document.documentElement).appendChild(badge);
    }
  }

  function waiting(on) {
    let el = document.getElementById("xski-viewer-wait");
    if (!on) { if (el) el.remove(); return; }
    if (el) return;
    el = document.createElement("div");
    el.id = "xski-viewer-wait";
    el.style.cssText = "position:fixed;inset:0;z-index:100000;display:grid;place-items:center;background:#f4f8fb;" +
      "color:#12324a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;text-align:center";
    el.innerHTML = '<div><div style="font-size:44px;font-weight:800">Warten auf Training …</div>' +
      '<div style="font-size:20px;color:#5b7690;margin-top:12px">Sobald am x-ski ein Training gestartet wird, erscheint es hier.</div></div>';
    (document.body || document.documentElement).appendChild(el);
  }

  async function follow() {
    // Läuft ein Training? Dann die Seite des Geräts zeigen; sonst nur «Warten auf Training».
    // Fehler (x-ski startet gerade neu) einfach übergehen und weiter nachfragen.
    try {
      const d = await (await fetch("/api/screen", { cache: "no-store" })).json();
      waiting(!d.training);
      if (d.training && d.path && d.path !== here()) { location.href = d.path; return; }
    } catch (e) { /* nächster Versuch */ }
    setTimeout(follow, 1500);
  }

  async function report() {
    try {
      await fetch("/api/screen", { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ path: here() }) });
    } catch (e) { /* x-ski startet neu */ }
  }

  async function init() {
    let control = null;
    for (let i = 0; i < 20 && control === null; i++) {
      try { control = (await (await fetch("/api/role", { cache: "no-store" })).json()).control; }
      catch (e) { await new Promise((r) => setTimeout(r, 1500)); }
    }
    if (control === false) {
      lockControls();
      if (isTop) follow();           // in eingebetteten Seiten (iframe) entscheidet die äussere Seite
    } else if (control === true && isTop) {
      report();
      setInterval(report, 3000);
      window.addEventListener("pageshow", report);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
