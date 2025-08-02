# tcx_export.py

import xml.etree.ElementTree as ET

def write_tcx(records, filename="training_output.tcx", sport_note="SkiErg Training"):
    NS = {
        'tcx': "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        'xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'ext': "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
    }

    ET.register_namespace('', NS['tcx'])
    ET.register_namespace('xsi', NS['xsi'])
    ET.register_namespace('ext', NS['ext'])

    root = ET.Element('TrainingCenterDatabase', {
        f"{{{NS['xsi']}}}schemaLocation":
        "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 "
        "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"
    })

    activities = ET.SubElement(root, 'Activities')
    activity = ET.SubElement(activities, 'Activity', Sport="Other")
    ET.SubElement(activity, 'Id').text = records[0]['timestamp']

    ET.SubElement(activity, 'Notes').text = sport_note

    lap = ET.SubElement(activity, 'Lap', StartTime=records[0]['timestamp'])
    ET.SubElement(lap, 'TotalTimeSeconds').text = str(len(records))
    ET.SubElement(lap, 'DistanceMeters').text = "0"
    ET.SubElement(lap, 'Calories').text = "0"
    ET.SubElement(lap, 'Intensity').text = "Active"
    ET.SubElement(lap, 'TriggerMethod').text = "Manual"

    track = ET.SubElement(lap, 'Track')

    for r in records:
        tp = ET.SubElement(track, 'Trackpoint')
        ET.SubElement(tp, 'Time').text = r['timestamp']
        ET.SubElement(tp, 'DistanceMeters').text = str(r.get('distance', 0.0))

        hr = ET.SubElement(tp, 'HeartRateBpm')
        ET.SubElement(hr, 'Value').text = str(r['heart_rate'])
        ET.SubElement(tp, 'Cadence').text = str(int(r['sequence_freq'])) if r['sequence_freq'] > 0 else "0"

        extensions = ET.SubElement(tp, 'Extensions')
        tpx = ET.SubElement(extensions, f"{{{NS['ext']}}}TPX")
        ET.SubElement(tpx, f"{{{NS['ext']}}}Watts").text = str(r['power'])
        ET.SubElement(tpx, f"{{{NS['ext']}}}Torque").text = str(r['torque'])

    tree = ET.ElementTree(root)
    tree.write(filename, encoding='utf-8', xml_declaration=True)
    print(f"💾 TCX-Datei gespeichert als: {filename}")
