// static/js/session_end.js – «Stop» in allen Trainingsseiten:
// fragen (bei Trainings unter 5 min: speichern oder verwerfen), Training beenden, zurück ins Startmenü.
// Läuft auch aus einem iframe heraus; Abfrage und Wartebildschirm erscheinen im obersten Fenster.
(function () {
  "use strict";
  const top = (() => { try { return window.top.document ? window.top : window; } catch (e) { return window; } })();
  const doc = top.document;

  function fmtTime(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

  function layer(html) {
    const old = doc.getElementById("xski-end-layer");
    if (old) old.remove();
    const el = doc.createElement("div");
    el.id = "xski-end-layer";
    el.style.cssText = "position:fixed;inset:0;z-index:100000;display:grid;place-items:center;" +
      "background:rgba(18,50,74,.55);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif";
    el.innerHTML = `<div style="background:#fff;color:#12324a;border-radius:20px;padding:28px 32px;max-width:720px;
      width:calc(100vw - 48px);box-shadow:0 20px 60px rgba(0,0,0,.35)">${html}</div>`;
    doc.body.appendChild(el);
    return el;
  }

  // Feste Grössen, damit Seiten-CSS (z.B. «button { width: 400px }») die Knöpfe nicht verändert
  const BTN = "font:inherit;width:auto;height:auto;min-width:0;line-height:1.2;margin:0;box-sizing:border-box;";
  // Pausenzeichen als zwei Balken (das Emoji fehlt in der Schrift auf dem Pi)
  const PAUSE_ICON = '<span style="display:inline-block;vertical-align:-2px;width:5px;height:0.9em;background:currentColor;' +
    'margin-right:4px"></span><span style="display:inline-block;vertical-align:-2px;width:5px;height:0.9em;' +
    'background:currentColor;margin-right:10px"></span>';

  function ask(title, text, buttons) {
    return new Promise((resolve) => {
      const btns = buttons.map((b, i) =>
        `<button data-i="${i}" style="${BTN}flex:1 1 200px;font-size:22px;font-weight:700;min-height:72px;padding:10px 22px;
          border-radius:14px;cursor:pointer;border:2px solid ${b.color || "#dbe5ee"};
          background:${b.fill ? b.color : "#fff"};color:${b.fill ? "#fff" : "#12324a"}">${b.label}</button>`).join("");
      const el = layer(`<div style="font-size:30px;font-weight:800;margin-bottom:10px">${title}</div>
        <div style="font-size:20px;line-height:1.4;margin-bottom:22px">${text}</div>
        <div style="display:flex;flex-wrap:wrap;gap:12px">${btns}</div>`);
      el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        el.remove(); resolve(buttons[Number(b.dataset.i)].value);
      }));
    });
  }

  async function backToMenu(saving) {
    layer(`<div style="font-size:26px;font-weight:800">${saving ? "Training wird gespeichert …" : "Training beendet"}</div>
      <div id="xski-end-sub" style="font-size:19px;margin-top:10px;color:#5b7690">Antrieb ist abgeschaltet – zurück zum Startmenü …</div>`);
    for (let i = 0; i < 240; i++) {            // Strava-Upload kann bis ~1 min dauern
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const r = await fetch("/api/launcher", { cache: "no-store" });
        if (r.ok) { top.location.href = "/"; return; }
      } catch (e) { /* x-ski schliesst gerade */ }
    }
    const sub = doc.getElementById("xski-end-sub");
    if (sub) sub.textContent = "Startmenü nicht erreichbar – bitte x-ski neu starten.";
  }

  // ---------------------- Pause / Weiter ----------------------
  // Knöpfe mit data-xski-pause werden automatisch beschriftet («Pause» / «Weiter»).
  // In der Pause erscheint unten eine Leiste mit der Pausenzeit, «Weiter» und «Beenden».
  // «Weiter» startet einen Countdown; danach gibt x-ski den Antrieb frei und der Rückzug spannt das Seil.
  let lastInfo = null;

  window.xskiPause = async function (paused) {
    try {
      const res = await fetch("/api/session/pause", { method: "POST", headers: { "Content-Type": "application/json" },
                                                      body: JSON.stringify(paused === undefined ? {} : { paused }) });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        await ask("Pause", data.message || `Fehler (${res.status})`, [{ label: "OK", value: null }]);
      }
    } catch (e) { /* nächste Abfrage zeigt den Zustand */ }
    refresh();
  };

  function pauseBar(info) {
    let bar = doc.getElementById("xski-pause-bar");
    if (!info || !info.paused) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = doc.createElement("div");
      bar.id = "xski-pause-bar";
      bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99999;display:flex;align-items:center;" +
        "justify-content:center;gap:18px;flex-wrap:wrap;padding:14px 18px;background:#12324a;color:#fff;" +
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;box-shadow:0 -6px 24px rgba(0,0,0,.3)";
      bar.innerHTML = `<span id="xski-pause-title" style="font-size:28px;font-weight:800"></span>
        <span id="xski-pause-sub" style="font-size:17px;opacity:.85"></span>
        <button id="xski-resume" style="${BTN}font-size:24px;font-weight:800;min-height:64px;padding:8px 28px;
          border:none;border-radius:14px;color:#fff;cursor:pointer"></button>
        <button id="xski-pause-stop" style="${BTN}font-size:20px;font-weight:700;min-height:64px;padding:8px 20px;
          border:2px solid #fff;border-radius:14px;background:transparent;color:#fff;cursor:pointer">■ Beenden</button>`;
      doc.body.appendChild(bar);
      // im Countdown bricht der Knopf das Weiterfahren ab (Pause bleibt)
      bar.querySelector("#xski-resume").addEventListener("click", () =>
        window.xskiPause(!!(lastInfo && lastInfo.resume_in_s !== null && lastInfo.resume_in_s !== undefined)));
      bar.querySelector("#xski-pause-stop").addEventListener("click", () => window.xskiStop());
    }
    const counting = info.resume_in_s !== null && info.resume_in_s !== undefined;
    const title = doc.getElementById("xski-pause-title"), sub = doc.getElementById("xski-pause-sub");
    const btn = doc.getElementById("xski-resume");
    bar.style.background = counting ? "#2e7d32" : "#12324a";
    if (counting) {
      title.textContent = `Seil wird gespannt in ${Math.max(1, Math.ceil(info.resume_in_s))} …`;
      sub.textContent = "Griffe festhalten – danach läuft die Uhr weiter";
      btn.textContent = "Abbrechen"; btn.style.background = "#12324a";
    } else {
      title.innerHTML = `${PAUSE_ICON}Pause ${fmtTime(info.paused_s || 0)}`;
      sub.textContent = `Antrieb aus · Uhr angehalten · Training ${fmtTime(info.elapsed_s || 0)}`;
      btn.textContent = "▶ Weiter"; btn.style.background = "#2e7d32";
    }
  }

  async function refresh() {
    try { lastInfo = await (await fetch("/api/session", { cache: "no-store" })).json(); } catch (e) { return; }
    document.querySelectorAll("[data-xski-pause]").forEach((b) => {
      b.disabled = !lastInfo.started;
      if (lastInfo.paused) b.textContent = "▶ Weiter"; else b.innerHTML = `${PAUSE_ICON}Pause`;
      b.title = lastInfo.started ? "" : "Pause ist möglich, sobald das Training läuft";
    });
    pauseBar(lastInfo);
  }

  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest("[data-xski-pause]");
    if (b) window.xskiPause(!(lastInfo && lastInfo.paused));
  });
  // im Countdown öfter nachfragen, damit die Zahl sauber läuft
  (async function loop() {
    await refresh();
    const counting = lastInfo && lastInfo.resume_in_s !== null && lastInfo.resume_in_s !== undefined;
    setTimeout(loop, counting ? 250 : 1000);
  })();

  window.xskiStop = async function () {
    let info = { started: false, elapsed_s: 0, short_s: 300 };
    try { info = await (await fetch("/api/session", { cache: "no-store" })).json(); } catch (e) { /* trotzdem fragen */ }
    let save;
    if (info.started && info.elapsed_s < info.short_s) {
      save = await ask("Kurzes Training", `Das Training dauerte erst ${fmtTime(info.elapsed_s)} min. Soll es gespeichert werden` +
        " (Datei, Strava, E-Mail)?", [
        { label: "Speichern & beenden", value: true, color: "#ff7b00", fill: true },
        { label: "Verwerfen & beenden", value: false, color: "#b91c1c" },
        { label: "Weiter trainieren", value: null },
      ]);
    } else {
      save = await ask("Training beenden?", info.started
        ? `Dauer ${fmtTime(info.elapsed_s)} min. Das Training wird gespeichert, danach geht es zurück zum Startmenü.`
        : "Es wurde noch nichts aufgezeichnet. Zurück zum Startmenü?", [
        { label: "Beenden", value: info.started, color: "#e53935", fill: true },
        { label: "Weiter trainieren", value: null },
      ]);
    }
    if (save === null) return;
    try {
      const res = await fetch("/api/session/end", { method: "POST", headers: { "Content-Type": "application/json" },
                                                    body: JSON.stringify({ save }) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      await ask("Fehler", `Stop konnte nicht gesendet werden (${e.message}).`, [{ label: "OK", value: null }]);
      return;
    }
    const bar = doc.getElementById("xski-pause-bar");
    if (bar) bar.remove();
    backToMenu(save && info.started);
  };
})();
