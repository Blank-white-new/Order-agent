from __future__ import annotations

from http import HTTPStatus

from app.domain.errors import DomainError


class SpeechError(DomainError):
    """Stable speech-domain failure with a public, non-sensitive message."""


_STATUS_BY_CODE = {
    "SPEECH_SIMULATION_DISABLED": HTTPStatus.NOT_FOUND,
    "SPEECH_PROVIDER_DISABLED": HTTPStatus.SERVICE_UNAVAILABLE,
    "SPEECH_PROVIDER_INVALID": HTTPStatus.UNPROCESSABLE_ENTITY,
    "SPEECH_PROVIDER_NOT_ALLOWED": HTTPStatus.FORBIDDEN,
    "SPEECH_FIXTURE_NOT_FOUND": HTTPStatus.NOT_FOUND,
    "TTS_FIXTURE_NOT_FOUND": HTTPStatus.NOT_FOUND,
    "SPEECH_FIXTURE_HASH_MISMATCH": HTTPStatus.UNPROCESSABLE_ENTITY,
    "SPEECH_TIMEOUT": HTTPStatus.GATEWAY_TIMEOUT,
    "SPEECH_PROVIDER_FAILURE": HTTPStatus.SERVICE_UNAVAILABLE,
    "NO_SPEECH_DETECTED": HTTPStatus.UNPROCESSABLE_ENTITY,
    "TRANSCRIPT_EMPTY": HTTPStatus.UNPROCESSABLE_ENTITY,
    "SPEECH_LANGUAGE_UNSUPPORTED": HTTPStatus.UNPROCESSABLE_ENTITY,
}


def speech_error(code: str, message: str | None = None) -> SpeechError:
    safe_message = message or "The synthetic speech request could not be processed safely."
    return SpeechError(code, safe_message, int(_STATUS_BY_CODE.get(code, HTTPStatus.UNPROCESSABLE_ENTITY)))
