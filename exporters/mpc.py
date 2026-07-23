"""MPC keygroup program (.xpm) exporter.

Writes the MPC 2.x/3.x keygroup XML program format, modeled on the
verified-working template used by intelliriffer's MPC-KeyGroupBuilder
(loads on standalone MPC/Force). Key requirements that a program MUST
satisfy to actually map samples:

- A full <ProgramPads> JSON block.
- A <PadNoteMap> with 128 pad->note entries (without it MPC shows the
  program but maps nothing).
- A <PadGroupMap> with 128 entries.
- Each <Instrument> carries the complete parameter/envelope/LFO set and
  exactly 4 <Layer> slots (unused layers have an empty <SampleName>).
- Samples are referenced by bare <SampleName> (no extension) with an
  EMPTY <SampleFile>; MPC resolves the name against the folder the .xpm
  lives in — so the .xpm MUST sit in the same directory as the WAVs.

Hardware constraints: max 128 keygroups, max 4 velocity layers each.
Round robins beyond the first pass are dropped (keygroups have no RR).
"""
from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from exporters.mapping import InstrumentMap, Zone

log = get_logger(__name__)

MAX_KEYGROUPS = 128
MAX_LAYERS = 4


class ExportError(RuntimeError):
    pass


def _program_pads_json() -> str:
    lines = [
        "{",
        '    "ProgramPads": {',
        '        "Universal": {',
        '            "value0": true',
        "        },",
        '        "Type": {',
        '            "value0": 5',
        "        },",
        '        "universalPad": 5635840,',
        '        "pads": {',
    ]
    pad_lines = [f'            "value{i}": 0' for i in range(128)]
    lines.append(",\n".join(pad_lines))
    lines += [
        "        },",
        '        "UnusedPads": {',
        '            "value0": 1',
        "        }",
        "    }",
        "}",
    ]
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _layer_xml(number: int, zone: Zone | None, one_shot: bool) -> str:
    """One <Layer>. zone=None emits an empty (silent) layer slot."""
    if zone is None:
        sample_name = ""
        root = 0
        vel_start, vel_end = 0, 127
        slice_end = 0
        loop_start = 0
        do_loop = 0
    else:
        sample_name = _xml_escape(zone.sample_path.stem)
        root = zone.root_note
        vel_start, vel_end = zone.low_vel, zone.high_vel
        slice_end = zone.frames or 0
        if zone.has_loop and not one_shot:
            loop_start = zone.loop_start or 0
            do_loop = 1
        else:
            loop_start = 0
            do_loop = 0
    return f"""          <Layer number="{number}">
            <Active>True</Active>
            <Volume>1.000000</Volume>
            <Pan>0.500000</Pan>
            <Pitch>0.000000</Pitch>
            <TuneCoarse>0</TuneCoarse>
            <TuneFine>0</TuneFine>
            <VelStart>{vel_start}</VelStart>
            <VelEnd>{vel_end}</VelEnd>
            <SampleStart>0</SampleStart>
            <SampleEnd>{slice_end}</SampleEnd>
            <Loop>{"True" if do_loop else "False"}</Loop>
            <LoopStart>{loop_start}</LoopStart>
            <LoopEnd>{slice_end}</LoopEnd>
            <LoopCrossfadeLength>0</LoopCrossfadeLength>
            <LoopTune>0</LoopTune>
            <Mute>False</Mute>
            <RootNote>{root}</RootNote>
            <KeyTrack>{"False" if one_shot else "True"}</KeyTrack>
            <SampleName>{sample_name}</SampleName>
            <SampleFile></SampleFile>
            <SliceIndex>129</SliceIndex>
            <Direction>0</Direction>
            <Offset>0</Offset>
            <SliceStart>0</SliceStart>
            <SliceEnd>{slice_end}</SliceEnd>
            <SliceLoopStart>{loop_start}</SliceLoopStart>
            <SliceLoop>{do_loop}</SliceLoop>
            <SliceLoopCrossFadeLength>0</SliceLoopCrossFadeLength>
          </Layer>"""


