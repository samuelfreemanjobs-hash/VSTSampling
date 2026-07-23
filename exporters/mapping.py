"""Shared keygroup mapping model consumed by every exporter.

Takes the flat sample list (note, velocity, round-robin, file) and
builds zones: each sampled root note covers the key range up to the
midpoint toward its neighbors; each velocity layer covers from just
above the previous layer to its own value (top layer extends to 127).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Zone:
    sample_path: Path
    root_note: int
    low_note: int
    high_note: int
    low_vel: int
    high_vel: int
    round_robin: int = 0
    loop_start: int | None = None
    loop_end: int | None = None
    frames: int = 0  # sample length in frames (for MPC SliceEnd/loop)

    @property
    def has_loop(self) -> bool:
        return self.loop_start is not None and self.loop_end is not None


@dataclass
class InstrumentMap:
    name: str
    zones: list[Zone] = field(default_factory=list)
    one_shot: bool = False  # drum mode: no pitch tracking, no loops, full decay

    @property
    def root_notes(self) -> list[int]:
        return sorted({z.root_note for z in self.zones})

    @property
    def velocity_layers(self) -> list[int]:
        return sorted({z.high_vel for z in self.zones})

    @property
    def round_robin_count(self) -> int:
        return max((z.round_robin for z in self.zones), default=0) + 1


def build_instrument_map(
    name: str, samples: list[dict[str, Any]], drum_mode: bool = False
) -> InstrumentMap:
    """samples: dicts with file_path, midi_note, velocity, round_robin,
    and optional loop_start/loop_end (as produced by the pipeline).

    drum_mode: each sampled note covers ONLY itself (no stretching across
    gaps — unmapped pads stay silent), zones are one-shots, loops dropped."""
    if not samples:
        raise ValueError("No samples to map")

    roots = sorted({int(s["midi_note"]) for s in samples})
    velocities = sorted({int(s["velocity"]) for s in samples})

    # Key range per root: drum kits pin 1:1; pitched maps split gaps at
    # the midpoint between sampled roots.
    note_range: dict[int, tuple[int, int]] = {}
    for i, root in enumerate(roots):
        if drum_mode:
            note_range[root] = (root, root)
            continue
        low = 0 if i == 0 else (roots[i - 1] + root) // 2 + 1
        high = 127 if i == len(roots) - 1 else (root + roots[i + 1]) // 2
        note_range[root] = (low, high)

    # Velocity range per layer: previous layer + 1 up to own value
    vel_range: dict[int, tuple[int, int]] = {}
    for i, vel in enumerate(velocities):
        low = 1 if i == 0 else velocities[i - 1] + 1
        high = 127 if i == len(velocities) - 1 else vel
        vel_range[vel] = (low, high)

    zones = []
    for s in samples:
        root = int(s["midi_note"])
        vel = int(s["velocity"])
        lo_n, hi_n = note_range[root]
        lo_v, hi_v = vel_range[vel]
        zones.append(
            Zone(
                sample_path=Path(s["file_path"]),
                root_note=root,
                low_note=lo_n,
                high_note=hi_n,
                low_vel=lo_v,
                high_vel=hi_v,
                round_robin=int(s.get("round_robin", 0) or 0),
                loop_start=None if drum_mode else s.get("loop_start"),
                loop_end=None if drum_mode else s.get("loop_end"),
                frames=int(s.get("frames", 0) or 0),
            )
        )
    zones.sort(key=lambda z: (z.root_note, z.low_vel, z.round_robin))
    return InstrumentMap(name=name, zones=zones, one_shot=drum_mode)
