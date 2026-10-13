#!/usr/bin/env python3
"""Höhen in eine GPX-Datei ohne Höhenangaben eintragen (nur Schweiz, Geländemodell swissALTI3D von swisstopo).

x-ski braucht die Höhe jedes Punkts für die Steigung. GPX-Dateien aus Kartenportalen (z. B. discover.swiss)
enthalten oft nur Koordinaten – die Strecke erscheint dann im Startmenü als «nicht lesbar».

    .venv/bin/python tools/add_elevation.py "src/routes/Engadin Skimarathon 44k.gpx"

Das Original bleibt als «<datei>.orig» daneben erhalten. Auf Seen liefert das Geländemodell die Seehöhe.
"""
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

NS = "http://www.topografix.com/GPX/1/1"
PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"
CHUNK = 150          # Punkte pro Anfrage (die Schnittstelle begrenzt die Länge der Geometrie)


def wgs84_to_lv95(lat: float, lon: float):
    """Näherungsformel von swisstopo (Genauigkeit ~1 m)."""
    p = (lat * 3600.0 - 169028.66) / 10000.0
    l = (lon * 3600.0 - 26782.5) / 10000.0
    e = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    n = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return e, n


def heights(points_lv95):
    """Höhe [m] für jeden Punkt: Profil entlang der Linie abfragen und auf die Punkte zurückrechnen."""
    out = []
    for start in range(0, len(points_lv95), CHUNK - 1):
        part = points_lv95[start:start + CHUNK]
        if len(part) < 2:
            part = points_lv95[start - 1:start + 1]
        geom = {"type": "LineString", "coordinates": [[round(e, 1), round(n, 1)] for e, n in part]}
        r = requests.post(PROFILE_URL, params={"sr": 2056, "nb_points": 2 * len(part), "distinct_points": "true"},
                          json=geom, timeout=60)
        r.raise_for_status()
        prof = r.json()
        # zu jedem Streckenpunkt den nächstgelegenen Profilpunkt nehmen
        for e, n in part:
            best = min(prof, key=lambda q: (q["easting"] - e) ** 2 + (q["northing"] - n) ** 2)
            alt = best["alts"].get("DTM2") or best["alts"].get("COMB") or best["alts"].get("DTM25")
            out.append(float(alt))
        if start + CHUNK - 1 < len(points_lv95):
            out.pop()                      # letzter Punkt ist der erste des nächsten Abschnitts
        print(f"  {min(start + CHUNK, len(points_lv95))}/{len(points_lv95)} Punkte", flush=True)
    return out[:len(points_lv95)]


def main():
    path = Path(sys.argv[1])
    ET.register_namespace("", NS)
    tree = ET.parse(path)
    pts = list(tree.getroot().iter(f"{{{NS}}}trkpt")) or list(tree.getroot().iter(f"{{{NS}}}rtept"))
    missing = [p for p in pts if p.find(f"{{{NS}}}ele") is None]
    if not pts:
        raise SystemExit("Keine Streckenpunkte gefunden.")
    if not missing:
        raise SystemExit("Die Datei hat schon Höhenangaben – nichts zu tun.")
    print(f"{path.name}: {len(pts)} Punkte, {len(missing)} ohne Höhe – frage swisstopo ab …")
    alts = heights([wgs84_to_lv95(float(p.get("lat")), float(p.get("lon"))) for p in pts])
    if len(alts) != len(pts) or any(a is None or math.isnan(a) for a in alts):
        raise SystemExit("Nicht für alle Punkte eine Höhe erhalten (liegt die Strecke in der Schweiz?).")
    backup = path.with_name(path.name + ".orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    for p, a in zip(pts, alts):
        ele = p.find(f"{{{NS}}}ele")
        if ele is None:
            ele = ET.Element(f"{{{NS}}}ele")
            p.insert(0, ele)
        ele.text = f"{a:.1f}"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Höhen eingetragen: {min(alts):.0f}–{max(alts):.0f} m. Original gesichert als {backup.name}")


if __name__ == "__main__":
    main()