def _instrument_xml(number: int, zones: list[Zone], one_shot: bool) -> str:
    # zones = the velocity layers for this keygroup, sorted low->high vel
    low = zones[0].low_note
    high = zones[0].high_note
    layers = []
    for i in range(MAX_LAYERS):
        zone = zones[i] if i < len(zones) else None
        layers.append(_layer_xml(i + 1, zone, one_shot))
    layers_xml = "\n".join(layers)
    return f"""      <Instrument number="{number}">
        <TuneCoarse>0</TuneCoarse>
        <TuneFine>0</TuneFine>
        <Mono>False</Mono>
        <Polyphony>16</Polyphony>
        <FilterKeytrack>0.000000</FilterKeytrack>
        <LowNote>{low}</LowNote>
        <HighNote>{high}</HighNote>
        <IgnoreBaseNote>{"True" if one_shot else "False"}</IgnoreBaseNote>
        <ZonePlay>1</ZonePlay>
        <MuteGroup>0</MuteGroup>
        <MuteTarget1>0</MuteTarget1>
        <MuteTarget2>0</MuteTarget2>
        <MuteTarget3>0</MuteTarget3>
        <MuteTarget4>0</MuteTarget4>
        <SimultTarget1>0</SimultTarget1>
        <SimultTarget2>0</SimultTarget2>
        <SimultTarget3>0</SimultTarget3>
        <SimultTarget4>0</SimultTarget4>
        <LfoPitch>0.000000</LfoPitch>
        <LfoCutoff>0.000000</LfoCutoff>
        <LfoVolume>0.000000</LfoVolume>
        <LfoPan>0.000000</LfoPan>
        <OneShot>{"True" if one_shot else "False"}</OneShot>
        <FilterType>2</FilterType>
        <Cutoff>1.000000</Cutoff>
        <Resonance>0.000000</Resonance>
        <FilterEnvAmt>0.000000</FilterEnvAmt>
        <AfterTouchToFilter>0.000000</AfterTouchToFilter>
        <VelocityToStart>0.000000</VelocityToStart>
        <VelocityToFilterAttack>0.000000</VelocityToFilterAttack>
        <VelocityToFilter>0.000000</VelocityToFilter>
        <VelocityToFilterEnvelope>0.000000</VelocityToFilterEnvelope>
        <FilterAttack>0.000000</FilterAttack>
        <FilterDecay>0.047244</FilterDecay>
        <FilterSustain>1.000000</FilterSustain>
        <FilterRelease>0.000000</FilterRelease>
        <FilterHold>0.000000</FilterHold>
        <FilterDecayType>True</FilterDecayType>
        <FilterADEnvelope>True</FilterADEnvelope>
        <VolumeHold>0.000000</VolumeHold>
        <VolumeDecayType>True</VolumeDecayType>
        <VolumeADEnvelope>True</VolumeADEnvelope>
        <VolumeAttack>0.000000</VolumeAttack>
        <VolumeDecay>0.047244</VolumeDecay>
        <VolumeSustain>1.000000</VolumeSustain>
        <VolumeRelease>{"0.010000" if one_shot else "0.100000"}</VolumeRelease>
        <VelocityToPitch>0.000000</VelocityToPitch>
        <VelocityToVolumeAttack>0.000000</VelocityToVolumeAttack>
        <VelocitySensitivity>1.000000</VelocitySensitivity>
        <VelocityToPan>0.000000</VelocityToPan>
        <LFO>
          <Type>Sine</Type>
          <Rate>0.500000</Rate>
          <Sync>0</Sync>
          <Reset>False</Reset>
        </LFO>
        <Layers>
{layers_xml}
        </Layers>
      </Instrument>"""


def _pad_note_map() -> str:
    rows = [
        f'      <PadNote number="{i + 1}">\n        <Note>{i}</Note>\n      </PadNote>'
        for i in range(128)
    ]
    return "<PadNoteMap>\n" + "\n".join(rows) + "\n    </PadNoteMap>"


def _pad_group_map() -> str:
    rows = [
        f'      <PadGroup number="{i + 1}">\n        <Group>0</Group>\n      </PadGroup>'
        for i in range(128)
    ]
    return "<PadGroupMap>\n" + "\n".join(rows) + "\n    </PadGroupMap>"


def export_mpc_xpm(imap: InstrumentMap, output_path: Path) -> Path:
    """Write a keygroup .xpm. IMPORTANT: output_path must be in the same
    directory as the referenced WAV files (MPC resolves SampleName there)."""
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

    instruments = []
    for idx, root_note in enumerate(roots):
        zones = sorted(zones_by_root[root_note], key=lambda z: z.low_vel)
        instruments.append(_instrument_xml(idx, zones, imap.one_shot))
    instruments_xml = "\n".join(instruments)

    pads_json = _xml_escape(_program_pads_json())

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<MPCVObject>
  <Version>
    <File_Version>2.1</File_Version>
    <Application>MPC-V</Application>
    <Application_Version>2.11.6</Application_Version>
    <Platform>Windows</Platform>
  </Version>
  <Program type="Keygroup">
    <ProgramName>{_xml_escape(imap.name)}</ProgramName>
    <ProgramPads>{pads_json}</ProgramPads>
    <Pitch>0.000000</Pitch>
    <TuneCoarse>0</TuneCoarse>
    <TuneFine>0</TuneFine>
    <Mono>False</Mono>
    <Program_Polyphony>16</Program_Polyphony>
    <PortamentoTime>0.000000</PortamentoTime>
    <PortamentoLegato>False</PortamentoLegato>
    <PortamentoQuantized>False</PortamentoQuantized>
    <Program.Xfader.Route>0</Program.Xfader.Route>
    <Instruments>
{instruments_xml}
    </Instruments>
    {_pad_note_map()}
    {_pad_group_map()}
    <KeygroupMasterTranspose>0.000000</KeygroupMasterTranspose>
    <KeygroupNumKeygroups>{len(roots)}</KeygroupNumKeygroups>
    <KeygroupPitchBendRange>2.000000</KeygroupPitchBendRange>
    <KeygroupWheelToLfo>0.000000</KeygroupWheelToLfo>
    <KeygroupAftertouchToFilter>0.000000</KeygroupAftertouchToFilter>
  </Program>
</MPCVObject>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    return output_path
