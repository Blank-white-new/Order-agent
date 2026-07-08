from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import run_dialogue_eval_v3 as eval_v3


DATASET = PROJECT_ROOT / "evaluation" / "dialogues_v3.jsonl"


def test_v3_dataset_loads_and_ids_are_unique():
    samples = eval_v3.load_dataset(DATASET)

    ids = [sample["id"] for sample in samples]
    assert 40 <= len(samples) <= 60
    assert len(ids) == len(set(ids))


def test_v3_dataset_categories_are_valid():
    samples = eval_v3.load_dataset(DATASET)

    assert {sample["category"] for sample in samples} <= eval_v3.VALID_CATEGORIES
    assert {sample["category"] for sample in samples} == eval_v3.VALID_CATEGORIES


def test_v3_dataset_expected_result_types_are_valid():
    samples = eval_v3.load_dataset(DATASET)

    result_types = {sample["expected_result_type"] for sample in samples}
    assert result_types <= eval_v3.VALID_EXPECTED_RESULT_TYPES
    assert result_types == eval_v3.VALID_EXPECTED_RESULT_TYPES


def test_runner_forces_offline_even_if_parent_environment_is_live(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_SPECULATIVE_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fake-parent-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-legacy-key")

    offline_path = eval_v3.force_offline_environment()
    service = eval_v3.create_text_entry_service()

    assert os.environ["LLM_FALLBACK_ENABLED"] == "false"
    assert os.environ["LLM_FALLBACK_SPECULATIVE_ENABLED"] == "false"
    assert "LLM_FALLBACK_API_KEY" not in os.environ
    assert "DEEPSEEK_API_KEY" not in os.environ
    assert os.environ["BACKEND_ENV_FILE"] != str(PROJECT_ROOT / ".env")
    assert not offline_path.exists()
    assert service.orchestrator.llm_client.can_call() is False


def test_runner_can_execute_max_dialogues_one(capsys):
    exit_code = eval_v3.main(["--dataset", str(DATASET), "--max-dialogues", "1"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "总数: 1" in output


def test_failed_sample_does_not_stop_following_samples():
    samples = eval_v3.load_dataset(DATASET)[:2]
    calls = 0

    def service_factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic sample failure")
        return eval_v3.create_text_entry_service()

    results = asyncio.run(eval_v3.evaluate_samples(samples, service_factory=service_factory))

    assert len(results) == 2
    assert results[0]["passed"] is False
    assert "synthetic sample failure" in results[0]["failure_reasons"][0]
    assert results[1]["id"] == samples[1]["id"]
    assert results[1]["turns"]


def test_runner_does_not_read_project_env_or_real_api_key(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fake-must-not-be-read")
    eval_v3.force_offline_environment()
    eval_v3.llm_module._env_file_values.cache_clear()

    def fail_if_dotenv_is_read(*_args, **_kwargs):
        raise AssertionError("dotenv must not be read by the offline evaluator")

    monkeypatch.setattr(eval_v3.llm_module, "dotenv_values", fail_if_dotenv_is_read)
    service = eval_v3.create_text_entry_service()

    assert service.orchestrator.llm_client.is_configured() is False
    assert "LLM_FALLBACK_API_KEY" not in os.environ


def test_runner_never_outputs_api_key(monkeypatch, capsys):
    sentinel = "fake-sensitive-value-for-output-test"
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", sentinel)

    exit_code = eval_v3.main(["--dataset", str(DATASET), "--max-dialogues", "1"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert sentinel not in captured.out
    assert sentinel not in captured.err
