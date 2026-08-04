from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.common.io import read_csv, read_jsonl
from experiments.common.metadata import ROOT
from experiments.common.stats import percentile
from experiments.latency.run_replay_speech_latency import Recorder, TimedValidator
from experiments.token_cost.baseline import TOKENIZER_ID, build_prompt, count_tokens
from experiments.token_cost.build_dataset import build_conversations


def test_token_dataset_is_shared_input_only_conversations() -> None:
    conversations = build_conversations(seed=42)
    assert len(conversations) == 160
    assert sum(len(row["turns"]) for row in conversations) == 868
    assert {row["locale"] for row in conversations} == {"zh-CN", "yue-Hant-HK", "en-HK", "mixed"}
    assert {row["scenario_type"] for row in conversations} == {"routine", "complex", "safety"}
    forbidden = {"expected_intent", "expected_classification", "expected_transcript", "expectedIntent", "expectedTranscript"}
    assert all(not (forbidden & set(row)) for row in conversations)
    assert all(not (forbidden & set(turn)) for row in conversations for turn in row["turns"])


def test_full_history_grows_and_token_count_is_reproducible() -> None:
    no_history = build_prompt(menu_snapshot="[]", history=[], user_utterance="wait 等等")
    with_history = build_prompt(
        menu_snapshot="[]",
        history=[{"user": "menu", "assistant": "Here is the menu."}],
        user_utterance="wait 等等",
    )
    assert len(with_history) > len(no_history)
    assert count_tokens(with_history) == count_tokens(with_history)
    assert count_tokens("A等🙂") == 3
    assert TOKENIZER_ID == "unicode-codepoint-v1"


def test_expected_labels_never_enter_baseline_prompt() -> None:
    prompt = build_prompt(menu_snapshot="[]", history=[], user_utterance="show the menu")
    for forbidden in ("expected_intent", "expectedClassification", "ground_truth", "P4-EN-"):
        assert forbidden not in prompt


def test_token_runs_use_identical_conversation_turns() -> None:
    results = ROOT / "experiments" / "results" / "token_cost"
    runs = [read_csv(results / f"run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    identities = [[(row["conversation_id"], row["turn_id"], row["user_utterance"]) for row in run] for run in runs]
    assert identities[0] == identities[1] == identities[2]
    assert all(row["current_llm_required"] == "False" for run in runs for row in run)


class _Validator:
    def validate(self, value):
        return {"same": value}


def test_latency_timer_wrapper_does_not_change_output() -> None:
    recorder = Recorder()
    wrapped = TimedValidator(_Validator(), recorder)
    assert wrapped.validate("audio") == _Validator().validate("audio")
    assert recorder.count("audio_validation") == 1
    assert recorder.total("audio_validation") >= 0


def test_latency_warmup_is_excluded_and_counts_repeat() -> None:
    results = ROOT / "experiments" / "results" / "latency"
    for run_id in (1, 2, 3):
        metadata = json.loads((results / f"text_run_{run_id}_metadata.json").read_text(encoding="utf-8"))
        rows = read_csv(results / f"text_run_{run_id}_raw.csv")
        assert metadata["warmup_count"] == 20
        assert metadata["measurement_count"] == len(rows) == 1228
        assert not any("warmup" in row["case_id"] for row in rows)
        replay = read_csv(results / f"replay_run_{run_id}_raw.csv")
        assert sum(row["record_type"] == "audio_pipeline" for row in replay) == 240
        assert sum(row["record_type"] == "replay_tts" for row in replay) == 105


def test_percentile_interpolation() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)


def test_latency_instrumentation_preserves_outputs_across_runs() -> None:
    results = ROOT / "experiments" / "results" / "latency"
    runs = [read_csv(results / f"text_run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    # Full state and confirmation responses contain run-specific database IDs.
    # Compare the stable decision/mutation path instead; wrapper identity is
    # tested separately above.
    fingerprints = [
        [
            (
                row["case_id"],
                row["canonical_intent"],
                row["selected_handler"],
                row["decision_class"],
            )
            for row in run
        ]
        for run in runs
    ]
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]
