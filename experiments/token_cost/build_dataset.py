from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from experiments.common.io import write_jsonl
from experiments.common.metadata import ROOT


SOURCE = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
DEFAULT_OUTPUT = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
LOCALES = ("zh-CN", "yue-Hant-HK", "en-HK", "mixed")


ROUTINE_TEMPLATES: tuple[tuple[str, ...], ...] = (
    ("menu", "recommend", "add1", "modifier", "pickup", "show", "confirm"),
    ("price", "add2mod", "remove_one", "delivery", "address", "phone", "show", "confirm"),
    ("alias", "note", "pickup", "show", "confirm"),
    ("add2mod", "change", "remove_one", "pickup", "show", "confirm"),
    ("recommend", "add1", "replace", "modifier", "delivery", "address", "phone", "show", "confirm"),
    ("menu", "price", "add1", "show", "pickup", "confirm"),
    ("recommend", "alias", "modifier", "note", "show", "pickup", "confirm"),
    ("add2mod", "remove_modifier", "change", "show", "delivery", "address", "phone", "confirm"),
    ("menu", "add1", "remove", "new", "add1", "pickup", "show", "confirm"),
    ("price", "recommend", "add2mod", "show", "delivery", "address", "phone", "confirm"),
)

COMPLEX_TEMPLATES: tuple[tuple[str, ...], ...] = (
    ("ambiguous_item", "add1", "ambiguous_quantity", "change", "show"),
    ("question_add", "add1", "correction", "show", "cancel"),
    ("missing_item", "recommend", "alias", "bad_modifier", "show"),
    ("sold_out", "add1", "replace", "note", "show"),
    ("add2mod", "remove_modifier", "remove", "new", "add1", "show"),
    ("unsupported", "menu", "recommend", "add1", "show"),
    ("ambiguous_quantity", "add2mod", "change", "correction", "show"),
    ("bad_modifier", "modifier", "question_add", "add1", "show"),
    ("missing_item", "sold_out", "recommend", "alias", "pickup", "show"),
    ("add1", "replace", "remove_one", "new", "add2mod", "show"),
)

SAFETY_TEMPLATES: tuple[tuple[str, ...], ...] = (
    ("menu", "allergy"),
    ("add1", "cross"),
    ("menu", "human"),
    ("add1", "complaint"),
    ("show", "refund"),
    ("show", "dispute"),
    ("menu", "cross_tenant"),
    ("menu", "attack"),
    ("menu", "secret"),
    ("add1", "guarantee"),
)


def _load_source(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_conversations(source: Path = SOURCE, *, seed: int = 42) -> list[dict]:
    """Build inputs only; expected Phase 4 fields are deliberately discarded."""
    source_rows = _load_source(source)
    lookup: dict[tuple[str, str], list[dict]] = {}
    for row in source_rows:
        lookup.setdefault((row["locale"], row["semantic_category"]), []).append(row)
    for candidates in lookup.values():
        candidates.sort(key=lambda row: (row["expression_variant"], row["scenario_id"]))

    rng = random.Random(seed)
    conversations: list[dict] = []
    for locale_index, locale in enumerate(LOCALES):
        plans: list[tuple[str, tuple[str, ...]]] = []
        plans.extend(("routine", ROUTINE_TEMPLATES[index % len(ROUTINE_TEMPLATES)]) for index in range(20))
        plans.extend(("complex", COMPLEX_TEMPLATES[index]) for index in range(10))
        plans.extend(("safety", SAFETY_TEMPLATES[index]) for index in range(10))
        for local_index, (scenario_type, categories) in enumerate(plans, start=1):
            turns = []
            provenance = []
            for turn_index, category in enumerate(categories, start=1):
                candidates = lookup.get((locale, category))
                if not candidates:
                    raise ValueError(f"missing Phase 4 source for {locale}/{category}")
                choice_index = (local_index + turn_index + locale_index + rng.randrange(len(candidates))) % len(candidates)
                source_row = candidates[choice_index]
                turns.append({"turn_id": turn_index, "user": source_row["input"]})
                provenance.append(source_row["scenario_id"])
            conversations.append(
                {
                    "conversation_id": f"TOK-{locale_index + 1:02d}-{local_index:03d}",
                    "scenario_type": scenario_type,
                    "locale": locale,
                    "restaurant_code": "hk-sim-restaurant-a",
                    "branch_code": "central",
                    "source_scenario_ids": provenance,
                    "turns": turns,
                }
            )
    if len(conversations) != 160:
        raise AssertionError(f"expected 160 conversations, got {len(conversations)}")
    return conversations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = build_conversations(args.source, seed=args.seed)
    write_jsonl(args.output, rows)
    print(f"wrote {len(rows)} conversations to {args.output}")


if __name__ == "__main__":
    main()
