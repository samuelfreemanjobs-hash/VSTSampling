"""MPC keygroup program (.xpm) exporter.

Writes the MPC 2.x XML program format. Hardware constraints enforced:
max 128 keygroups, max 4 velocity layers per keygroup. Round robins
beyond the first pass are skipped with a warning (MPC keygroups have
no native round-robin; layer cycling would change the velocity map).

NOTE: the XPM schema is Akai-proprietary and version-sensitive. This
writer targets MPC Software 2.10+ and needs a validation pass on a
real MPC install; expect to tweak field defaults, not structure.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from core.logger import get_logger
from exporters.mapping import InstrumentMap, Zone

log = get_logger(__name__)

MAX_KEYGROUPS = 128
MAX_LAYERS = 4


class ExportError(RuntimeError):
    pass


def _text(parent: ET.Element, tag: str, value) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = str(value)
    return el


def export_mpc_xpm(imap: InstrumentMap, output_path: Path) -> Path:
    """One <Instrument> (keygroup) per root note, velocity layers within."""
    zones_by_root: dict[int, list[Zone]] = {}
    skipped_rr = 0
    for zone in imap.zones:
        if zone.round_robin > 0:
            skipped_rr += 1
            continue
        zones_by_root.setdefault(zone.root_note, []).append(zone)
    if skipped_rr:
        log.warning(
            "MPC export: %d round-robin zones skipped (keygroups have no RR)",
            skipped_rr,
        )

    roots = sorted(zones_by_root)
    if not roots:
        raise ExportError("No zones to export")
    if len(roots) > MAX_KEYGROUPS:
        raise ExportError(f"{len(roots)} keygroups exceeds MPC limit of {MAX_KEYGROUPS}")
    for root_note, zones in zones_by_root.items():
        if len(zones) > MAX_LAYERS:
            raise ExportError(
                f"Root note {root_note} has {len(zones)} velocity layers; "
                f"MPC keygroups support {MAX_LAYERS}. Re-render with fewer layers "
                f"or export SFZ instead."
            )

    root = ET.Element("MPCVObject")
    version = ET.SubElement(root, "Version")
    _text(version, "File_Version", "2.1")
    _text(version, "Application", "MPC-V")
    _text(version, "Application_Version", "2.10.0")
    _text(version, "Platform", "Windows")

    program = ET.SubElement(root, "Program", type="Keygroup")
    _text(program, "ProgramName", imap.name)
    pads = ET.SubElement(program, "ProgramPads")
    pads.text = ""
    _text(program, "KeygroupMasterTranspose", "0.000000")
    _text(program, "KeygroupNumKeygroups", len(roots))

    instruments = ET.SubElement(program, "Instruments")
    for idx, root_note in enumerate(roots):
        zones = sorted(zones_by_root[root_note], key=lambda z: z.low_vel)
        inst = ET.SubElement(instruments, "Instrument", number=str(idx))
        _text(inst, "LowNote", zones[0].low_note)
        _text(inst, "HighNote", zones[0].high_note)
        _text(inst, "IgnoreBaseNote", "True" if imap.one_shot else "False")
        _text(inst, "OneShot", "True" if imap.one_shot else "False")
        _text(inst, "Polyphony", "16")
        _text(inst, "Volume", "0.707107")
        _text(inst, "Pan", "0.500000")
        _text(inst, "Tune", "0.000000")
        _text(inst, "VolumeAttack", "0.000000")
        _text(inst, "VolumeRelease", "0.100000")

        layers = ET.SubElement(inst, "Layers")
        for layer_num, zone in enumerate(zones, start=1):
            layer = ET.SubElement(layers, "Layer", number=str(layer_num))
            _text(layer, "Active", "True")
            _text(layer, "Volume", "1.000000")
            _text(layer, "Pan", "0.500000")
            _text(layer, "TuneCoarse", "0")
            _text(layer, "TuneFine", "0")
            _text(layer, "VelStart", zone.low_vel)
            _text(layer, "VelEnd", zone.high_vel)
            _text(layer, "RootNote", zone.root_note)
            _text(layer, "SampleName", zone.sample_path.stem)
            _text(layer, "SampleFile", zone.sample_path.name)
            _text(layer, "SliceIndex", "129")
            _text(layer, "Direction", "0")
            _text(layer, "Offset", "0")
            if zone.has_loop:
                _text(layer, "SliceStart", 0)
                _text(layer, "SliceLoopStart", zone.loop_start)
                _text(layer, "SliceLoop", 3)  # forward loop
            else:
                _text(layer, "SliceStart", 0)
                _text(layer, "SliceLoopStart", 0)
                _text(layer, "SliceLoop", 0)

        # Remaining layer slots stay absent; MPC fills defaults on load.

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(str(output_path), encoding="UTF-8", xml_declaration=True)
    return output_path
