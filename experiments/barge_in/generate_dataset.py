from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from experiments.common.io import write_json, write_jsonl
from experiments.common.metadata import ROOT, sha256_file


DEFAULT_OUTPUT = ROOT / "experiments" / "datasets" / "barge_in_synthetic.jsonl"
SAMPLE_RATE = 16_000
DURATION_SECONDS = 2.4
LOCALES = ("zh-CN", "yue-Hant-HK", "en-HK", "mixed")
ONSETS = (20, 40, 60, 80)
SNR_VALUES = (-10, -5, 0, 5, 10)
AI_CONTENTS = (
    "order-readback", "menu-description", "modifier-readback", "delivery-readback",
    "address-readback", "phone-readback", "safety-notice", "confirmation-readback",
)

POSITIVE_CATEGORIES = (
    "direct_stop", "correction", "cancellation", "quantity_change", "item_change",
    "address_correction", "phone_correction", "imperative_hold", "negation", "restart_request",
)
NEGATIVE_CATEGORIES = (
    "cough_like", "impulse_noise", "background_synthetic_speech", "unrelated_speech", "silence",
    "breathing_like", "cutlery_transient", "music_tone_mixture", "acknowledgement", "low_volume_background_speech",
)

POSITIVE_PHRASES = {
    "zh-CN": ("等等", "等一下", "不要这个", "改一下", "停", "不是这个", "先别下单", "数量改成一份", "地址不对", "电话改一下"),
    "yue-Hant-HK": ("等等先", "等陣", "唔要呢個", "改一改", "停", "唔係呢個", "住先", "數量改做一份", "地址唔啱", "電話改一改"),
    "en-HK": ("wait", "hold on", "not this one", "change that", "stop", "that's not right", "don't place it yet", "make it one", "the address is wrong", "change the phone number"),
    "mixed": ("等等 wait", "hold on 先", "唔要 this one", "change 一下", "stop 停", "not 呢個", "住先 don't place it", "quantity 改一份", "address 唔啱", "phone 改一下"),
}

NEGATIVE_DESCRIPTIONS = {
    "cough_like": "programmatic band-limited cough-like noise",
    "impulse_noise": "programmatic short impulse",
    "background_synthetic_speech": "non-instructional speech-like tone pattern",
    "unrelated_speech": "unrelated speech-like tone pattern",
    "silence": "no overlay event",
    "breathing_like": "low-energy filtered noise",
    "cutlery_transient": "high-frequency metallic transients",
    "music_tone_mixture": "harmonic tone mixture",
    "acknowledgement": "short non-directive acknowledgement-like tone",
    "low_volume_background_speech": "low-volume speech-like tone pattern",
}


