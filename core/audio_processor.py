"""Audio processing: slicing, trimming, normalizing, loop detection, QC.

All functions operate on float32/float64 numpy arrays shaped
(frames,) mono or (frames, channels), as returned by soundfile.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from core.logger import get_logger

log = get_logger(__name__)

_SUBTYPES = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}


def _to_mono_view(data: np.ndarray) -> np.ndarray:
    return data if data.ndim == 1 else data.mean(axis=1)


def db_to_amplitude(db: float) -> float:
    return 10.0 ** (db / 20.0)


def amplitude_to_db(amp: float) -> float:
    return -np.inf if amp <= 0 else 20.0 * np.log10(amp)


# -- slicing -----------------------------------------------------------


def slice_render(
    render_wav: Path,
    slice_map_path: Path,
    output_dir: Path,
    prefix: str = "",
) -> list[Path]:
    """Cut the long Reaper render into one WAV per sample event."""
    slice_map = json.loads(slice_map_path.read_text(encoding="utf-8"))
    data, sr = sf.read(str(render_wav), always_2d=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for event in slice_map["events"]:
        start = int(round(event["start_seconds"] * sr))
        end = int(round((event["start_seconds"] + event["slot_length_seconds"]) * sr))
        chunk = data[start:min(end, len(data))]
        if len(chunk) == 0:
            log.warning("Empty slice for %s — render shorter than plan", event["sample_name"])
            continue
        name = f"{prefix}{event['sample_name']}.wav" if prefix else f"{event['sample_name']}.wav"
        out = output_dir / name
        sf.write(str(out), chunk, sr, subtype="PCM_24")
        written.append(out)
    return written


# -- per-sample transforms --------------------------------------------


def trim_silence(
    data: np.ndarray,
    sr: int,
    threshold_db: float = -60.0,
    pad_ms: float = 5.0,
    trim_tail: bool = True,
) -> np.ndarray:
    """Cut leading (and optionally trailing) audio below threshold_db."""
    mono = np.abs(_to_mono_view(data))
    thresh = db_to_amplitude(threshold_db)
    loud = np.flatnonzero(mono > thresh)
    if len(loud) == 0:
        return data[:0]
    pad = int(sr * pad_ms / 1000.0)
    start = max(0, loud[0] - pad)
    end = min(len(mono), loud[-1] + pad + 1) if trim_tail else len(mono)
    return data[start:end]


def normalize_peak(data: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak <= 0:
        return data
    return (data * (db_to_amplitude(target_db) / peak)).astype(data.dtype)


def to_mono(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        return data
    return data.mean(axis=1).astype(data.dtype)


def resample(data: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return data
    from scipy.signal import resample_poly
    from math import gcd

    g = gcd(sr_from, sr_to)
    up, down = sr_to // g, sr_from // g
    if data.ndim == 1:
        return resample_poly(data, up, down).astype(data.dtype)
    return np.stack(
        [resample_poly(data[:, ch], up, down) for ch in range(data.shape[1])], axis=1
    ).astype(data.dtype)


# -- loop detection ----------------------------------------------------


@dataclass
class LoopPoints:
    start_frame: int
    end_frame: int
    correlation: float  # 0..1, how well the loop joins

    @property
    def length(self) -> int:
        return self.end_frame - self.start_frame


def detect_loop(
    data: np.ndarray,
    sr: int,
    search_start_seconds: float = 0.5,
    min_loop_seconds: float = 0.25,
    correlation_threshold: float = 0.90,
) -> LoopPoints | None:
    """Find sustain-region loop points via autocorrelation.

    Searches the region after the attack for the lag with the highest
    normalized autocorrelation, then snaps both ends to rising
    zero-crossings for a click-free join. Returns None when nothing
    correlates well enough (one-shots, evolving pads with no cycle).
    """
    mono = _to_mono_view(data).astype(np.float64)
    duration = len(mono) / sr
    # Scale the attack-skip and minimum loop length down for short
    # samples so a 1s note can still yield a loop; keep the configured
    # values as ceilings for long ones.
    search_start_seconds = min(search_start_seconds, duration * 0.3)
    min_loop_seconds = min(min_loop_seconds, duration * 0.15)
    start = int(search_start_seconds * sr)
    min_lag = max(32, int(min_loop_seconds * sr))
    segment = mono[start:]
    if len(segment) < min_lag * 3:
        return None

    # Unbiased normalized autocorrelation over the sustain segment.
    # Raw autocorrelation at lag k only sums n-k products, so it decays
    # with lag even for a perfectly periodic signal; rescale by n/(n-k).
    seg = segment - segment.mean()
    n = len(seg)
    corr = np.correlate(seg, seg, mode="full")[n - 1 :]
    norm = corr[0]
    if norm <= 0:
        return None
    lags = np.arange(n)
    corr = (corr / norm) * (n / np.maximum(n - lags, 1))

    max_lag = min(n - min_lag, int(len(seg) * 0.75))
    if max_lag <= min_lag:
        return None
    window = corr[min_lag:max_lag]
    best_lag = min_lag + int(np.argmax(window))
    best_corr = float(corr[best_lag])
    if best_corr < correlation_threshold:
        return None

    loop_start = start
    loop_end = start + best_lag
    loop_start = _snap_to_zero_crossing(mono, loop_start)
    loop_end = _snap_to_zero_crossing(mono, loop_end)
    if loop_end - loop_start < min_lag // 2:
        return None
    return LoopPoints(start_frame=loop_start, end_frame=loop_end, correlation=best_corr)


def apply_crossfade_loop(
    data: np.ndarray,
    loop: LoopPoints,
    sr: int,
    fade_seconds: float = 0.05,
) -> np.ndarray:
    """Blend the pre-loop-start audio into the loop end so the wrap is
    seamless even when the two ends don't naturally match (evolving pads).

    Equal-power crossfade: the tail leading up to loop_end is mixed with
    the tail leading up to loop_start, so when playback jumps end->start
    the waveform is continuous. Returns a new array; loop points unchanged.
    """
    fade = int(min(fade_seconds * sr, (loop.end_frame - loop.start_frame) / 2,
                   loop.start_frame))
    if fade < 8:
        return data  # not enough room to fade; leave as-is
    out = data.copy()
    # Ramps (equal power) shaped for the sample's channel layout
    t = np.linspace(0.0, np.pi / 2, fade)
    fade_out = np.cos(t)  # weight for the loop-end audio
    fade_in = np.sin(t)   # weight for the pre-start audio
    if out.ndim == 2:
        fade_out = fade_out[:, None]
        fade_in = fade_in[:, None]
    end_region = out[loop.end_frame - fade:loop.end_frame]
    pre_start = out[loop.start_frame - fade:loop.start_frame]
    out[loop.end_frame - fade:loop.end_frame] = end_region * fade_out + pre_start * fade_in
    return out


def _snap_to_zero_crossing(mono: np.ndarray, frame: int, window: int = 512) -> int:
    lo = max(1, frame - window)
    hi = min(len(mono) - 1, frame + window)
    region = mono[lo:hi]
    rising = np.flatnonzero((region[:-1] <= 0) & (region[1:] > 0))
    if len(rising) == 0:
        return frame
    candidates = rising + lo
    return int(candidates[np.argmin(np.abs(candidates - frame))])


# -- decay probe -------------------------------------------------------


@dataclass
class DecayProfile:
    percussive: bool           # sound dies while the note is still held
    note_length_seconds: float  # recommended hold
    release_tail_seconds: float  # recommended ring-out capture


def analyze_decay(
    path: Path,
    hold_seconds: float,
    threshold_db: float = -60.0,
    min_note_seconds: float = 0.5,
    max_tail_seconds: float = 8.0,
) -> DecayProfile:
    """Classify a probe render (one long held note) and recommend lengths.

    Percussive/decaying source (piano, pluck, drum): sound falls below
    threshold while held -> hold just past the natural decay, short tail.
    Sustained source (pad, organ, strings): still sounding at note-off ->
    keep the configured hold, tail sized to the actual release ring-out.
    """
    data, sr = sf.read(str(path), always_2d=True)
    mono = np.abs(_to_mono_view(data))
    if mono.size == 0:
        return DecayProfile(True, min_note_seconds, 0.5)

    # 50 ms envelope so single-sample zero crossings don't read as decay
    win = max(1, int(sr * 0.05))
    n_win = len(mono) // win
    env = mono[: n_win * win].reshape(n_win, win).max(axis=1)
    thresh = db_to_amplitude(threshold_db)
    loud = np.flatnonzero(env > thresh)
    if len(loud) == 0:
        return DecayProfile(True, min_note_seconds, 0.5)

    last_sound = (loud[-1] + 1) * win / sr
    if last_sound < hold_seconds * 0.9:
        # Died during the hold: percussive. Capture the full natural decay.
        note_length = max(min_note_seconds, min(last_sound + 0.25, hold_seconds))
        return DecayProfile(True, round(note_length, 2), 0.5)

    release = max(0.5, min(last_sound - hold_seconds + 0.3, max_tail_seconds))
    return DecayProfile(False, hold_seconds, round(release, 2))


# -- pitch verification -----------------------------------------------


def detect_fundamental_hz(data: np.ndarray, sr: int) -> float | None:
    """Estimate the fundamental frequency via autocorrelation.

    Returns None for signals with no clear pitch (noise, silence, drums).
    Analyzes a stable mid-portion of the sample, past the attack transient.
    """
    mono = _to_mono_view(data).astype(np.float64)
    if len(mono) < sr // 20:  # < 50 ms, too short to judge
        return None
    # Middle third: past attack, before release
    lo, hi = len(mono) // 3, 2 * len(mono) // 3
    seg = mono[lo:hi] if hi > lo else mono
    seg = seg - seg.mean()
    if np.max(np.abs(seg)) < 1e-6:
        return None

    corr = np.correlate(seg, seg, mode="full")[len(seg) - 1:]
    if corr[0] <= 0:
        return None
    corr = corr / corr[0]

    # Textbook autocorrelation pitch: skip the main lobe by finding the
    # first point where correlation goes negative, THEN take the highest
    # peak after it — that peak sits at the fundamental period. (Taking a
    # raw global argmax locks onto tiny sub-period lags for pure tones.)
    neg = np.flatnonzero(corr < 0)
    if len(neg) == 0:
        return None
    search_from = neg[0]
    max_lag = min(len(corr) - 1, int(sr / 20))   # floor 20 Hz
    min_lag = max(search_from, int(sr / 5000))    # ceiling 5 kHz
    if max_lag <= min_lag:
        return None
    window = corr[min_lag:max_lag]
    peak = min_lag + int(np.argmax(window))
    if corr[peak] < 0.3:
        return None  # weak periodicity: unpitched
    return sr / peak


def hz_to_midi(freq: float) -> float:
    return 69.0 + 12.0 * np.log2(freq / 440.0)


def pitch_error_semitones(data: np.ndarray, sr: int, expected_note: int) -> float | None:
    """Signed semitone error of the rendered pitch vs the expected note.

    None when no clear pitch is found (correctly the case for drums, and
    for pads with strong detuned/unison content). Folds octave errors out
    so a synth patch voiced an octave down doesn't false-alarm."""
    freq = detect_fundamental_hz(data, sr)
    if freq is None:
        return None
    detected = hz_to_midi(freq)
    err = detected - expected_note
    # Fold to nearest octave: many patches are legitimately +/- octaves
    err = err - 12.0 * round(err / 12.0)
    return float(err)


