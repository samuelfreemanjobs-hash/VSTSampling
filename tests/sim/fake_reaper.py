"""A stand-in for reaper.exe used by the full-pipeline simulation.

Parses Reaper-style CLI args, then executes the REAL render_job.lua via
lupa with a mocked `reaper` API. Notes inserted through the API are
synthesized into an actual WAV on render, honoring the render settings
the script sets. The goal: every line of the production Lua runs.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from lupa import LuaRuntime

PPQ_PER_SECOND = 960.0 * 2.0  # 120 bpm, PPQ 960

KNOWN_PLUGINS = {
    "ReaSynth (Cockos)",
    "Blofeld (Waldorf) (34 out)",
    "Diva (u-he)",
    "Pluck (Test)",   # decays to silence in ~0.4s regardless of hold
    "Kit (Test)",     # drum machine: only a few notes are mapped
}

PRESETS = {
    "ReaSynth (Cockos)": ["Basic", "Soft Sine", "Bright Saw"],
    "Diva (u-he)": ["Init", "Warm Pad", "Solo Lead", "Deep Bass"],
    "Pluck (Test)": ["Nylon", "Steel"],
}

KIT_NOTES = {36, 38, 42, 45, 49}  # the only mapped pads on "Kit (Test)"


class State:
    def __init__(self) -> None:
        self.tracks: list[dict] = []
        self.notes: list[tuple[float, float, int, int]] = []  # start_s, end_s, pitch, vel
        self.time_sel = (0.0, 0.0)
        self.render_info: dict[str, float] = {}
        self.render_strings: dict[str, str] = {}
        self.fx_loaded: list[str] = []
        self.preset: str | None = None
        self.preset_index = 0
        self.quit_called = False

    @property
    def plugin_name(self) -> str:
        if not self.fx_loaded:
            return ""
        name = self.fx_loaded[0]
        for prefix in ("VST3:", "VST:"):
            if name.startswith(prefix):
                return name[len(prefix):].strip()
        return name


def synthesize(state: State) -> Path | None:
    out_dir = state.render_strings.get("RENDER_FILE", "")
    pattern = state.render_strings.get("RENDER_PATTERN", "render")
    if not out_dir:
        return None
    sr = int(state.render_info.get("RENDER_SRATE", 44100))
    channels = int(state.render_info.get("RENDER_CHANNELS", 2))
    total = state.time_sel[1]
    frames = int(math.ceil(total * sr))
    audio = np.zeros(frames, dtype=np.float64)
    plugin = state.plugin_name
    for start_s, end_s, pitch, vel in state.notes:
        if plugin.startswith("Kit") and pitch not in KIT_NOTES:
            continue  # unmapped drum pad: silence
        freq = 440.0 * 2 ** ((pitch - 69) / 12)
        amp = 0.5 * vel / 127.0
        if plugin.startswith(("Pluck", "Kit")):
            # Percussive: short decay independent of note-off
            length = 0.4
            n0 = int(start_s * sr)
            n1 = min(n0 + int(length * sr), frames)
            t = np.arange(n1 - n0) / sr
            env = np.minimum(1.0, t / 0.005) * np.exp(-t / 0.08)
        else:
            n0, n1 = int(start_s * sr), min(int(end_s * sr), frames)
            if n1 <= n0:
                continue
            t = np.arange(n1 - n0) / sr
            seg_len = (n1 - n0) / sr
            env = np.minimum(1.0, np.minimum(t / 0.01, np.maximum(0.0, (seg_len - t) / 0.05)))
        audio[n0:n1] += amp * env * np.sin(2 * np.pi * freq * t)
    data = np.tile(audio[:, None], (1, channels)) if channels > 1 else audio
    out = Path(out_dir) / f"{pattern}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), data, sr, subtype="PCM_24")
    return out


def plugin_matches(query: str) -> bool:
    q = query
    for prefix in ("VST3:", "VST:"):
        if q.startswith(prefix):
            q = q[len(prefix):].strip()
            break
    return q in KNOWN_PLUGINS


def build_reaper_api(lua: LuaRuntime, state: State):
    def Main_OnCommand(cmd, _flag):
        if int(cmd) == 41824:  # render using most recent settings
            synthesize(state)
        elif int(cmd) == 40004:  # quit
            state.quit_called = True

    def InsertTrackAtIndex(_idx, _defaults):
        state.tracks.append({})

    def GetTrack(_proj, idx):
        idx = int(idx)
        return state.tracks[idx] if idx < len(state.tracks) else None

    def TrackFX_AddByName(_track, name, _rec, _instantiate):
        if str(name).endswith(".RfxChain"):
            state.fx_loaded.append(str(name))
            return 0
        if plugin_matches(str(name)):
            state.fx_loaded.append(str(name))
            return 0
        return -1

    def TrackFX_SetPreset(_track, _fx, preset):
        state.preset = str(preset)
        return not str(preset).startswith("BadPreset")

    def TrackFX_GetPresetIndex(_track, _fx):
        presets = PRESETS.get(state.plugin_name, [])
        return (state.preset_index, len(presets))

    def TrackFX_SetPresetByIndex(_track, _fx, idx):
        presets = PRESETS.get(state.plugin_name, [])
        idx = int(idx)
        if 0 <= idx < len(presets):
            state.preset_index = idx
            state.preset = presets[idx]
            return True
        return False

    def TrackFX_GetPreset(_track, _fx, _buf):
        presets = PRESETS.get(state.plugin_name, [])
        if presets:
            return (True, presets[state.preset_index])
        return (False, "")

    def CreateNewMIDIItemInProject(_track, start, end, _qn):
        return {"start": float(start), "end": float(end)}

    def GetActiveTake(item):
        return item

    def AddMediaItemToTrack(_track):
        return {"start": 0.0, "end": 0.0}

    def SetMediaItemPosition(item, pos, _refresh):
        item["start"] = float(pos)
        return True

    def SetMediaItemLength(item, length, _refresh):
        item["end"] = item["start"] + float(length)
        return True

    def AddTakeToMediaItem(item):
        return item

    def PCM_Source_CreateFromType(kind):
        return {"type": str(kind)}

    def SetMediaItemTake_Source(_take, _src):
        return True

    def defer(fn):
        fn()  # synchronous in the mock: "after startup" is now

    def SetMediaTrackInfo_Value(_track, _param, _value):
        return True

    def SetCurrentBPM(_proj, _bpm, _undo):
        return None

    def UpdateArrange():
        return None

    def SetItemStateChunk(item, chunk, _undo):
        # Parse the <SOURCE MIDI> E-lines the way Reaper would.
        ticks_per_second = 2.0 * 960.0  # 120 bpm, PPQ 960 (chunk embeds these)
        tick = 0
        open_notes: dict[int, tuple[int, int]] = {}  # pitch -> (start_tick, vel)
        for line in str(chunk).splitlines():
            parts = line.strip().split()
            if len(parts) == 5 and parts[0] == "E":
                delta, status, d1, d2 = parts[1], parts[2], parts[3], parts[4]
                tick += int(delta)
                st, pitch, vel = int(status, 16), int(d1, 16), int(d2, 16)
                if 0x90 <= st <= 0x9F and vel > 0:
                    open_notes[pitch] = (tick, vel)
                elif 0x80 <= st <= 0x9F and pitch in open_notes:
                    start_tick, note_vel = open_notes.pop(pitch)
                    state.notes.append(
                        (start_tick / ticks_per_second, tick / ticks_per_second,
                         pitch, note_vel)
                    )
            elif len(parts) >= 2 and parts[0] == "LENGTH":
                item["end"] = item.get("start", 0.0) + float(parts[1])
        return True

    def MIDI_CountEvts(_take):
        return (True, len(state.notes), 0, 0)

    def MIDI_GetPPQPosFromProjTime(_take, seconds):
        return float(seconds) * PPQ_PER_SECOND

    def MIDI_InsertNote(_take, _sel, _mut, sppq, eppq, _chan, pitch, vel, _nosort):
        state.notes.append(
            (float(sppq) / PPQ_PER_SECOND, float(eppq) / PPQ_PER_SECOND, int(pitch), int(vel))
        )
        return True

    def MIDI_Sort(_take):
        pass

    def GetSet_LoopTimeRange(is_set, _loop, start, end, _seek):
        if is_set:
            state.time_sel = (float(start), float(end))
        return state.time_sel

    def GetSetProjectInfo(_proj, key, value, is_set):
        if is_set:
            state.render_info[str(key)] = float(value)
        return state.render_info.get(str(key), 0.0)

    def GetSetProjectInfo_String(_proj, key, value, is_set):
        if is_set:
            state.render_strings[str(key)] = str(value)
        return True

    def file_exists(path):
        return Path(str(path)).is_file()

    api = {
        "Main_OnCommand": Main_OnCommand,
        "InsertTrackAtIndex": InsertTrackAtIndex,
        "GetTrack": GetTrack,
        "TrackFX_AddByName": TrackFX_AddByName,
        "TrackFX_SetPreset": TrackFX_SetPreset,
        "TrackFX_GetPresetIndex": TrackFX_GetPresetIndex,
        "TrackFX_SetPresetByIndex": TrackFX_SetPresetByIndex,
        "TrackFX_GetPreset": TrackFX_GetPreset,
        "CreateNewMIDIItemInProject": CreateNewMIDIItemInProject,
        "GetActiveTake": GetActiveTake,
        "AddMediaItemToTrack": AddMediaItemToTrack,
        "SetMediaItemPosition": SetMediaItemPosition,
        "SetMediaItemLength": SetMediaItemLength,
        "AddTakeToMediaItem": AddTakeToMediaItem,
        "PCM_Source_CreateFromType": PCM_Source_CreateFromType,
        "SetMediaItemTake_Source": SetMediaItemTake_Source,
        "SetMediaTrackInfo_Value": SetMediaTrackInfo_Value,
        "SetCurrentBPM": SetCurrentBPM,
        "UpdateArrange": UpdateArrange,
        "SetItemStateChunk": SetItemStateChunk,
        "MIDI_CountEvts": MIDI_CountEvts,
        "defer": defer,
        "MIDI_GetPPQPosFromProjTime": MIDI_GetPPQPosFromProjTime,
        "MIDI_InsertNote": MIDI_InsertNote,
        "MIDI_Sort": MIDI_Sort,
        "GetSet_LoopTimeRange": GetSet_LoopTimeRange,
        "GetSetProjectInfo": GetSetProjectInfo,
        "GetSetProjectInfo_String": GetSetProjectInfo_String,
        "file_exists": file_exists,
    }
    import os
    if os.environ.get("FAKE_REAPER_STARTUP_API_GAP"):
        # Mimic the real-hardware gap: this function missing entirely;
        # the chunk method must carry the job.
        del api["CreateNewMIDIItemInProject"]
    if os.environ.get("FAKE_REAPER_NO_CHUNK_API"):
        # Force the per-note API fallback branch.
        del api["SetItemStateChunk"]
    return lua.table_from(api)


def main(argv: list[str]) -> int:
    # Reaper-style CLI: flags then a positional script path.
    flags = [a for a in argv if a.startswith("-")]
    scripts = [a for a in argv if not a.startswith("-")]
    if "-newinst" not in flags:
        # Mimic single-instance forwarding: swallow the command, exit fast.
        return 0
    if not scripts:
        return 0
    script_path = Path(scripts[-1])
    if not script_path.is_file():
        return 0  # like Reaper: nothing to run

    lua = LuaRuntime(unpack_returned_tuples=True)
    state = State()
    lua.globals().reaper = build_reaper_api(lua, state)
    # loadfile keeps the real source path so script_dir() works as in Reaper
    loader = lua.eval("loadfile")
    res = loader(str(script_path))
    fn, err = res if isinstance(res, tuple) else (res, None)
    if fn is None:
        sys.stderr.write(f"lua load error: {err}\n")
        return 1
    fn()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
