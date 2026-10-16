// static/js/viewer.js – in jeder Seite eingebunden.
// Steuergerät (das erste Gerät, das den PIN eingegeben hat): meldet x-ski, welche Seite gerade angezeigt wird.
// Jedes andere Gerät ist Zuschauer: Bedienelemente gesperrt; während eines Trainings folgt es automatisch der
// Seite des Steuergeräts, ohne Training zeigt es «Warten auf Training». Zuschauer brauchen keinen PIN.
// Mit «Mit PIN steuern» bzw. «Steuerung übernehmen» wird ein Gerät zum Steuergerät.
// Der Server lehnt Steuerbefehle von Zuschauern zusätzlich selbst ab.
(function () {
  "use strict";
  const isTop = window.top === window;
  const here = () => location.pathname + location.search;

  let role = {};

  async function login() {
    const pin = prompt("PIN zum Steuern eingeben:");
    if (pin === null || pin === "") return;
    const send = (takeover) => fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
                                                   body: JSON.stringify({ pin, takeover }) });
    try {
      let res = await send(false), d = await res.json();
      if (!d.ok && d.busy && confirm(d.message)) { res = await send(true); d = await res.json(); }
      if (d.ok) { location.reload(); return; }
      if (d.message && !d.busy) alert(d.message);
    } catch (e) { alert("Anmelden nicht möglich – x-ski startet vielleicht gerade neu."); }
  }

  function loginButton(big) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "xski-login";
    b.textContent = role.controller ? "Steuerung übernehmen" : "Mit PIN steuern";
    b.style.cssText = big
      ? "font:800 24px sans-serif;margin-top:26px;padding:16px 34px;border:none;border-radius:16px;background:#ff7b00;color:#fff;cursor:pointer"
      : "font:700 14px sans-serif;margin-left:10px;padding:5px 10px;border:none;border-radius:8px;background:#ff7b00;color:#fff;cursor:pointer";
    b.addEventListener("click", login);
    return b;
  }

  function lockControls() {
    const css = document.createElement("style");
    css.textContent =
      "button:not(.xski-login), input, select, textarea, a.nav-link:not(.xski-free), .tile, .item, dialog { pointer-events: none !important; }" +
      // Bedienelemente ausblenden statt nur sperren (Platz bleibt, damit die Anzeige nicht verrutscht);
      // in der Kopfzeile ganz weg: Navigation, Profil, Konfiguration, Neu starten/Ausschalten
      "button:not(.xski-login), input[type=button], input[type=submit], input[type=range], select, textarea { visibility: hidden !important; }" +
      ".header-actions > *:not(.xski-free) { display: none !important; }" +
      "#xski-pause-bar button { display: none !important; }" +
      ".xski-login, .xski-free { pointer-events: auto !important; opacity: 1 !important; visibility: visible !important; }" +
      "#xski-viewer-badge { position: fixed; right: 10px; bottom: 10px; z-index: 100001; background: #12324a; color: #fff;" +
      " font: 600 15px sans-serif; padding: 7px 12px; border-radius: 10px; opacity: .95; display: flex; align-items: center; }";
    document.head.appendChild(css);
    document.documentElement.classList.add("xski-viewer");
    if (isTop) {
      const badge = document.createElement("div");
      badge.id = "xski-viewer-badge";
      badge.appendChild(document.createTextNode("Nur Ansicht"));
      badge.appendChild(loginButton(false));
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
    if (role.pin_login) el.firstElementChild.appendChild(loginButton(true));
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
      try { role = await (await fetch("/api/role", { cache: "no-store" })).json(); control = role.control; }
      catch (e) { await new Promise((r) => setTimeout(r, 1500)); }
    }
    // Seiten mit data-xski-stay (z. B. die 3D-Ansicht fürs Tablet) bleiben, wo sie sind: sie haben keine
    // Bedienelemente und zeigen ihren Wartezustand selbst
    const stay = document.documentElement.hasAttribute("data-xski-stay");
    if (control === false && stay) {
      return;
    } else if (control === false) {
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
