# VST Sampling Factory

Automated multisampling pipeline: **Reaper** renders VST presets, **Python** processes the audio, sampler-specific exporters (MPC XPM, SFZ, Kontakt, DecentSampler) build the final keygroup programs.

## Status

**v0.1 — desktop shell.** Navigation, settings snapshot, empty views. No rendering yet.

## Roadmap

| Version | Goal                                                    |
| ------- | ------------------------------------------------------- |
| v0.1    | Desktop GUI shell with navigation and settings          |
| v0.2    | Queue manager and editable project configuration        |
| v0.3    | Reaper integration and MIDI generator                   |
| v0.4    | Automated rendering and WAV processing                  |
| v0.5    | Metadata, reporting, and SQLite database                |
| v0.6    | MPC XPM keygroup export                                 |
| v0.7    | Batch processing of complete preset banks               |
| v1.0    | PyInstaller installer and documentation                 |

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
