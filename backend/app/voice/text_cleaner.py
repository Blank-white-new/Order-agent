from __future__ import annotations

import json
import re
import unicodedata


FILLER_WORDS = {"嗯", "啊", "那个", "就是", "呃", "额"}
FILLER_PATTERN = re.compile(r"^(嗯|啊|那个|就是|呃|额)+$")


def normalize_voice_transcript(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"^(嗯|啊|那个|就是|呃|额)[，,。！？!?；;、\s]*", "", normalized)
    normalized = re.sub(r"[，,。！？!?；;、\s]*(嗯|啊|那个|就是|呃|额)$", "", normalized)
    return normalized.strip()


def is_empty_transcript(text: str | None) -> bool:
    normalized = normalize_voice_transcript(text)
    if not normalized:
        return True
    compact = re.sub(r"[\s，,。！？!?；;、]+", "", normalized)
    return bool(FILLER_PATTERN.fullmatch(compact))


def clean_text_for_tts(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _remove_code_fences(text)
    cleaned = _remove_json_objects(cleaned)
    cleaned = re.sub(r"\b(trace|debug|state|raw_state|finalIntent|selectedAgent)\b[:：]?.*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[*_`>#\[\]\(\)]", "", cleaned)
    cleaned = _remove_emoji(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _remove_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _remove_json_objects(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            json.loads(candidate)
            return ""
        except json.JSONDecodeError:
            pass
    cleaned = []
    index = 0
    while index < len(text):
        if text[index] != "{":
            cleaned.append(text[index])
            index += 1
            continue
        depth = 0
        end = index
        while end < len(text):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        block = text[index:end]
        if any(token in block.lower() for token in ["trace", "debug", "state", "finalintent"]) or _looks_like_json(block):
            index = end
        else:
            cleaned.append(block)
            index = end
    return "".join(cleaned)


def _looks_like_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def _remove_emoji(text: str) -> str:
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("So"))
