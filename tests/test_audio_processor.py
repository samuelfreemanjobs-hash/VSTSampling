"""Tests for core.audio_processor using synthetic signals."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from core.audio_processor import (
    DecayProfile,
    LoopPoints,
    analyze_decay,
    apply_crossfade_loop,
    db_to_amplitude,
    detect_fundamental_hz,
    detect_loop,
    normalize_peak,
    pitch_error_semitones,
    process_sample_file,
    qc_check,
    resample,
    slice_render,
    to_mono,
    trim_silence,
)

SR = 44100


def sine(freq: float, seconds: float, sr: int = SR, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def test_trim_silence_leading_and_trailing() -> None:
    signal = np.concatenate([np.zeros(SR), sine(440, 1.0), np.zeros(SR)])
    trimmed = trim_silence(signal, SR, pad_ms=0.0)
    assert len(trimmed) == pytest.approx(SR, abs=64)


def test_trim_silence_all_silent_returns_empty() -> None:
    assert len(trim_silence(np.zeros(SR), SR)) == 0


def test_normalize_peak() -> None:
    quiet = sine(440, 0.5, amp=0.1)
    normed = normalize_peak(quiet, target_db=-3.0)
    assert np.max(np.abs(normed)) == pytest.approx(db_to_amplitude(-3.0), rel=1e-3)


def test_to_mono_folds_channels() -> None:
    left = sine(440, 0.1)
    stereo = np.stack([left, -left], axis=1)
    mono = to_mono(stereo)
    assert mono.ndim == 1
    assert np.max(np.abs(mono)) < 1e-9  # cancels


def test_resample_halves_length() -> None:
    signal = sine(440, 1.0, sr=44100)
    out = resample(signal, 44100, 22050)
    assert len(out) == pytest.approx(22050, abs=2)


def test_detect_loop_on_steady_tone() -> None:
    signal = sine(220, 3.0)
    loop = detect_loop(signal, SR)
    assert isinstance(loop, LoopPoints)
    assert loop.correlation > 0.9
    # loop length should be close to a multiple of the 220 Hz period
    period = SR / 220
    remainder = loop.length % period
    assert min(remainder, period - remainder) < period * 0.15


def test_detect_loop_on_short_tone() -> None:
    # 1s note (quick-test length) must still find a loop in a steady tone
    signal = sine(220, 1.0)
    loop = detect_loop(signal, SR)
    assert isinstance(loop, LoopPoints)
    assert loop.correlation > 0.9


def test_detect_loop_rejects_noise_burst() -> None:
    rng = np.random.default_rng(7)
    # decaying white noise — no periodic structure
    env = np.exp(-np.linspace(0, 8, SR * 2))
    signal = rng.standard_normal(SR * 2) * env * 0.5
    assert detect_loop(signal, SR) is None


def test_qc_flags_clipping_and_quiet(tmp_path: Path) -> None:
    clipped = np.clip(sine(440, 0.5, amp=2.0), -1.0, 1.0)
    p1 = tmp_path / "clipped.wav"
    sf.write(str(p1), clipped, SR)
    r1 = qc_check(p1)
    assert r1.clipped and not r1.passed

    quiet = sine(440, 0.5, amp=0.001)
    p2 = tmp_path / "quiet.wav"
    sf.write(str(p2), quiet, SR)
    r2 = qc_check(p2)
    assert r2.too_quiet and not r2.clipped and r2.passed  # quiet warns, doesn't fail

    p3 = tmp_path / "silent.wav"
    sf.write(str(p3), np.zeros(SR // 2), SR)
    r3 = qc_check(p3)
    assert r3.silent and not r3.passed


def test_crossfade_loop_smooths_seam() -> None:
    # Two different-amplitude halves so the seam has a discontinuity
    sr = SR
    a = 0.6 * np.sin(2 * np.pi * 200 * np.arange(sr) / sr)
    b = 0.2 * np.sin(2 * np.pi * 200 * np.arange(sr) / sr + 1.0)
    signal = np.concatenate([a, b])[:, None]
    loop = LoopPoints(start_frame=sr // 2, end_frame=sr + sr // 2, correlation=0.6)
    faded = apply_crossfade_loop(signal, loop, sr, fade_seconds=0.05)
    # Discontinuity at the wrap = |value just before loop_end - value at loop_start|
    seam_before = abs(faded[loop.end_frame - 1, 0] - signal[loop.start_frame, 0])
    raw_before = abs(signal[loop.end_frame - 1, 0] - signal[loop.start_frame, 0])
    assert seam_before < raw_before  # crossfade reduced the jump
    assert faded.shape == signal.shape


def test_detect_fundamental_and_pitch_error() -> None:
    # A4 = 440 Hz should map to MIDI note 69 with ~0 error
    sr = SR
    t = np.arange(2 * sr) / sr
    signal = 0.5 * np.sin(2 * np.pi * 440 * t)[:, None]
    freq = detect_fundamental_hz(signal, sr)
    assert freq is not None
    assert abs(freq - 440) < 5

    assert abs(pitch_error_semitones(signal, sr, 69)) < 0.2
    # A tone a semitone sharp of the expected note reads ~+1.0
    sharp = 0.5 * np.sin(2 * np.pi * 466.16 * t)[:, None]  # A#4
    err = pitch_error_semitones(sharp, sr, 69)
    assert 0.7 < err < 1.3


def test_pitch_error_folds_octaves() -> None:
    # Patch voiced an octave down should NOT flag as an error
    sr = SR
    t = np.arange(2 * sr) / sr
    down_oct = 0.5 * np.sin(2 * np.pi * 220 * t)[:, None]  # A3
    err = pitch_error_semitones(down_oct, sr, 69)  # expected A4
    assert err is not None
    assert abs(err) < 0.2


def test_pitch_none_for_noise() -> None:
    rng = np.random.default_rng(3)
    noise = (rng.standard_normal(SR) * 0.3)[:, None]
    assert pitch_error_semitones(noise, SR, 60) is None


def test_analyze_decay_percussive(tmp_path: Path) -> None:
    # Held for 6s but the sound is an exponential pluck dying in ~0.4s
    hold = 6.0
    n = int((hold + 4.0) * SR)
    t = np.arange(n) / SR
    env = np.exp(-t / 0.08)
    signal = 0.6 * env * np.sin(2 * np.pi * 220 * t)
    p = tmp_path / "pluck.wav"
    sf.write(str(p), signal, SR)
    profile = analyze_decay(p, hold_seconds=hold)
    assert isinstance(profile, DecayProfile)
    assert profile.percussive is True
    assert profile.note_length_seconds < 2.0


def test_analyze_decay_sustained(tmp_path: Path) -> None:
    # Full-amplitude tone for the whole 3s hold, then a 1.5s release ring
    hold, tail = 3.0, 2.0
    total = hold + tail
    n = int(total * SR)
    t = np.arange(n) / SR
    signal = 0.5 * np.sin(2 * np.pi * 220 * t)
    # release ramp after note-off
    rel = t > hold
    signal[rel] *= np.maximum(0.0, 1.0 - (t[rel] - hold) / 1.5)
    p = tmp_path / "pad.wav"
    sf.write(str(p), signal, SR)
    profile = analyze_decay(p, hold_seconds=hold)
    assert profile.percussive is False
    assert profile.note_length_seconds == hold
    assert profile.release_tail_seconds > 1.0


def test_slice_render_cuts_by_map(tmp_path: Path) -> None:
    # Two 1s tones in 1.5s slots with 0.5s gaps
    slot, gap = 1.5, 0.5
    total = int((slot + gap) * 2 * SR)
    timeline = np.zeros(total)
    timeline[: SR] = sine(440, 1.0)
    second_start = int((slot + gap) * SR)
    timeline[second_start : second_start + SR] = sine(880, 1.0)

    render = tmp_path / "render.wav"
    sf.write(str(render), timeline, SR)
    slice_map = {
        "events": [
            {"sample_name": "C4_v100", "start_seconds": 0.0, "slot_length_seconds": slot},
            {"sample_name": "A5_v100", "start_seconds": slot + gap, "slot_length_seconds": slot},
        ]
    }
    map_path = tmp_path / "render.slices.json"
    map_path.write_text(json.dumps(slice_map))

    out_dir = tmp_path / "samples"
    written = slice_render(render, map_path, out_dir)
    assert [p.name for p in written] == ["C4_v100.wav", "A5_v100.wav"]
    data, sr = sf.read(str(written[0]))
    assert sr == SR
    assert len(data) == pytest.approx(slot * SR, abs=2)


def test_process_sample_file_full_pass(tmp_path: Path) -> None:
    signal = np.concatenate([np.zeros(SR // 2), sine(330, 2.0, amp=0.2), np.zeros(SR // 2)])
    p = tmp_path / "C4_v100.wav"
    sf.write(str(p), signal, SR, subtype="PCM_24")

    meta = process_sample_file(
        p, trim=True, normalize=True, normalize_target_db=-3.0, find_loop=True
    )
    assert meta["silent"] is False
    assert meta["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    assert meta["peak_db"] == pytest.approx(-3.0, abs=0.2)
    assert "loop_start" in meta and meta["loop_end"] > meta["loop_start"]

    data, sr = sf.read(str(p))
    assert sr == SR
    assert np.max(np.abs(data)) == pytest.approx(db_to_amplitude(-3.0), abs=0.01)
