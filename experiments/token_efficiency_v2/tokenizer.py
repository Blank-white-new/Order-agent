from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import tiktoken


MODEL_ID = "gpt-4o-mini-2024-07-18"
ENCODING_NAME = "o200k_base"
TIKTOKEN_VERSION = "0.13.0"

# This is an explicit, shared accounting assumption rather than a claim about
# the provider's private billing implementation. Message contents are encoded
# with o200k_base, then the same fixed framing estimate is applied to A and B.
TOKENS_PER_MESSAGE = 3
REPLY_PRIMER_TOKENS = 3
ACCOUNTING_ID = "tiktoken-o200k-content-plus-3-per-message-plus-3-primer-v1"

FINGERPRINT_TEXTS = (
    "再加一份可乐",
    "等等，唔係呢個 / hold on, change it",
    "severe peanut allergy and cross-contamination",
    "AUTO_DRAFT > confirmation is required",
)


@dataclass(frozen=True)
class TokenCount:
    total: int
    content: int
    framing: int
    message_count: int


@lru_cache(maxsize=1)
def encoding():
    installed = importlib.metadata.version("tiktoken")
    if installed != TIKTOKEN_VERSION:
        raise RuntimeError(
            f"token benchmark requires tiktoken=={TIKTOKEN_VERSION}, found {installed}"
        )
    selected = tiktoken.encoding_for_model(MODEL_ID)
    if selected.name != ENCODING_NAME:
        raise RuntimeError(
            f"{MODEL_ID} resolved to {selected.name}, expected {ENCODING_NAME}"
        )
    return selected


def count_text(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("token input must be text")
    return len(encoding().encode(text, disallowed_special=()))


def count_messages(messages: Iterable[dict[str, str]]) -> TokenCount:
    materialized = list(messages)
    content = 0
    for message in materialized:
        role = message.get("role")
        body = message.get("content")
        if not isinstance(role, str) or not isinstance(body, str):
            raise TypeError("each message requires string role and content")
        content += count_text(role) + count_text(body)
    framing = TOKENS_PER_MESSAGE * len(materialized) + REPLY_PRIMER_TOKENS
    return TokenCount(
        total=content + framing,
        content=content,
        framing=framing,
        message_count=len(materialized),
    )


def prompt_sha256(messages: Iterable[dict[str, str]]) -> str:
    payload = json.dumps(
        list(messages), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tokenizer_fingerprint() -> str:
    token_ids: list[int] = []
    for text in FINGERPRINT_TEXTS:
        token_ids.extend(encoding().encode(text, disallowed_special=()))
        token_ids.append(-1)
    payload = json.dumps(token_ids, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def metadata() -> dict:
    selected = encoding()
    return {
        "target_model": MODEL_ID,
        "library": "tiktoken",
        "library_version": importlib.metadata.version("tiktoken"),
        "model_mapping_api": "tiktoken.encoding_for_model",
        "encoding": selected.name,
        "encoding_n_vocab": selected.n_vocab,
        "encoding_fingerprint": tokenizer_fingerprint(),
        "accounting_id": ACCOUNTING_ID,
        "tokens_per_message_assumption": TOKENS_PER_MESSAGE,
        "reply_primer_tokens_assumption": REPLY_PRIMER_TOKENS,
        "actual_billing_count": False,
        "scope": "model-specific estimated input tokens; no API usage response",
        "official_tokenizer_reference": "https://platform.openai.com/tokenizer/",
    }
