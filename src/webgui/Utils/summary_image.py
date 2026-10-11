# Utils/summary_image.py – Trainingszusammenfassung als Bild (PNG) für Chat, E-Mail oder Strava-Foto
#
# Gleicher Inhalt wie die Seite «Auswertung»: Kennzahlen, Tempo über die Strecke (Original blau, Training rot),
# Höhenprofil und Zeit pro Zone. Daten kommen aus Utils.speed_compare.

from typing import Optional

INK, MUTED, GRID = "#12324a", "#5b7690", "#dbe5ee"
ORIG, TRAIN = "#1f6fd6", "#d6362b"
ZONE_COLORS = ["#9aa9b8", "#7fa8c9", "#5fa777", "#e0b400", "#e87a1c", "#d6362b", "#8e1b14"]
ZONE_TITLES = (("hr", "Zeit pro Pulszone"), ("power", "Zeit pro Leistungszone"), ("cadence", "Zeit pro Kadenzzone"))


def _hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def _num(value, digits=0, dash="–") -> str:
    return dash if value is None else f"{value:.{digits}f}"


def render_summary_png(path, data: dict, summary: Optional[dict], title: str, subtitle: str = "") -> str:
    """Bild schreiben. data: comparison_payload()/training_payload(); summary: training_summary() oder None."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    s = summary or {}
    zones = [(k, t) for k, t in ZONE_TITLES if (s.get("zones") or {}).get(k)]
    fig = plt.figure(figsize=(16, 10.5), dpi=100, facecolor="white")
    gs = GridSpec(3, max(1, len(zones)), figure=fig, height_ratios=[1.15, 3.0, 1.9],
                  left=0.075, right=0.975, top=0.93, bottom=0.05, hspace=0.34, wspace=0.42)
    fig.text(0.03, 0.962, title, fontsize=22, fontweight="bold", color=INK, va="center")
    fig.text(0.975, 0.962, subtitle, fontsize=13, color=MUTED, va="center", ha="right")

    # ---- Kennzahlen ----
    ax = fig.add_subplot(gs[0, :]); ax.axis("off")
    tiles = [("Distanz", f"{_num(data.get('distance_km'), 2)} km"), ("Zeit", _hms(data.get("time_train_s") or 0))]
    if data.get("has_original") and data.get("time_orig_s"):
        diff = data["time_train_s"] - data["time_orig_s"]
        tiles.append(("Original", f"{_hms(data['time_orig_s'])} ({'+' if diff > 0 else '−'}{abs(diff) // 60}:{abs(diff) % 60:02d})"))
    if s:
        tiles += [("Höhenmeter", f"↑ {_num(s.get('ascent_m'))} m  ↓ {_num(s.get('descent_m'))} m"),
                  ("Puls Ø / max", f"{_num(s.get('hr_avg'))} / {_num(s.get('hr_max'))} bpm"),
                  ("Leistung Ø / max", f"{_num(s.get('power_avg'))} / {_num(s.get('power_max'))} W"),
                  ("Kadenz Ø", f"{_num(s.get('cadence_avg'))} spm"),
                  ("Tempo Ø / max", f"{_num(s.get('speed_avg_kmh'), 1)} / {_num(s.get('speed_max_kmh'), 1)} km/h"),
                  ("Arbeit am Seil", f"{_num(s.get('work_kj'))} kJ"),
                  ("Stösse", f"{_num(s.get('strokes'))} · {_num(s.get('m_per_stroke'), 2)} m"),
                  ("Effizienz", f"{_num(s.get('watt_per_bpm'), 3)} W/Puls"),
                  ("Entkopplung", f"{_num(s.get('decoupling_pct'), 1)} %")]
    cols = 6
    for i, (label, value) in enumerate(tiles[:12]):
        x, y = -0.03 + (i % cols) / cols * 1.03, 0.62 - (i // cols) * 0.58
        ax.text(x, y + 0.26, label.upper(), fontsize=10.5, color=MUTED, transform=ax.transAxes)
        ax.text(x, y, value, fontsize=14.5, fontweight="bold", color=INK, transform=ax.transAxes)

    # ---- Tempo über die Strecke, Höhenprofil als graue Fläche darunter ----
    sub = gs[1, :].subgridspec(2, 1, height_ratios=[4, 1], hspace=0.06)
    ax = fig.add_subplot(sub[0]); axe = fig.add_subplot(sub[1], sharex=ax)
    x = data.get("x_km") or []
    if data.get("has_original"):
        ax.plot(x, [v if v is not None else float("nan") for v in data["v_orig"]], color=ORIG, linewidth=2.2, label="Original (GPX)")
    ax.plot(x, [v if v is not None else float("nan") for v in data.get("v_train") or []], color=TRAIN, linewidth=2.2, label="Training")
    ax.set_ylabel("Tempo [km/h]", color=INK); ax.set_ylim(bottom=0)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=12, ncol=2)
    ele = data.get("elevation_m") or []
    if ele:
        axe.fill_between(x, ele, min(ele), color="#cfd9e3")
        axe.set_ylabel("Höhe [m]", color=INK)
    axe.set_xlabel("Strecke [km]", color=INK)
    if x:
        ax.set_xlim(0, x[-1])
    for a in (ax, axe):
        a.grid(axis="y", color=GRID, linewidth=0.8); a.set_axisbelow(True); a.tick_params(colors=MUTED)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(GRID)
    ax.tick_params(labelbottom=False)

    # ---- Zeit pro Zone ----
    for i, (key, ztitle) in enumerate(zones):
        az = fig.add_subplot(gs[2, i])
        rows = [r for r in s["zones"][key] if r["seconds"] > 0 or r["range"]]
        names = [r["zone"] for r in rows]
        colors = [ZONE_COLORS[0 if r["zone"].startswith("unter") else 6 if r["zone"].startswith("über") else int(r["zone"][1])] for r in rows]
        ypos = list(range(len(rows)))[::-1]
        az.barh(ypos, [r["seconds"] / 60 for r in rows], color=colors, height=0.68)
        az.set_yticks(ypos); az.set_yticklabels(names, fontsize=11, color=INK)
        vmax = max([r["seconds"] / 60 for r in rows] + [1])
        for yy, r in zip(ypos, rows):
            az.text(r["seconds"] / 60 + vmax * 0.02, yy, f"{int(r['seconds'] // 60)}:{int(r['seconds'] % 60):02d} · {r['pct']:.0f} %",
                    va="center", fontsize=10.5, color=INK)
        az.set_xlim(0, vmax * 1.32); az.set_title(ztitle, loc="left", fontsize=13, color=MUTED, fontweight="bold")
        az.set_xlabel("Minuten", color=MUTED, fontsize=10); az.tick_params(colors=MUTED)
        for side in ("top", "right", "left"):
            az.spines[side].set_visible(False)
        az.spines["bottom"].set_color(GRID)
    fig.savefig(str(path), facecolor="white")
    plt.close(fig)
    return str(path)
