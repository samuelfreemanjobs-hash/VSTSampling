# VST Sampling Factory

Automated multisampling pipeline: **Reaper** renders VST presets, **Python** processes the audio, sampler-specific exporters (MPC XPM, SFZ, Kontakt, DecentSampler) build the final keygroup programs.

## Status

**v1.0** — full pipeline implemented and unit/integration tested (43 tests).
The Reaper render step and MPC XPM import need validation on a machine with
Reaper, real VSTs, and MPC Software installed — see
[docs/USAGE.md](docs/USAGE.md) for the checklist.

## Feature summary

- **Queue** — thread-safe job queue with reorder, pause/resume, cancel,
  JSON persistence, and crash-resume.
- **MIDI generation** — note range × velocity layers × round robins laid on
  one deterministic timeline; dependency-free SMF writer + JSON slice map.
- **Headless Reaper rendering** — `render_job.lua` loads the VSTi (or an
  `.RfxChain`), inserts the MIDI, renders the time selection; Python
  controller supervises with timeout.
- **Audio engine** — slicing, silence trim, peak normalize, mono fold,
  resample, autocorrelation loop detection, clip/quiet/silent QC.
- **Catalog** — SQLite for plugins/banks/presets/runs/samples/exports;
  `instrument.json` + `samples.csv` per instrument; Markdown batch reports.
- **Exporters** — MPC `.xpm` (128-keygroup/4-layer limits enforced), SFZ
  (loops + round robins), DecentSampler `.dspreset`, Kontakt via SFZ import.

## Requirements

- Windows 10/11 (Reaper is cross-platform but the MPC toolchain is Windows/macOS)
- Python 3.11+
- Reaper 7.x with the SWS extension
- Akai MPC Software (for XPM validation and MPC Live sync)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Layout

```
VSTSampling/
├── app.py                # Entry point
├── settings.json         # User config
├── requirements.txt
├── core/                 # Config, logging, queue, DB, audio processor
├── ui/                   # CustomTkinter views
├── reaper/               # Reaper controller + MIDI generator
├── exporters/            # MPC, SFZ, Kontakt, DecentSampler writers
├── database/             # SQLite catalog
├── logs/                 # Rotating app log
├── output/               # Rendered samples and keygroups
├── presets/              # Preset bank manifests (CSV/JSON)
└── tests/
```

## Architecture

```
                 CustomTkinter GUI
                        │
                Application Controller
                        │
              ┌─────────┼──────────┐
              ▼         ▼          ▼
        Queue     Preset      Render
        Manager   Manager     Workers
              │         │          │
              └─────────┼──────────┘
                        ▼
              Reaper Integration Layer
                        │
                        ▼
              Reaper + VST Instruments
                        │
                        ▼
                Audio Processor
                        │
                        ▼
                Export Manager
                        │
        ┌───────────┬───┴───┬────────────────┐
        ▼           ▼       ▼                ▼
       MPC         SFZ    Kontakt      DecentSampler
```

## Running the tests

```powershell
pip install pytest
python -m pytest
```

## License

Personal project — no license declared yet.
