"""DecentSampler .dspreset exporter."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from exporters.mapping import InstrumentMap


def export_decentsampler(
    imap: InstrumentMap, output_path: Path, samples_relative_to: Path | None = None
) -> Path:
    base = samples_relative_to or output_path.parent

    root = ET.Element("DecentSampler", minVersion="1.0")
    ui = ET.SubElement(root, "ui", width="812", height="375")
    tab = ET.SubElement(ui, "tab", name="main")
    ET.SubElement(
        tab, "label", x="0", y="10", width="812", height="30",
        text=imap.name, textSize="24",
    )
    groups = ET.SubElement(root, "groups", attack="0.001", release="0.4")

    rr_count = imap.round_robin_count
    # One group per round-robin pass; DS cycles seqMode round_robin groups
    for rr in range(rr_count):
        attrs = {}
        if rr_count > 1:
            attrs = {"seqMode": "round_robin", "seqPosition": str(rr + 1)}
        group = ET.SubElement(groups, "group", **attrs)
        for zone in imap.zones:
            if zone.round_robin != rr:
                continue
            try:
                sample_ref = zone.sample_path.relative_to(base)
            except ValueError:
                sample_ref = zone.sample_path
            attrib = {
                "path": sample_ref.as_posix(),
                "rootNote": str(zone.root_note),
                "loNote": str(zone.low_note),
                "hiNote": str(zone.high_note),
                "loVel": str(zone.low_vel),
                "hiVel": str(zone.high_vel),
            }
            if zone.has_loop:
                attrib["loopEnabled"] = "true"
                attrib["loopStart"] = str(zone.loop_start)
                attrib["loopEnd"] = str(zone.loop_end)
            ET.SubElement(group, "sample", **attrib)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(str(output_path), encoding="UTF-8", xml_declaration=True)
    return output_path
