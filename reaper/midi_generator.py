"""Note-plan generation and Standard MIDI File writing.

The sampling strategy: lay every (note, velocity, round-robin) event on
one sequential timeline, render the whole timeline to a single WAV in
Reaper, then slice it back into individual samples using the slice map
this module emits. One render pass per preset, fully deterministic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

PPQ = 960  # ticks per quarter note
DEFAULT_BPM = 120.0


def note_name(midi_note: int) -> str:
    """MIDI note number to name, C-1 convention (60 = C4... Akai uses C3=60 sometimes;
    we use the common C4=60 / octave = note//12 - 1)."""
    return f"{NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"


@dataclass
class SampleEvent:
    """One rendered sample: a note at a velocity (and round-robin pass)."""

    midi_note: int
    velocity: int
    round_robin: int
    start_seconds: float
    note_length_seconds: float
    slot_length_seconds: float  # note + release tail; slicing window

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.slot_length_seconds

    @property
    def sample_name(self) -> str:
        base = f"{note_name(self.midi_note)}_v{self.velocity}"
        if self.round_robin > 0:
            base += f"_rr{self.round_robin + 1}"
        return base


@dataclass
class NotePlan:
    events: list[SampleEvent]
    total_seconds: float
    bpm: float = DEFAULT_BPM

    def to_slice_map(self) -> dict:
        return {
            "bpm": self.bpm,
            "total_seconds": self.total_seconds,
            "events": [asdict(e) | {"sample_name": e.sample_name} for e in self.events],
        }

    def save_slice_map(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_slice_map(), indent=2), encoding="utf-8")


def build_note_plan(
    lowest_note: int = 24,
    highest_note: int = 108,
    interval_semitones: int = 3,
    velocities: list[int] | None = None,
    round_robins: int = 1,
    note_length_seconds: float = 3.0,
    release_tail_seconds: float = 1.5,
    gap_seconds: float = 0.5,
) -> NotePlan:
    """Sequential timeline: every note x velocity x round-robin gets its
    own slot of (note_length + release_tail), separated by gap_seconds
    of pure silence so slicing never bleeds between samples."""
    if not 0 <= lowest_note <= highest_note <= 127:
        raise ValueError("Note range must satisfy 0 <= low <= high <= 127")
    if interval_semitones < 1:
        raise ValueError("interval_semitones must be >= 1")
    velocities = sorted(set(velocities or [100]))
    if any(not 1 <= v <= 127 for v in velocities):
        raise ValueError("Velocities must be in 1..127")
    if round_robins < 1:
        raise ValueError("round_robins must be >= 1")

    slot = note_length_seconds + release_tail_seconds
    events: list[SampleEvent] = []
    cursor = 0.0
    for note in range(lowest_note, highest_note + 1, interval_semitones):
        for velocity in velocities:
            for rr in range(round_robins):
                events.append(
                    SampleEvent(
                        midi_note=note,
                        velocity=velocity,
                        round_robin=rr,
                        start_seconds=cursor,
                        note_length_seconds=note_length_seconds,
                        slot_length_seconds=slot,
                    )
                )
                cursor += slot + gap_seconds
    return NotePlan(events=events, total_seconds=cursor)


# -- Standard MIDI File writing (type 0, minimal, no dependencies) -----


def _vlq(value: int) -> bytes:
    """Variable-length quantity encoding per the SMF spec."""
    if value < 0:
        raise ValueError("VLQ cannot encode negative values")
    chunks = [value & 0x7F]
    value >>= 7
    while value:
        chunks.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(chunks))


def _seconds_to_ticks(seconds: float, bpm: float) -> int:
    return round(seconds * (bpm / 60.0) * PPQ)


def write_midi_file(plan: NotePlan, path: Path, channel: int = 0) -> Path:
    """Write the note plan as a type-0 SMF."""
    if not 0 <= channel <= 15:
        raise ValueError("channel must be 0..15")

    # Absolute-time event list: (tick, priority, message bytes).
    # Note-offs sort before note-ons at the same tick (priority 0 < 1).
    abs_events: list[tuple[int, int, bytes]] = []
    for e in plan.events:
        on_tick = _seconds_to_ticks(e.start_seconds, plan.bpm)
        off_tick = _seconds_to_ticks(e.start_seconds + e.note_length_seconds, plan.bpm)
        abs_events.append((on_tick, 1, bytes([0x90 | channel, e.midi_note, e.velocity])))
        abs_events.append((off_tick, 0, bytes([0x80 | channel, e.midi_note, 0])))
    abs_events.sort(key=lambda t: (t[0], t[1]))

    track = bytearray()
    # Tempo meta event at tick 0
    usec_per_quarter = round(60_000_000 / plan.bpm)
    track += _vlq(0) + bytes([0xFF, 0x51, 0x03]) + usec_per_quarter.to_bytes(3, "big")

    last_tick = 0
    for tick, _prio, msg in abs_events:
        track += _vlq(tick - last_tick) + msg
        last_tick = tick
    track += _vlq(0) + bytes([0xFF, 0x2F, 0x00])  # end of track

    header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") \
        + (1).to_bytes(2, "big") + PPQ.to_bytes(2, "big")
    chunk = b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + chunk)
    return path
