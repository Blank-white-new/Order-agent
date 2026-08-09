from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from experiments.barge_in.generate_dataset import SAMPLE_RATE, synthesize_example
from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, sha256_file


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "barge_in_synthetic.jsonl"
DEFAULT_OUTPUT = ROOT / "experiments" / "results" / "barge_in" / "features.csv"
FEATURE_NAMES = (
    "residual_rms",
    "mixture_rms",
    "residual_to_ai_db",
    "zero_crossing_rate",
    "spectral_centroid_hz",
    "spectral_bandwidth_hz",
    "spectral_flatness",
    "onset_strength",
    "active_fraction",
    "active_duration_ms",
    "crest_factor",
    "periodicity_proxy",
    "pulse_count",
)


def _rms(signal: np.ndarray) -> float:
    return math.sqrt(float(np.mean(signal**2))) if signal.size else 0.0


def extract_features(mixed: np.ndarray, ai_reference: np.ndarray) -> dict[str, float]:
    """Acoustic/temporal features only; no label, text, language, or generator parameter."""
    if mixed.shape != ai_reference.shape or mixed.ndim != 1:
        raise ValueError("aligned mono playback reference is required")
    residual = mixed - ai_reference
    residual_rms = _rms(residual)
    ai_rms = _rms(ai_reference)
    mixture_rms = _rms(mixed)
    zcr = float(np.mean(np.signbit(residual[1:]) != np.signbit(residual[:-1]))) if residual.size > 1 else 0.0

    windowed = residual * np.hanning(residual.size)
    spectrum = np.abs(np.fft.rfft(windowed)) + 1e-12
    frequencies = np.fft.rfftfreq(residual.size, 1 / SAMPLE_RATE)
    spectrum_sum = float(np.sum(spectrum))
    centroid = float(np.sum(frequencies * spectrum) / spectrum_sum)
    bandwidth = math.sqrt(float(np.sum(((frequencies - centroid) ** 2) * spectrum) / spectrum_sum))
    flatness = float(np.exp(np.mean(np.log(spectrum))) / np.mean(spectrum))

    frame = 320
    hop = 160
    frame_rms = np.asarray([
        _rms(residual[start : start + frame])
        for start in range(0, max(1, residual.size - frame + 1), hop)
    ])
    onset_strength = float(np.max(np.maximum(0, np.diff(frame_rms, prepend=frame_rms[0])))) if frame_rms.size else 0.0
    threshold = max(0.002, float(np.median(frame_rms) + 1.5 * np.median(np.abs(frame_rms - np.median(frame_rms))))) if frame_rms.size else 0.002
    active = frame_rms > threshold
    active_fraction = float(np.mean(active)) if active.size else 0.0
    active_duration_ms = float(np.sum(active) * hop * 1000 / SAMPLE_RATE)
    pulse_count = float(np.sum(active[1:] & ~active[:-1])) if active.size > 1 else float(bool(active.size and active[0]))
    peak = float(np.max(np.abs(residual))) if residual.size else 0.0
    crest = peak / max(residual_rms, 1e-12)

    voiced_band = spectrum[(frequencies >= 70) & (frequencies <= 500)]
    periodicity = (
        float(np.max(voiced_band) / max(float(np.sum(voiced_band)), 1e-12))
        if residual_rms >= 1e-9 and voiced_band.size
        else 0.0
    )

    return {
        "residual_rms": residual_rms,
        "mixture_rms": mixture_rms,
        "residual_to_ai_db": 20 * math.log10(max(residual_rms, 1e-12) / max(ai_rms, 1e-12)),
        "zero_crossing_rate": zcr,
        "spectral_centroid_hz": centroid,
        "spectral_bandwidth_hz": bandwidth,
        "spectral_flatness": flatness,
        "onset_strength": onset_strength,
        "active_fraction": active_fraction,
        "active_duration_ms": active_duration_ms,
        "crest_factor": crest,
        "periodicity_proxy": periodicity,
        "pulse_count": pulse_count,
    }


def build_features(dataset_path: Path) -> list[dict]:
    rows = []
    for source in read_jsonl(dataset_path):
        mixed, ai, _ = synthesize_example(source)
        features = extract_features(mixed, ai)
        if tuple(features) != FEATURE_NAMES:
            raise AssertionError("feature order changed")
        rows.append(
            {
                "example_id": source["example_id"],
                "template_group_id": source["template_group_id"],
                "split": source["split"],
                "label": source["label"],
                "target": int(source["label"] == "INTERRUPTION"),
                "locale": source["locale"],
                "event_category": source["event_category"],
                "onset_pct": source["onset_pct"],
                "target_snr_db": source["target_snr_db"],
                "waveform_sha256": source["waveform_sha256"],
                **features,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = build_features(args.dataset)
    write_csv(args.output, rows)
    metadata = {
        "dataset_sha256": sha256_file(args.dataset),
        "features_csv_sha256": sha256_file(args.output),
        "examples": len(rows),
        "feature_names": list(FEATURE_NAMES),
        "feature_source": "mixed waveform minus known AI playback reference",
        "forbidden_model_inputs": ["label", "semantic_content", "locale", "event_category", "onset_pct", "target_snr_db", "template_group_id", "waveform_seed"],
        "text_or_asr_features_used": False,
        "deterministic": True,
    }
    write_json(args.output.with_suffix(".metadata.json"), metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
