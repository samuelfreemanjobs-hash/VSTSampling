"""Kontakt export.

Kontakt's .nki format is proprietary and undocumented; writing it
directly is not feasible. The supported path is SFZ: Kontakt 5.6+
imports SFZ files directly (Files sidebar > drag the .sfz in), and
the SFZ exporter carries key ranges, velocity layers, loops, and
round robins. This module exists so the export manager can present
"Kontakt" as a target and route it to SFZ with a README.
"""
from __future__ import annotations

from pathlib import Path

from exporters.mapping import InstrumentMap
from exporters.sfz import export_sfz

_README = """Kontakt import
==============

Kontakt cannot be written directly (.nki is proprietary). To load this
instrument in Kontakt:

1. Open Kontakt's Files browser.
2. Navigate to this folder and double-click / drag in: {sfz_name}
3. Kontakt converts the SFZ mapping (key ranges, velocity layers,
   loops, round robins) into a new instrument.
4. Save as .nki from Kontakt if you want a native copy.
"""


def export_kontakt(imap: InstrumentMap, output_dir: Path,
                   samples_relative_to: Path | None = None) -> Path:
    sfz_path = output_dir / f"{imap.name}.sfz"
    export_sfz(imap, sfz_path, samples_relative_to=samples_relative_to)
    readme = output_dir / "KONTAKT_IMPORT.txt"
    readme.write_text(_README.format(sfz_name=sfz_path.name), encoding="utf-8")
    return sfz_path
