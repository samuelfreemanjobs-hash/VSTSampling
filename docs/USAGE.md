# VST Sampling Factory — Usage Guide

## What it does

Turns any VSTi preset into a playable sample instrument:

1. Generates a MIDI timeline covering your note range × velocity layers × round robins.
2. Launches Reaper headlessly to render the whole timeline as one WAV.
3. Slices the render into individual samples using the exact timeline geometry.
4. Trims silence, optionally normalizes, detects sustain loops, runs QC.
5. Writes `instrument.json` + `samples.csv` metadata.
6. Exports keygroup programs: MPC `.xpm`, `.sfz`, DecentSampler `.dspreset` (Kontakt loads the SFZ).

## Preset auto-enumeration

Instead of typing preset names, let the app read them from the plugin:

1. Queue tab → pick a plugin from the dropdown.
2. Click **Scan Presets…**. Reaper opens briefly and walks the plugin's
   preset list. A dialog shows every preset with a checkbox.
3. **All** / **None** to bulk-select, or tick individual presets.
4. **Queue Selected** — one job per preset, selected by index (robust
   against odd preset names).

Presets are queued using whatever mode / quick-test / auto-length /
FX-chain options are set at the time. Plugins with their own internal
browser (Omnisphere) expose no presets to Reaper — the scan returns
empty and you should use the FX-chain route instead.

## Keygroup vs Drum-kit mode

The **mode selector** on the Queue tab picks how a source is sampled:

- **Keygroup (pitched)** — the default. Samples every N semitones, stretches
  each sample across the gap to its neighbors, layers velocities, detects
  sustain loops. Right for synths, pianos, pads, strings, basses.
- **Drum kit (one-shots)** — samples every note chromatically at one
  velocity, each sample covers only its own note (no stretching), loops are
  disabled, and the export is a one-shot program (MPC `OneShot=True`,
  SFZ `loop_mode=one_shot`). Notes the kit doesn't map render silent and are
  dropped automatically. Right for the TR-808/909/606/707/727, and any
  drum/percussion instrument.

Use drum mode for your Roland TR machines — sampling them as pitched
keygroups produces nonsense.

## Auto length (decay probing)

Tick **Auto length** and the app renders one long held note per preset
first, measures how the sound behaves, and picks the note length + release
tail automatically:

- **Percussive/decaying** source (piano, pluck, drum) → the sound dies
  while held, so the hold is shortened to just past the natural decay.
- **Sustained** source (pad, organ, strings) → still sounding at note-off,
  so the configured hold is kept and the tail is sized to the actual
  release ring-out.

This costs one extra short render per preset but removes the guesswork of
setting lengths by hand. Without it, lengths come from settings / the
profile table below.

## Quality & reliability options

These are on by default (in `settings.json` under `audio` / `render`):

- **Crossfade looping** (`audio.crossfade_loop`) — blends the loop seam with
  an equal-power crossfade so a loop wraps without a click even when the two
  ends don't naturally match. Normalization runs after the fade so levels
  stay correct.
- **Force loop** (`audio.force_loop`, off by default) — when strict loop
  detection finds nothing, accept a lower-confidence loop and lean on the
  crossfade. Turn this on for evolving pads you want looped no matter what;
  leave off for one-shots and plucks that shouldn't loop.
- **Pitch verification** (`audio.verify_pitch`) — detects each rendered
  sample's fundamental and compares it to the intended note. A sample off by
  more than half a semitone fails QC and is flagged in `instrument.json`
  (`pitch_error_semitones`, `pitch_ok`). Octave-transposed patches are folded
  out so they don't false-alarm; unpitched sources (drums) are skipped.
- **Checkpoint / resume** (`render.resume`) — a finished preset writes a
  `.complete.json` marker. Re-running the same queue skips presets that are
  already done (marker + samples present), so an overnight batch that crashed
  at preset 300 of 500 resumes instead of restarting. Delete the marker (or
  the preset folder) to force a re-render.

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

## MPC AutoSampler feature parity

How this tool compares to the AutoSampler built into MPC Software:

| AutoSampler feature | This tool |
| ------------------- | --------- |
| Note range (low/high) | ✅ `midi.lowest_note` / `highest_note` |
| Note interval (every N semitones) | ✅ `midi.note_interval_semitones` |
| Velocity layers | ✅ `velocities` (any count; MPC XPM capped at 4) |
| Note length (hold) | ✅ setting, or **auto** via decay probe |
| Release tail capture | ✅ `release_tail_seconds`, or **auto** |
| Auto keygroup program creation | ✅ MPC `.xpm` written directly |
| Sample naming (note + velocity) | ✅ `C3_v100.wav` convention |
| Loop detection | ✅ autocorrelation + zero-crossing snap + crossfade seam (AutoSampler has none) |
| Pitch QC | ✅ verifies each sample's rendered pitch (AutoSampler has none) |
| Resume interrupted batch | ✅ checkpoint markers skip finished presets |
| Round robins | ✅ SFZ / DecentSampler (MPC keygroups can't hold RR) |
| Drum / one-shot programs | ✅ drum-kit mode |
| Batch whole preset banks | ✅ preset scan + batch add (AutoSampler is one preset at a time) |
| Multi-format export (SFZ, Kontakt, DecentSampler) | ✅ AutoSampler is MPC-only |
| Sample external hardware via audio input | ❌ not supported — this tool renders VSTi output offline; live audio-input sampling is a possible future addition |

In short: this covers AutoSampler's pitched-instrument and drum workflows,
adds loop detection, auto-length, batch preset processing, and extra export
formats — and omits only hardware-input recording.

## Known limitations

- **XPM schema**: targets MPC Software 2.10+; validate the first export in
  MPC Software before trusting a big batch. Field defaults may need tuning.
- **Preset selection** uses Reaper's preset API (by index after a scan, or
  by name), which works for plugins exposing native preset lists. For
  Omnisphere-style browsers, use the `.RfxChain` route above.
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
