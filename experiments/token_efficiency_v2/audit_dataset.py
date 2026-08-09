from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, sha256_file


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
PHASE4_SOURCE = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_efficiency_v2"


def _normalized_conversation(conversation: dict) -> str:
    return "\n".join(
        re.sub(r"\s+", " ", turn["user"].strip().casefold())
        for turn in conversation["turns"]
    )


def _template_key(conversation: dict, source_by_id: dict[str, dict]) -> str:
    return ">".join(
        source_by_id[source_id]["semantic_category"]
        for source_id in conversation["source_scenario_ids"]
    )


def template_group_id(template_key: str) -> str:
    return "TPL-" + hashlib.sha256(template_key.encode("utf-8")).hexdigest()[:12]


def audit_dataset(dataset_path: Path = DEFAULT_DATASET) -> tuple[dict, list[dict]]:
    conversations = read_jsonl(dataset_path)
    phase4 = read_jsonl(PHASE4_SOURCE)
    source_by_id = {row["scenario_id"]: row for row in phase4}
    lengths = [len(row["turns"]) for row in conversations]
    exact_payloads = [
        json.dumps(row["turns"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in conversations
    ]
    normalized_payloads = [_normalized_conversation(row) for row in conversations]
    source_ids = [
        source_id
        for conversation in conversations
        for source_id in conversation["source_scenario_ids"]
    ]
    manifest: list[dict] = []
    for conversation in conversations:
        key = _template_key(conversation, source_by_id)
        manifest.append(
            {
                "conversation_id": conversation["conversation_id"],
                "scenario_type": conversation["scenario_type"],
                "locale": conversation["locale"],
                "turn_count": len(conversation["turns"]),
                "template_group_id": template_group_id(key),
                "template_key": key,
                "conversation_sha256": hashlib.sha256(
                    _normalized_conversation(conversation).encode("utf-8")
                ).hexdigest(),
            }
        )
    template_counts = Counter(row["template_group_id"] for row in manifest)
    reuse = Counter(source_ids)
    audit = {
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_sha256": sha256_file(dataset_path),
        "conversations": len(conversations),
        "turns": sum(lengths),
        "locale_distribution": dict(sorted(Counter(row["locale"] for row in conversations).items())),
        "scenario_distribution": dict(
            sorted(Counter(row["scenario_type"] for row in conversations).items())
        ),
        "conversation_length": {
            "mean": statistics.fmean(lengths),
            "median": statistics.median(lengths),
            "minimum": min(lengths),
            "maximum": max(lengths),
            "distribution": dict(sorted(Counter(lengths).items())),
        },
        "exact_duplicate_conversations": len(exact_payloads) - len(set(exact_payloads)),
        "normalized_duplicate_conversations": len(normalized_payloads)
        - len(set(normalized_payloads)),
        "semantic_template_groups": len(template_counts),
        "template_group_size_distribution": dict(
            sorted(Counter(template_counts.values()).items())
        ),
        "unique_source_scenarios": len(reuse),
        "source_scenario_references": len(source_ids),
        "maximum_source_scenario_reuse": max(reuse.values()),
        "most_reused_source_scenarios": [
            {"scenario_id": scenario_id, "uses": uses}
            for scenario_id, uses in reuse.most_common(15)
        ],
        "source_text_mismatches": sum(
            turn["user"] != source_by_id[source_id]["input"]
            for conversation in conversations
            for turn, source_id in zip(
                conversation["turns"], conversation["source_scenario_ids"]
            )
        ),
        "balanced_locale": len(set(Counter(row["locale"] for row in conversations).values())) == 1,
        "known_template_dependence": (
            "160 conversations contain 30 semantic template groups; conversation-level "
            "and template-cluster bootstrap intervals must both be reported."
        ),
        "dataset_changed_for_v2": False,
    }
    return audit, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    audit, manifest = audit_dataset(args.dataset)
    write_json(args.results_dir / "dataset_audit.json", audit)
    write_csv(args.results_dir / "conversation_manifest.csv", manifest)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
