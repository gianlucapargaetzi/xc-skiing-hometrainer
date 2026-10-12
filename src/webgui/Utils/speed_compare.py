# Utils/speed_compare.py – Streckentraining (FIT) mit dem Original-Lauf (GPX mit Zeitstempeln) vergleichen
#
# Für die Auswertung nach dem Training (Seite «Tempovergleich») und für tools/compare_gpx.py.
# Die Simulation selbst verwendet die Zeitstempel des GPX nie.

import math
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

import fitdecode

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
SEMICIRCLE_DEG = 180.0 / 2 ** 31      # FIT speichert Positionen in «Semicircles»
ROUTE_MATCH_MAX_M = 60.0              # so nah müssen die GPS-Punkte der Aufzeichnung an einer Strecke liegen

TERRAIN = (("bergab", "< −1 %", lambda s: s < -1), ("flach", "−1…1 %", lambda s: -1 <= s <= 1),
           ("leicht bergauf", "1…3.5 %", lambda s: 1 < s < 3.5), ("steil", "≥ 3.5 %", lambda s: s >= 3.5))


def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def load_gpx(path) -> List[tuple]:
    """[(Distanz m, Zeit s oder None, Höhe m)] des Originals. Zeit ist None, wenn das GPX keine Zeitstempel hat."""
    pts = []
    for p in ET.parse(path).getroot().iter(GPX_NS + "trkpt"):
        t, e = p.find(GPX_NS + "time"), p.find(GPX_NS + "ele")
        ts = None
        if t is not None and t.text:
            try:
                ts = datetime.fromisoformat(t.text.strip().replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
        pts.append((float(p.get("lat")), float(p.get("lon")), float(e.text) if e is not None else 0.0, ts))
    timed = bool(pts) and all(p[3] is not None for p in pts)
    out, d = [], 0.0
    for i, p in enumerate(pts):
        if i:
            d += haversine(pts[i - 1], p)
        out.append((d, (p[3] - pts[0][3]) if timed else None, p[2]))
    return out


def load_fit(path) -> List[tuple]:
    """[(Distanz m, Zeit s, Leistung W, Kadenz)] der Aufzeichnung."""
    out, t0 = [], None
    with fitdecode.FitReader(str(path)) as f:
        for fr in f:
            if isinstance(fr, fitdecode.FitDataMessage) and fr.name == "record":
                v = {x.name: x.value for x in fr.fields}
                ts = v["timestamp"].timestamp()
                t0 = t0 or ts
                out.append((v.get("distance") or 0.0, ts - t0, v.get("power") or 0, v.get("cadence") or 0))
    return out


def value_at(series, dist, col=1):
    if dist >= series[-1][0]:
        return series[-1][col]
    if dist <= series[0][0]:
        return series[0][col]
    lo, hi = 0, len(series) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        lo, hi = (m, hi) if series[m][0] <= dist else (lo, m)
    a, b = series[lo], series[hi]
    r = (dist - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
    return a[col] + r * (b[col] - a[col])


def segments(sim, real, seg_m, section_start_m: float = 0.0, route_length_m: Optional[float] = None):
    """Pro Abschnitt: (Start m ab Trainingsbeginn, Länge m, Steigung %, Tempo Original km/h oder None,
    Tempo Training km/h, Leistung W, Kadenz). section_start_m: Streckenposition, an der das Training begann."""
    scale = real[-1][0] / route_length_m if route_length_m else (real[-1][0] / sim[-1][0] if not section_start_m else 1.0)
    timed = real[0][1] is not None
    rows, k = [], 0
    while k * seg_m < sim[-1][0]:
        a, b = k * seg_m, min((k + 1) * seg_m, sim[-1][0])
        k += 1
        if b - a < min(100.0, seg_m):
            break
        ra, rb = (section_start_m + a) * scale, (section_start_m + b) * scale
        ts = value_at(sim, b) - value_at(sim, a)
        slope = 100 * (value_at(real, rb, 2) - value_at(real, ra, 2)) / max(rb - ra, 1e-6)
        v_real = None
        if timed:
            tr = value_at(real, rb) - value_at(real, ra)
            v_real = (rb - ra) / tr * 3.6 if tr > 0 else None
        part = [r for r in sim if a <= r[0] < b]
        rows.append((a, b - a, slope, v_real, (b - a) / ts * 3.6 if ts > 0 else 0.0,
                     statistics.mean(r[2] for r in part) if part else 0.0, statistics.mean(r[3] for r in part) if part else 0.0))
    return rows


def load_waypoints(gpx_path, section_start_m: float, length_m: float) -> List[dict]:
    """Verpflegungsposten der Strecke («<Strecke>.posten.json») im gelaufenen Abschnitt:
    [{"name", "km"}] mit km ab Trainingsbeginn."""
    import json
    from pathlib import Path
    gpx_path = Path(gpx_path)
    try:
        raw = json.loads(gpx_path.with_name(gpx_path.stem + ".posten.json").read_text(encoding="utf-8")).get("posten", [])
    except (FileNotFoundError, ValueError, AttributeError):
        return []
    out = []
    for w in raw:
        try:
            d = float(w["km"]) * 1000.0 - section_start_m
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 <= d <= length_m:
            out.append({"name": str(w.get("name", "Posten")), "km": round(d / 1000.0, 2), "food": bool(w.get("verpflegung", True))})
    return sorted(out, key=lambda w: w["km"])


def comparison_payload(fit_path, gpx_path, section_start_m: float = 0.0, route_length_m: Optional[float] = None,
                       step_m: float = 100.0, window_m: float = 300.0) -> dict:
    """Daten für die Seite «Tempovergleich»: Tempo über die Strecke (gleitend über window_m) für Original und
    Training, Höhenprofil und eine Zusammenfassung nach Gelände."""
    sim, real = load_fit(fit_path), load_gpx(gpx_path)
    if len(sim) < 10 or sim[-1][0] < 2 * step_m:
        raise ValueError("Die Aufzeichnung ist zu kurz für einen Vergleich.")
    scale = real[-1][0] / route_length_m if route_length_m else 1.0
    timed = real[0][1] is not None
    length = sim[-1][0]
    xs, v_train, v_orig, ele = [], [], [], []
    d = 0.0
    while d <= length + 1e-6:
        a, b = max(0.0, d - window_m / 2), min(length, d + window_m / 2)
        ts = value_at(sim, b) - value_at(sim, a)
        ra, rb = (section_start_m + a) * scale, (section_start_m + b) * scale
        xs.append(round(d / 1000.0, 3))
        v_train.append(round((b - a) / ts * 3.6, 1) if ts > 0 else None)
        if timed:
            tr = value_at(real, rb) - value_at(real, ra)
            v_orig.append(round((rb - ra) / tr * 3.6, 1) if tr > 0 else None)
        ele.append(round(value_at(real, (section_start_m + d) * scale, 2), 1))
        d += step_m
    rows = segments(sim, real, 500.0, section_start_m, route_length_m)
    inner = rows[1:-1] if len(rows) > 4 else rows
    terrain = []
    for name, label, sel in TERRAIN:
        g = [r for r in inner if sel(r[2])]
        if not g:
            continue
        km = sum(r[1] for r in g) / 1000.0
        t_train = sum(r[1] / (r[4] / 3.6) for r in g if r[4] > 0)
        entry = {"name": name, "range": label, "km": round(km, 1), "v_train": round(km * 3600 / t_train, 1) if t_train else None}
        if timed:
            t_orig = sum(r[1] / (r[3] / 3.6) for r in g if r[3])
            entry["v_orig"] = round(km * 3600 / t_orig, 1) if t_orig else None
        terrain.append(entry)
    ra, rb = section_start_m * scale, (section_start_m + length) * scale
    return {
        "has_original": timed,
        "distance_km": round(length / 1000.0, 2),
        "time_train_s": round(sim[-1][1]),
        "time_orig_s": round(value_at(real, rb) - value_at(real, ra)) if timed else None,
        "x_km": xs, "v_train": v_train, "v_orig": v_orig if timed else [], "elevation_m": ele,
        "terrain": terrain,
        "waypoints": load_waypoints(gpx_path, section_start_m, length),
    }


# ---------------------- Kennzahlen und Zeit in Zonen ----------------------

def load_fit_records(path) -> List[dict]:
    """Sekundenwerte der Aufzeichnung: t, distance, speed, hr, cadence, power, altitude."""
    out, t0 = [], None
    with fitdecode.FitReader(str(path)) as f:
        for fr in f:
            if isinstance(fr, fitdecode.FitDataMessage) and fr.name == "record":
                v = {x.name: x.value for x in fr.fields}
                ts = v["timestamp"].timestamp()
                t0 = t0 or ts
                lat, lon = v.get("position_lat"), v.get("position_long")
                out.append({"t": ts - t0, "distance": v.get("distance") or 0.0, "speed": v.get("speed") or 0.0,
                            "hr": v.get("heart_rate"), "cadence": v.get("cadence"), "power": v.get("power"),
                            "altitude": v.get("altitude"), "start": ts,
                            "lat": lat * SEMICIRCLE_DEG if lat is not None else None,
                            "lon": lon * SEMICIRCLE_DEG if lon is not None else None})
    return out


def _pace_seconds(text: str) -> Optional[float]:
    try:
        m, s = text.strip().split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def _pace_bounds(display: str):
    """«>3:09» / «3:03–3:08» / «<2:54» -> (schnellste, langsamste) Sekunden pro 500 m dieser Zone."""
    d = (display or "").strip()
    if d.startswith(">"):
        return _pace_seconds(d[1:]), None
    if d.startswith("<"):
        return None, _pace_seconds(d[1:])
    for sep in ("–", "-"):
        if sep in d:
            a, b = d.split(sep, 1)
            return _pace_seconds(a), _pace_seconds(b)
    return None, None


def _zone_name(key: str, zone: dict) -> str:
    label = str(zone.get("label", "")).strip()
    return key.upper() if not label or label.upper() == key.upper() else f"{key.upper()} {label}"


def _zone_times(values, zones, low_key, high_key, unit, fmt="{:.0f}"):
    """Sekunden pro Zone. values: [(Wert oder None, dt)]. Werte unter Z1 bzw. über Z5 werden eigens gezählt."""
    keys = [k for k in ("z1", "z2", "z3", "z4", "z5") if k in zones]
    rows = [{"zone": "unter Z1", "range": "", "seconds": 0.0}]
    for k in keys:
        lo, hi = zones[k].get(low_key), zones[k].get(high_key)
        rng = f"{fmt.format(lo)}–{fmt.format(hi)} {unit}" if hi is not None else f"ab {fmt.format(lo)} {unit}"
        rows.append({"zone": _zone_name(k, zones[k]), "range": rng, "seconds": 0.0, "lo": lo, "hi": hi})
    rows.append({"zone": "über Z5", "range": "", "seconds": 0.0})
    for v, dt in values:
        if v is None or v <= 0:
            continue
        placed = False
        for r in rows[1:-1]:
            if v >= r["lo"] and (r["hi"] is None or v < r["hi"] + 1):
                r["seconds"] += dt; placed = True
                break
        if not placed:
            (rows[0] if v < rows[1]["lo"] else rows[-1])["seconds"] += dt
    total = sum(r["seconds"] for r in rows) or 1.0
    return [{"zone": r["zone"], "range": r["range"], "seconds": round(r["seconds"]), "pct": round(100 * r["seconds"] / total, 1)}
            for r in rows if r["seconds"] > 0 or r["range"]]


def training_summary(fit_path, targets: Optional[dict] = None, weight_kg: Optional[float] = None) -> dict:
    """Kennzahlen der Einheit und Zeit pro Zone (Puls, Kadenz, Leistung, Pace) für die Auswertungsseite."""
    rec = load_fit_records(fit_path)
    if len(rec) < 2:
        raise ValueError("Die Aufzeichnung ist zu kurz.")
    dts = [max(0.0, min(5.0, b["t"] - a["t"])) for a, b in zip(rec, rec[1:])] + [1.0]
    dur = rec[-1]["t"] - rec[0]["t"]
    dist = rec[-1]["distance"]

    def wmean(key):
        pairs = [(r[key], dt) for r, dt in zip(rec, dts) if r[key]]
        tot = sum(dt for _, dt in pairs)
        return sum(v * dt for v, dt in pairs) / tot if tot else None

    def vmax(key):
        vals = [r[key] for r in rec if r[key]]
        return max(vals) if vals else None

    alts = [r["altitude"] for r in rec if r["altitude"] is not None]
    ascent = sum(max(0.0, b - a) for a, b in zip(alts, alts[1:]))
    descent = sum(max(0.0, a - b) for a, b in zip(alts, alts[1:]))
    work_kj = sum((r["power"] or 0) * dt for r, dt in zip(rec, dts)) / 1000.0
    strokes = sum((r["cadence"] or 0) / 60.0 * dt for r, dt in zip(rec, dts))
    hr_avg, p_avg = wmean("hr"), wmean("power")

    # Entkopplung: Leistung pro Pulsschlag in der zweiten Hälfte gegenüber der ersten (0 % = stabil, negativ = Ermüdung)
    half = rec[0]["t"] + dur / 2

    def ratio(sel):
        pw = [(r["power"], r["hr"]) for r in rec if sel(r) and r["power"] and r["hr"]]
        return (sum(p for p, _ in pw) / sum(h for _, h in pw)) if pw else None
    r1, r2 = ratio(lambda r: r["t"] < half), ratio(lambda r: r["t"] >= half)

    out = {
        "duration_s": round(dur), "distance_km": round(dist / 1000.0, 2),
        "ascent_m": round(ascent) if alts else None, "descent_m": round(descent) if alts else None,
        "hr_avg": round(hr_avg) if hr_avg else None, "hr_max": vmax("hr"),
        "power_avg": round(p_avg) if p_avg else None, "power_max": vmax("power"),
        "cadence_avg": round(wmean("cadence")) if wmean("cadence") else None, "cadence_max": vmax("cadence"),
        "speed_avg_kmh": round(dist / dur * 3.6, 1) if dur > 0 else None,
        "speed_max_kmh": round(vmax("speed") * 3.6, 1) if vmax("speed") else None,
        "work_kj": round(work_kj), "strokes": round(strokes),
        "m_per_stroke": round(dist / strokes, 2) if strokes > 0 else None,
        "watt_per_bpm": round(p_avg / hr_avg, 3) if p_avg and hr_avg else None,
        "watt_per_kg": round(p_avg / weight_kg, 2) if p_avg and weight_kg else None,
        "decoupling_pct": round(100 * (r2 / r1 - 1), 1) if r1 and r2 else None,
        "zones": {},
    }
    if targets:
        z = out["zones"]
        if targets.get("hr_zones"):
            z["hr"] = _zone_times([(r["hr"], dt) for r, dt in zip(rec, dts)], targets["hr_zones"], "low_bpm", "high_bpm", "bpm")
        if targets.get("skierg_spm_zones"):
            z["cadence"] = _zone_times([(r["cadence"], dt) for r, dt in zip(rec, dts)], targets["skierg_spm_zones"], "low_spm", "high_spm", "spm")
        if targets.get("xski_power_zones"):
            z["power"] = _zone_times([(r["power"], dt) for r, dt in zip(rec, dts)], targets["xski_power_zones"], "low_w", "high_w", "W")
        if targets.get("pace_zones"):
            # Pace = Sekunden pro 500 m; schnellere Zone = kleinere Zahl
            rows = []
            for k in ("z1", "z2", "z3", "z4", "z5"):
                if k in targets["pace_zones"]:
                    fast, slow = _pace_bounds(targets["pace_zones"][k].get("display", ""))
                    rows.append({"zone": _zone_name(k, targets["pace_zones"][k]),
                                 "range": f"{targets['pace_zones'][k].get('display', '')} /500 m", "fast": fast, "slow": slow, "seconds": 0.0})
            for r, dt in zip(rec, dts):
                if not r["speed"] or r["speed"] < 0.3:
                    continue
                pace = 500.0 / r["speed"]
                for row in rows:
                    if (row["fast"] is None or pace >= row["fast"]) and (row["slow"] is None or pace < row["slow"] + 1):
                        row["seconds"] += dt
                        break
            total = sum(row["seconds"] for row in rows) or 1.0
            z["pace"] = [{"zone": row["zone"], "range": row["range"], "seconds": round(row["seconds"]),
                          "pct": round(100 * row["seconds"] / total, 1)} for row in rows]
    return out


# ---------------------- beliebige Trainingsdatei auswerten ----------------------

def training_payload(fit_path, step_m: float = 100.0, window_m: float = 300.0) -> dict:
    """Wie comparison_payload, aber ohne Strecke: nur das Tempo des Trainings (und die Höhe aus der Datei)."""
    rec = load_fit_records(fit_path)
    sim = [(r["distance"], r["t"], r["power"] or 0, r["cadence"] or 0) for r in rec]
    if len(sim) < 10 or sim[-1][0] < 2 * step_m:
        raise ValueError("Die Aufzeichnung ist zu kurz für eine Auswertung.")
    alt = [(r["distance"], r["t"], r["altitude"]) for r in rec if r["altitude"] is not None]
    length, xs, v_train, ele, d = sim[-1][0], [], [], [], 0.0
    while d <= length + 1e-6:
        a, b = max(0.0, d - window_m / 2), min(length, d + window_m / 2)
        ts = value_at(sim, b) - value_at(sim, a)
        xs.append(round(d / 1000.0, 3))
        v_train.append(round((b - a) / ts * 3.6, 1) if ts > 0 else None)
        if alt:
            ele.append(round(value_at(alt, d, 2), 1))
        d += step_m
    return {"has_original": False, "distance_km": round(length / 1000.0, 2), "time_train_s": round(sim[-1][1]),
            "time_orig_s": None, "x_km": xs, "v_train": v_train, "v_orig": [], "elevation_m": ele, "terrain": []}


def match_route(rec: List[dict], routes: list) -> Optional[dict]:
    """Strecke finden, auf der die Aufzeichnung gefahren wurde. routes: Route-Objekte (Utils.route).
    Rückgabe {"route": Route, "section_start_m": …} oder None (kein GPS bzw. keine passende Strecke)."""
    import numpy as np
    pts = [(r["lat"], r["lon"]) for r in rec if r["lat"] is not None and r["lon"] is not None]
    if len(pts) < 5:
        return None
    sample = [pts[int(i * (len(pts) - 1) / 8)] for i in range(9)]
    best = None
    for route in routes:
        # Strecke im 10-m-Raster (nicht nur die Stützpunkte des GPX – die können weit auseinanderliegen)
        grid = np.asarray(route._grid)
        lat, lon = np.interp(grid, route._dist, route._lat), np.interp(grid, route._dist, route._lon)
        kx = 111320.0 * math.cos(math.radians(float(lat.mean())))
        err, first_idx = [], None
        for i, (la, lo) in enumerate(sample):
            dist = np.hypot((lat - la) * 110540.0, (lon - lo) * kx)
            err.append(float(dist.min()))
            if i == 0:
                # bei Runden/Schlaufen die früheste Stelle nehmen, die (fast) gleich nah ist
                near = np.nonzero(dist <= dist.min() + 15.0)[0]
                first_idx = int(near[0])
        mean_err = sum(err) / len(err)
        if max(err) <= ROUTE_MATCH_MAX_M and (best is None or mean_err < best[0]):
            best = (mean_err, route, float(grid[first_idx]))
    if best is None:
        return None
    return {"route": best[1], "section_start_m": best[2]}


def fit_overview(path) -> dict:
    """Kurzinfo für die Dateiliste: Start, Dauer, Distanz, GPS ja/nein."""
    rec = load_fit_records(path)
    if not rec:
        raise ValueError("keine Messwerte")
    return {"start": rec[0]["start"], "duration_s": round(rec[-1]["t"] - rec[0]["t"]),
            "distance_km": round(rec[-1]["distance"] / 1000.0, 2),
            "has_gps": any(r["lat"] is not None for r in rec),
            "hr_avg": round(statistics.mean(r["hr"] for r in rec if r["hr"])) if any(r["hr"] for r in rec) else None,
            "power_avg": round(statistics.mean(r["power"] for r in rec if r["power"])) if any(r["power"] for r in rec) else None}
