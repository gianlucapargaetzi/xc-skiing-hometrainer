# tcx_export.py

import xml.etree.ElementTree as ET


def write_tcx(records, filename="training_output.tcx", sport_note="SkiErg Training", sport="Rowing"):
    if not records:
        raise ValueError("write_tcx: 'records' ist leer – keine TCX-Erzeugung möglich.")

    NS = {
        "tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
    }

    ET.register_namespace("", NS["tcx"])
    ET.register_namespace("xsi", NS["xsi"])
    ET.register_namespace("ext", NS["ext"])

    root = ET.Element("TrainingCenterDatabase", {
        f"{{{NS['xsi']}}}schemaLocation":
        "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 "
        "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"
    })

    activities = ET.SubElement(root, "Activities")
    activity = ET.SubElement(activities, "Activity", Sport=sport)
    ET.SubElement(activity, "Id").text = records[0]["timestamp"]

    ET.SubElement(activity, "Notes").text = sport_note

    lap = ET.SubElement(activity, "Lap", StartTime=records[0]["timestamp"])
    ET.SubElement(lap, "TotalTimeSeconds").text = str(len(records))
    ET.SubElement(lap, "DistanceMeters").text = str(records[-1].get("distance", 0.0))
    ET.SubElement(lap, "Calories").text = "0"
    ET.SubElement(lap, "Intensity").text = "Active"
    ET.SubElement(lap, "TriggerMethod").text = "Manual"

    track = ET.SubElement(lap, "Track")

    for r in records:
        tp = ET.SubElement(track, "Trackpoint")
        ET.SubElement(tp, "Time").text = r["timestamp"]
        ET.SubElement(tp, "DistanceMeters").text = str(r.get("distance", 0.0))

        hr_value = int(float(r.get("heart_rate", 0) or 0))
        if hr_value > 0:
            hr = ET.SubElement(tp, "HeartRateBpm")
            ET.SubElement(hr, "Value").text = str(hr_value)

        cadence_spm = r.get("cadence_spm", r.get("sequence_freq", 0))
        cadence_spm = int(float(cadence_spm)) if cadence_spm and float(cadence_spm) > 0 else 0
        if cadence_spm > 0:
            ET.SubElement(tp, "Cadence").text = str(cadence_spm)

        power_watts = float(r.get("power", 0) or 0)
        torque = float(r.get("torque", 0) or 0)
        if power_watts > 0 or torque > 0:
            extensions = ET.SubElement(tp, "Extensions")
            tpx = ET.SubElement(extensions, f"{{{NS['ext']}}}TPX")
            if power_watts > 0:
                ET.SubElement(tpx, f"{{{NS['ext']}}}Watts").text = str(round(power_watts, 2))
            if torque > 0:
                ET.SubElement(tpx, f"{{{NS['ext']}}}Torque").text = str(round(torque, 2))

    tree = ET.ElementTree(root)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"💾 TCX-Datei gespeichert als: {filename}")