# -- QC ---------------------------------------------------------------


@dataclass
class QCResult:
    path: str
    peak_db: float
    duration_seconds: float
    clipped: bool
    too_quiet: bool
    silent: bool

    @property
    def passed(self) -> bool:
        return not (self.clipped or self.silent)


def qc_check(
    path: Path,
    quiet_threshold_db: float = -40.0,
    clip_threshold: float = 0.999,
    clip_run_frames: int = 4,
) -> QCResult:
    """Flag clipped, suspiciously quiet, or silent renders."""
    data, sr = sf.read(str(path), always_2d=True)
    mono = np.abs(_to_mono_view(data))
    peak = float(mono.max()) if mono.size else 0.0

    # Clipping = a run of consecutive frames pinned at/near full scale
    pinned = mono >= clip_threshold
    clipped = False
    if pinned.any():
        run = 0
        for flag in pinned:
            run = run + 1 if flag else 0
            if run >= clip_run_frames:
                clipped = True
                break

    peak_db = amplitude_to_db(peak)
    return QCResult(
        path=str(path),
        peak_db=round(peak_db, 2) if np.isfinite(peak_db) else -120.0,
        duration_seconds=round(len(mono) / sr, 3),
        clipped=clipped,
        too_quiet=peak_db < quiet_threshold_db,
        silent=peak <= db_to_amplitude(-90.0),
    )


