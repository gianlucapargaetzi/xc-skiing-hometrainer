#!/usr/bin/env python3
"""Simulator-Training (FIT) mit dem echten Lauf (GPX mit Zeitstempeln) pro Streckenabschnitt vergleichen.

    .venv/bin/python tools/compare_gpx.py trainings/skiErg_….fit "src/routes/Sertig Classic 13k.gpx" \
        [--seg 500] [--png trainings/vergleich.png]

Gibt eine Tabelle (Steigung, Tempo echt / Simulator, Seilleistung) und eine Zusammenfassung nach Gelände aus;
mit --png zusätzlich ein Diagramm (blau = GPX, rot = Aufzeichnung).

Hinweis: In Aufzeichnungen bis und mit 2026-10-11 ist die Leistung (P_W) rund 15 % zu tief gespeichert
(Mittel über Regelzyklen statt über die Zeit); spätere Dateien sind zeitgewichtet und damit korrekt."""
import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "webgui"))
from Utils.speed_compare import TERRAIN as _TERRAIN, load_fit, load_gpx, segments   # noqa: E402

TERRAIN = tuple((f"{name} ({rng})", sel) for name, rng, sel in _TERRAIN)


def report(rows, sim, real):
    print(f"Echt {real[-1][0] / 1000:.2f} km in {real[-1][1] / 60:.1f} min | Simulator {sim[-1][0] / 1000:.2f} km in {sim[-1][1] / 60:.1f} min")
    print(f"{'km':>5} {'Steig%':>6} {'echt':>6} {'Sim':>6} {'Sim/echt':>8} {'P_W':>5} {'spm':>4}")
    for a, _, slope, vr, vs, p, c in rows:
        print(f"{a / 1000:5.1f} {slope:6.1f} {vr:6.1f} {vs:6.1f} {vs / vr if vr else 0:8.2f} {p:5.0f} {c:4.0f}")
    inner = rows[1:-1]                      # ohne Start und Ziel (Anfahren, Auslaufen, Stehen)
    for name, sel in TERRAIN:
        g = [r for r in inner if sel(r[2])]
        if g:
            print(f"{name:26s} n={len(g):2d}  echt {statistics.mean(r[3] for r in g):5.1f}  Sim {statistics.mean(r[4] for r in g):5.1f} km/h  "
                  f"Verhältnis {statistics.mean(r[4] / r[3] for r in g):.2f}  P {statistics.mean(r[5] for r in g):3.0f} W")
    err = statistics.mean(abs(math.log(r[4] / r[3])) for r in inner if r[3] > 0 and r[4] > 0)
    print(f"mittlere Abweichung (log): {err:.3f}  ≈ {100 * (math.exp(err) - 1):.0f} %")


def plot(rows, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    BLUE, RED, INK, MUTED, GRID = "#1f6fd6", "#d6362b", "#12324a", "#5b7690", "#dbe5ee"
    x0 = [r[0] / 1000 for r in rows]
    x1 = [(r[0] + r[1]) / 1000 for r in rows]
    edges = x0 + [x1[-1]]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(14, 7.6), dpi=110, sharex=True,
                                  gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.08})
    for vals, color, label in (([r[3] for r in rows], BLUE, "GPX – echter Lauf"), ([r[4] for r in rows], RED, "Aufzeichnung heute – Simulator")):
        ax.stairs(vals, edges, color=color, linewidth=2.4, label=label, baseline=None)
        ax.plot([(a + b) / 2 for a, b in zip(x0, x1)], vals, "o", color=color, markersize=5, markeredgecolor="white", markeredgewidth=1)
    ax.set_ylabel("Tempo pro Abschnitt [km/h]", color=INK)
    ax.set_ylim(0, max(max(r[3], r[4]) for r in rows) * 1.12)
    ax.legend(loc="upper right", frameon=False, fontsize=12)
    ax.set_title(title, loc="left", color=INK, fontsize=15, fontweight="bold", pad=12)
    slopes = [r[2] for r in rows]
    ax2.bar([(a + b) / 2 for a, b in zip(x0, x1)], slopes, width=[(b - a) * 0.9 for a, b in zip(x0, x1)],
            color=["#8fa3b5" if s >= 0 else "#c5d1dc" for s in slopes])
    ax2.axhline(0, color=MUTED, linewidth=0.8)
    ax2.set_ylabel("Steigung [%]", color=INK)
    ax2.set_xlabel("Strecke [km]", color=INK)
    ax2.set_xlim(0, edges[-1])
    for a in (ax, ax2):
        a.grid(axis="y", color=GRID, linewidth=0.8)
        a.set_axisbelow(True)
        a.tick_params(colors=MUTED)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(GRID)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    print(f"Diagramm gespeichert: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fit")
    ap.add_argument("gpx")
    ap.add_argument("--seg", type=float, default=500.0, help="Abschnittslänge in m (Standard 500)")
    ap.add_argument("--png", default=None, help="Diagramm in diese Datei schreiben")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()
    sim, real = load_fit(args.fit), load_gpx(args.gpx)
    if real[0][1] is None:
        raise SystemExit("Das GPX hat keine Zeitstempel – kein Vergleich mit einem echten Lauf möglich.")
    rows = segments(sim, real, args.seg)
    report(rows, sim, real)
    if args.png:
        plot(rows, args.png, args.title or f"Tempo pro {args.seg:.0f}-m-Abschnitt: echter Lauf und Simulator")


if __name__ == "__main__":
    main()