def _smooth(signal: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return signal
    width = min(int(width), max(1, signal.size))
    left = width // 2
    right = width - 1 - left
    padded = np.pad(signal, (left, right), mode="edge")
    cumulative = np.concatenate(([0.0], np.cumsum(padded, dtype=np.float64)))
    return (cumulative[width:] - cumulative[:-width]) / width


def _speech_like(t: np.ndarray, *, base_hz: float, syllables_hz: float, phase: float) -> np.ndarray:
    carrier = (
        np.sin(2 * np.pi * base_hz * t + phase)
        + 0.43 * np.sin(2 * np.pi * base_hz * 2.03 * t + phase / 2)
        + 0.21 * np.sin(2 * np.pi * base_hz * 3.11 * t)
    )
    pulse = (np.sin(2 * np.pi * syllables_hz * t + phase) > -0.18).astype(float)
    envelope = 0.16 + 0.84 * _smooth(pulse, max(3, int(SAMPLE_RATE * 0.018)))
    return carrier * envelope


def synthesize_example(row: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return mixed signal, known AI playback reference, and overlay event.

    The waveform is reconstructed entirely from documented manifest parameters.
    It is a programmatic signal, not a recording and not intelligible TTS.
    """
    rng = np.random.default_rng(int(row["waveform_seed"]))
    count = int(SAMPLE_RATE * DURATION_SECONDS)
    t = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    ai_profile = int(row["ai_profile"])
    ai = 0.065 * _speech_like(
        t,
        base_hz=145.0 + 17.0 * (ai_profile % 6),
        syllables_hz=2.7 + 0.35 * (ai_profile % 5),
        phase=0.31 * ai_profile,
    )
    ai *= _smooth(((t > 0.03) & (t < 2.30)).astype(float), 321)

    event = np.zeros_like(ai)
    start = int(float(row["onset_fraction"]) * count)
    length = max(1, min(count - start, int(float(row["event_duration_ms"]) * SAMPLE_RATE / 1000)))
    local_t = np.arange(length, dtype=np.float64) / SAMPLE_RATE
    category = row["event_category"]
    template_hash = int(hashlib.sha256(row["template_group_id"].encode("utf-8")).hexdigest()[:8], 16)
    base_hz = 170.0 + float(template_hash % 170)

    if row["label"] == "INTERRUPTION" or category in {
        "background_synthetic_speech", "unrelated_speech", "low_volume_background_speech", "acknowledgement"
    }:
        event_segment = _speech_like(
            local_t,
            base_hz=base_hz,
            syllables_hz=2.4 + (template_hash % 25) / 10,
            phase=(template_hash % 628) / 100,
        )
        if category == "acknowledgement":
            event_segment *= np.exp(-4.0 * local_t / max(local_t[-1], 0.01))
    elif category == "cough_like":
        noise = rng.normal(0, 1, length)
        event_segment = _smooth(noise, 17) - _smooth(noise, 181)
        event_segment *= np.exp(-5 * local_t / max(local_t[-1], 0.01))
    elif category == "impulse_noise":
        event_segment = np.zeros(length)
        for position in (0.18, 0.52):
            center = min(length - 1, int(position * length))
            width = max(2, int(0.006 * SAMPLE_RATE))
            indexes = np.arange(length)
            event_segment += np.exp(-0.5 * ((indexes - center) / width) ** 2) * rng.choice((-1.0, 1.0))
    elif category == "breathing_like":
        event_segment = _smooth(rng.normal(0, 1, length), 241)
        event_segment *= 0.4 + 0.6 * np.sin(np.pi * local_t / max(local_t[-1], 0.01)) ** 2
    elif category == "cutlery_transient":
        event_segment = np.zeros(length)
        indexes = np.arange(length)
        for position in (0.13, 0.41, 0.77):
            center = int(position * length)
            decay = np.exp(-np.maximum(0, indexes - center) / (0.018 * SAMPLE_RATE))
            decay[indexes < center] = 0
            event_segment += decay * np.sin(2 * np.pi * (2100 + 500 * position) * local_t)
    elif category == "music_tone_mixture":
        event_segment = sum(np.sin(2 * np.pi * frequency * local_t) for frequency in (220.0, 277.18, 329.63)) / 3
        event_segment *= _smooth(np.ones(length), 401)
    elif category == "silence":
        event_segment = np.zeros(length)
    else:
        raise ValueError(f"unsupported synthetic category {category}")

    segment_rms = math.sqrt(float(np.mean(event_segment**2))) if length else 0.0
    ai_segment_rms = math.sqrt(float(np.mean(ai[start : start + length] ** 2))) if length else 0.0
    if segment_rms > 1e-12:
        target_snr = float(row["target_snr_db"])
        target_event_rms = ai_segment_rms * (10 ** (target_snr / 20))
        event_segment = event_segment * target_event_rms / segment_rms
    event[start : start + length] = event_segment
    mixed = ai + event
    return mixed.astype(np.float64), ai.astype(np.float64), event.astype(np.float64)


def _pcm_sha256(signal: np.ndarray) -> str:
    pcm = np.clip(signal, -0.999, 0.999)
    return hashlib.sha256((pcm * 32767).astype("<i2").tobytes()).hexdigest()


def build_dataset(*, seed: int = 42) -> list[dict]:
    rows: list[dict] = []
    example_index = 0
    contexts = (
        "menu-readback", "item-readback", "quantity-readback", "modifier-readback", "pickup-readback",
        "delivery-readback", "address-readback", "phone-readback", "safety-notice", "confirmation-readback",
    )
    for label_index, label in enumerate(("INTERRUPTION", "NON_INTERRUPTION")):
        categories = POSITIVE_CATEGORIES if label == "INTERRUPTION" else NEGATIVE_CATEGORIES
        for locale_index, locale in enumerate(LOCALES):
            for category_index, category in enumerate(categories):
                for template_index in range(10):
                    template_group_id = (
                        f"BG-{label_index + 1}-{locale_index + 1}-{category_index + 1:02d}-{template_index + 1:02d}"
                    )
                    if label == "INTERRUPTION":
                        phrase = POSITIVE_PHRASES[locale][category_index]
                        semantic_content = f"{phrase} [{contexts[template_index]}]"
                    else:
                        semantic_content = f"{NEGATIVE_DESCRIPTIONS[category]} [{contexts[template_index]}]"
                    # Within every class × locale × category cell, seven groups
                    # train and the remaining three rotate 1/2 or 2/1 between
                    # validation and test. This preserves category balance while
                    # keeping all variants of a semantic template in one split.
                    if template_index < 7:
                        split = "train"
                    elif (locale_index + category_index + label_index) % 2 == 0:
                        split = "validation" if template_index in {7, 8} else "test"
                    else:
                        split = "validation" if template_index == 7 else "test"
                    for variant in range(2):
                        group_index = category_index * 10 + template_index
                        example_index += 1
                        onset_pct = ONSETS[(variant + group_index + locale_index) % len(ONSETS)]
                        snr = SNR_VALUES[(variant * 2 + group_index + label_index) % len(SNR_VALUES)]
                        if category == "low_volume_background_speech":
                            snr = min(snr, -5)
                        if category == "silence":
                            snr = -120
                        duration_base = 260 + 75 * ((variant + group_index) % 9)
                        if category in {"impulse_noise", "cutlery_transient"}:
                            duration_base = 120 + 30 * (variant % 5)
                        if category == "acknowledgement":
                            duration_base = 180 + 45 * (variant % 5)
                        waveform_seed = seed * 100_000 + example_index
                        row = {
                            "example_id": f"BGX-{example_index:04d}",
                            "template_group_id": template_group_id,
                            "split": split,
                            "label": label,
                            "locale": locale,
                            "event_category": category,
                            "semantic_content": semantic_content,
                            "synthetic": True,
                            "generation": "programmatic-harmonic-and-noise-overlap",
                            "license": "CC0-synthetic-project-generated",
                            "sample_rate_hz": SAMPLE_RATE,
                            "duration_ms": int(DURATION_SECONDS * 1000),
                            "onset_pct": onset_pct,
                            "onset_fraction": onset_pct / 100,
                            "target_snr_db": snr,
                            "event_duration_ms": duration_base,
                            "ai_speaking_content": AI_CONTENTS[(variant + group_index) % len(AI_CONTENTS)],
                            "ai_profile": (variant + group_index + locale_index) % len(AI_CONTENTS),
                            "waveform_seed": waveform_seed,
                            "dataset_seed": seed,
                        }
                        mixed, _, _ = synthesize_example(row)
                        row["waveform_sha256"] = _pcm_sha256(mixed)
                        rows.append(row)
    if len(rows) != 1600:
        raise AssertionError(f"expected 1600 rows, got {len(rows)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = build_dataset(seed=args.seed)
    write_jsonl(args.output, rows)
    distribution: dict[str, dict[str, int]] = {}
    for key in ("split", "label", "locale", "event_category"):
        counts: dict[str, int] = {}
        for row in rows:
            counts[row[key]] = counts.get(row[key], 0) + 1
        distribution[key] = counts
    metadata = {
        "dataset": str(args.output.relative_to(ROOT)),
        "dataset_sha256": sha256_file(args.output),
        "examples": len(rows),
        "random_seed": args.seed,
        "synthetic": True,
        "contains_recorded_voice": False,
        "contains_real_customer_data": False,
        "contains_intelligible_tts": False,
        "waveform_storage": "manifest parameters plus PCM SHA-256; regenerate on demand",
        "group_split": "template_group_id; within each class-locale-category cell 7/1.5/1.5 groups on average, with validation/test rotation",
        "distribution": distribution,
    }
    write_json(args.output.with_suffix(".metadata.json"), metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