# -- file-level pipeline ----------------------------------------------


def process_sample_file(
    path: Path,
    *,
    trim: bool = True,
    trim_threshold_db: float = -60.0,
    normalize: bool = False,
    normalize_target_db: float = -3.0,
    mono: bool = False,
    target_sample_rate: int | None = None,
    bit_depth: int = 24,
    find_loop: bool = False,
    crossfade_loop: bool = True,
    force_loop: bool = False,
    expected_note: int | None = None,
) -> dict:
    """Apply the configured transforms to one WAV in place.

    find_loop: detect a sustain loop. crossfade_loop: blend the seam so
    it wraps cleanly. force_loop: if strict detection fails, accept a
    lower-confidence loop and rely on the crossfade (for evolving pads).
    expected_note: if given, verify the rendered pitch and report the
    semitone error in metadata.

    Returns a metadata dict (duration, peak, loop points, pitch error).
    """
    data, sr = sf.read(str(path), always_2d=True)

    if trim:
        data = trim_silence(data, sr, threshold_db=trim_threshold_db)
    if data.size == 0:
        log.warning("%s trimmed to nothing (silent sample)", path.name)
        return {"path": str(path), "silent": True}

    if mono:
        data = to_mono(data)
        if data.ndim == 1:
            data = data[:, np.newaxis]
    if target_sample_rate and target_sample_rate != sr:
        data = resample(data, sr, target_sample_rate)
        sr = target_sample_rate

    # Pitch verification before any loop edits touch the waveform
    # (amplitude-independent, so order vs normalize doesn't matter)
    pitch_err = (
        pitch_error_semitones(data, sr, expected_note)
        if expected_note is not None
        else None
    )

    loop = None
    if find_loop:
        loop = detect_loop(data, sr)
        if loop is None and force_loop:
            loop = detect_loop(data, sr, correlation_threshold=0.55)
        if loop is not None and crossfade_loop:
            data = apply_crossfade_loop(data, loop, sr)

    # Normalize LAST: a crossfade can sum in-phase regions above the
    # pre-fade peak, so the target must be enforced after the seam edit.
    if normalize:
        data = normalize_peak(data, target_db=normalize_target_db)

    subtype = _SUBTYPES.get(bit_depth, "PCM_24")
    out = data if data.shape[1] > 1 else data[:, 0]
    sf.write(str(path), out, sr, subtype=subtype)

    peak = float(np.max(np.abs(data)))
    meta: dict = {
        "path": str(path),
        "silent": False,
        "sample_rate": sr,
        "channels": int(data.shape[1]),
        "duration_seconds": round(len(data) / sr, 4),
        "peak_db": round(amplitude_to_db(peak), 2),
    }
    if loop:
        meta["loop_start"] = loop.start_frame
        meta["loop_end"] = loop.end_frame
        meta["loop_correlation"] = round(loop.correlation, 4)
    if pitch_err is not None:
        meta["pitch_error_semitones"] = round(pitch_err, 3)
        meta["pitch_ok"] = abs(pitch_err) <= 0.5
    return meta
