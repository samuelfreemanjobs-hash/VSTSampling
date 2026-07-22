# VST Sampling Factory — Usage Guide

## What it does

Turns any VSTi preset into a playable sample instrument:

1. Generates a MIDI timeline covering your note range × velocity layers × round robins.
2. Launches Reaper headlessly to render the whole timeline as one WAV.
3. Slices the render into individual samples using the exact timeline geometry.
4. Trims silence, optionally normalizes, detects sustain loops, runs QC.
5. Writes `instrument.json` + `samples.csv` metadata.
6. Exports keygroup programs: MPC `.xpm`, `.sfz`, DecentSampler `.dspreset` (Kontakt loads the SFZ).

## First-time setup

1. Install Python 3.11+, Reaper, and (for XPM validation) MPC Software.
2. `pip install -r requirements.txt`
3. Open `settings.json` (or the Settings tab) and set:
   - `reaper_path` — full path to `reaper.exe`. Leave empty to auto-detect.
   - `output_dir` — where instrument folders land.
4. **One-time in Reaper**: open Reaper once and make sure your VSTs are scanned
   (Options → Preferences → Plug-ins → VST → Re-scan).

## Plugin names

The `plugin` field of a job must match Reaper's FX-browser name, e.g.:

- `VSTi: Omnisphere (Spectrasonics)`
- `VSTi: Serum (Xfer Records)`
- `VST3i: Pigments (Arturia)`

Copy it exactly from Reaper's FX browser. Alternatively, save a configured
track FX chain in Reaper (`.RfxChain`) and put its path in the job's
`settings_override` as `{"fxchain": "C:/path/chain.RfxChain"}` — this also
captures a fully dialed-in preset, which is more reliable than preset-name
selection for plugins with nonstandard preset handling (Omnisphere included).

## Running a job

1. `python app.py`
2. Queue tab → enter plugin / bank / preset → **Add Job**.
3. **Start Queue**.
4. Watch progress on the Dashboard; results land in
   `output/<Plugin>/<Bank>/<Preset>/`:

```
output/Omnisphere/Factory A/Warm Pad/
├── Samples/           C1_v20.wav … C8_v127.wav
├── instrument.json    full metadata
├── samples.csv        spreadsheet-friendly listing
├── Warm Pad.xpm       MPC keygroup program
├── Warm Pad.sfz       SFZ (also the Kontakt path)
├── Warm Pad.dspreset  DecentSampler
├── timeline.mid       the rendered MIDI plan
└── render.wav         raw long render (delete after verifying)
```

5. Copy the preset folder (`.xpm` + `Samples/`) to your MPC Live's drive.
   Open the XPM in MPC Software first to verify the mapping.

## Settings that matter

| Key | Effect |
| --- | ------ |
| `midi.note_interval_semitones` | 1 = chromatic (large), 3 = minor-third stretch (typical), 12 = octaves (small) |
| `velocities` | One sample per listed velocity. **MPC keygroups max out at 4 layers** — use ≤4 if exporting XPM. |
| `midi.round_robins` | Extra passes per note. SFZ/DecentSampler only; MPC export skips RR >1. |
| `midi.note_length_seconds` / `release_tail_seconds` | Hold time and ring-out captured per sample. Pads want longer tails. |
| `audio.normalize` | Off by default — normalizing per-sample destroys natural velocity volume differences. Leave off unless layering identically-loud zones on purpose. |
| `audio.loop_detection` | Finds sustain loops via autocorrelation; loop points land in every export format. One-shots and evolving pads correctly return "no loop". |

## Sampling profiles (suggested)

| Source | Interval | Velocities | Note length | Tail |
| ------ | -------- | ---------- | ----------- | ---- |
| Pads / strings | 3 | 100 | 6–10 s | 4 s |
| Keys / pianos | 3 | 40, 80, 110, 127 | 4 s | 2 s |
| Basses | 3–6 | 90, 127 | 2 s | 1 s |
| Leads / plucks | 3 | 100, 127 | 2 s | 1 s |

Save different profiles as `settings_override` on each job (queue files are
plain JSON — build a library of them in `presets/`).

## Headless batch runs

The pipeline is importable without the GUI:

```python
from pathlib import Path
from core.config import Config
from core.queue_manager import QueueManager, Job
from core.pipeline import PipelineRunner

config = Config.load(Path("settings.json"))
queue = QueueManager(save_path=Path("database/queue.json"))
for preset in ["Warm Pad", "Analog Brass", "Deep Bass"]:
    queue.add(Job(plugin="VSTi: Omnisphere (Spectrasonics)", bank="Factory", preset=preset))
runner = PipelineRunner(queue, config)
runner.start()
runner.join()   # blocks until the batch finishes
```

Leave it overnight; the Markdown report ends up in `output/Logs/`.

## Known limitations

- **XPM schema**: targets MPC Software 2.10+; validate the first export in
  MPC Software before trusting a big batch. Field defaults may need tuning.
- **Preset selection** uses Reaper's `TrackFX_SetPreset`, which works for
  plugins exposing native preset lists. For Omnisphere-style browsers, use
  the `.RfxChain` route above.
- **One render pass per preset** means a preset change requires a new job —
  by design, so renders are deterministic and resumable.
- Rendering requires a machine where Reaper can open the plugin UI-less;
  first run of a plugin may show an activation dialog — run it once
  interactively first.

## Building the .exe

```powershell
pip install pyinstaller
pyinstaller app.spec
# → dist/VSTSamplingFactory/VSTSamplingFactory.exe
```
