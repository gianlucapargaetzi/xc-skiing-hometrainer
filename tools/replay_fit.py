#!/usr/bin/env python3
"""Aufzeichnung (FIT) mit anderen Modellfaktoren neu auf die Strecke rechnen.

Die Leistung, der Puls und die Kadenz gelten an der Stelle der Strecke, an der sie aufgezeichnet wurden; Tempo,
Zeit und GPS werden mit dem Skifahrer-Modell neu berechnet. Mit --target-min wird der Leistungsfaktor so
bestimmt, dass die ganze Strecke genau diese Zeit ergibt.

    .venv/bin/python tools/replay_fit.py trainings/skiErg_….fit "src/routes/Sertig Classic 13k.gpx" \
        --power-scale 2.6 --diagonal 0.9 [--target-min 86] [--out trainings/…_korr.fit]
"""
import argparse
import sys
from pathlib import Path

import fitdecode
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "webgui"))
from Utils.fit_export import FitRecorder, FitSample   # noqa: E402
from Utils.route import Route                         # noqa: E402
from Utils.skier_model import Terrain, VirtualSkier   # noqa: E402

DT = 0.1


def load(path):
    rows = []
    with fitdecode.FitReader(path) as f:
        for fr in f:
            if isinstance(fr, fitdecode.FitDataMessage) and fr.name == "record":
                v = {x.name: x.value for x in fr.fields}
                rows.append((v["timestamp"].timestamp(), v.get("distance") or 0.0, v.get("power") or 0.0,
                             v.get("heart_rate") or 0, v.get("cadence") or 0))
    return rows


def replay(rows, route, *, mass, mu, cda, rho, power_scale, diagonal, power_bias, thr=3.5, hyst=1.0):
    """Gibt [(t, Distanz, Tempo, Leistung, Puls, Kadenz, Steigung)] im Sekundentakt zurück."""
    d = np.array([r[1] for r in rows])
    keep = np.concatenate([[True], np.diff(d) > 1e-6])           # nur Stellen, an denen es vorwärts ging
    d, p = d[keep], np.array([r[2] for r in rows])[keep] * power_bias
    hr, cad = np.array([r[3] for r in rows])[keep], np.array([r[4] for r in rows])[keep]
    end = float(d[-1])
    skier = VirtualSkier(mass_kg=mass, cda_m2=cda, air_density_kg_m3=rho)
    lo, hi = thr - hyst - 0.5, thr + 0.5
    w, t, out, next_out = 0.0, 0.0, [], 0.0
    stalled = 0.0
    while skier.distance_m < end and t < 6 * 3600 and stalled < 20.0:
        x = skier.distance_m
        slope = route.slope_at(x)
        target = max(0.0, min(1.0, (slope - lo) / (hi - lo)))
        w += (target - w) * min(1.0, DT / 3.5)                    # Technikübergang über ~3 Stösse
        power = float(np.interp(x + 2.0, d, p))                   # 2 m voraus: am Startpunkt ist die Leistung noch 0
        skier.step(DT, Terrain(slope_percent=slope, mu=mu),
                   propulsive_power_w=power * power_scale * (1.0 + w * (diagonal - 1.0)))
        t += DT
        # am Schluss der Aufzeichnung ist die Leistung 0 (Stop kurz vor dem Ziel): nicht ewig weiterrechnen
        stalled = stalled + DT if skier.speed_m_s < 0.05 and x > 0.9 * end else 0.0
        if t >= next_out:
            out.append((t, skier.distance_m, skier.speed_m_s, power, float(np.interp(x, d, hr)), float(np.interp(x, d, cad)), slope))
            next_out += 1.0
    while len(out) > 2 and out[-1][2] < 0.05:
        out.pop()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fit"); ap.add_argument("gpx")
    ap.add_argument("--power-scale", type=float, default=2.6)
    ap.add_argument("--diagonal", type=float, default=0.9)
    ap.add_argument("--mu", type=float, default=0.025)
    ap.add_argument("--mass", type=float, default=78.0)
    ap.add_argument("--power-bias", type=float, default=1.0,
                    help="Korrektur der gespeicherten Leistung (Dateien bis 2026-10-11: 1.156)")
    ap.add_argument("--target-min", type=float, default=None, help="Leistungsfaktor so wählen, dass diese Zeit herauskommt")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows, route = load(a.fit), Route.from_gpx(a.gpx)
    kw = dict(mass=a.mass, mu=a.mu, cda=0.45, rho=1.0, diagonal=a.diagonal, power_bias=a.power_bias)
    k = a.power_scale
    if a.target_min:
        lo, hi = 0.8, 6.0
        for _ in range(30):
            k = (lo + hi) / 2
            lo, hi = (lo, k) if replay(rows, route, power_scale=k, **kw)[-1][0] < a.target_min * 60 else (k, hi)
    out = replay(rows, route, power_scale=k, **kw)
    print(f"Leistungsfaktor {k:.3f}, Diagonal {a.diagonal}, µ {a.mu}: {out[-1][1] / 1000:.2f} km in {out[-1][0] / 60:.1f} min "
          f"(Original {rows[-1][1] / 1000:.2f} km in {(rows[-1][0] - rows[0][0]) / 60:.1f} min), Ø {np.mean([o[3] for o in out]):.0f} W")
    if a.out:
        rec, t0 = FitRecorder(), rows[0][0]
        for t, x, v, p, hr, cad, slope in out:
            pos = route.position_at(x)
            rec.add(FitSample(t=t0 + t, distance_m=x, speed_m_s=v, heart_rate=round(hr) or None, cadence=round(cad) or None,
                              power=p, lat=pos.lat, lon=pos.lon, altitude_m=pos.elevation_m, grade_percent=slope),
                    lap_key=int(x // 1000), lap_trigger=2)
        rec.write(a.out)
        print(f"geschrieben: {a.out} ({len(rec.samples)} s, {len(rec.laps)} Runden)")


if __name__ == "__main__":
    main()
