from __future__ import annotations

from app.speech.config import SpeechSettings
from app.speech.errors import speech_error
from app.speech.formats import ProviderMode
from app.speech.provider import AsrProvider, TtsProvider


class SpeechProviderRegistry:
    def __init__(
        self,
        settings: SpeechSettings,
        *,
        asr_providers: tuple[AsrProvider, ...] = (),
        tts_providers: tuple[TtsProvider, ...] = (),
    ) -> None:
        self.settings = settings
        self._asr = {provider.name: provider for provider in asr_providers}
        self._tts = {provider.name: provider for provider in tts_providers}

    def get_asr(self, provider_name: str | None = None) -> AsrProvider:
        return self._get(self._asr, provider_name or self.settings.asr_provider)

    def get_tts(self, provider_name: str | None = None) -> TtsProvider:
        return self._get(self._tts, provider_name or self.settings.tts_provider)

    def _get(self, providers: dict, provider_name: str):
        normalized = provider_name.strip().casefold()
        if normalized == "disabled":
            raise speech_error("SPEECH_PROVIDER_DISABLED")
        provider = providers.get(normalized)
        if provider is None:
            raise speech_error("SPEECH_PROVIDER_INVALID")
        capabilities = provider.capabilities()
        if self.settings.app_env == "production" and (
            capabilities.provider_mode == ProviderMode.REPLAY
            or not capabilities.production_allowed
        ):
            raise speech_error("SPEECH_PROVIDER_NOT_ALLOWED")
        if capabilities.provider_mode == ProviderMode.REPLAY and not self.settings.may_use_simulation:
            raise speech_error("SPEECH_SIMULATION_DISABLED")
        return provider

    def list_capabilities(self) -> dict:
        return {
            "simulation": self.settings.may_use_simulation,
            "realSpeechRecognition": False,
            "realSpeechSynthesis": False,
            "asr": [provider.capabilities().serializable() for provider in self._asr.values()],
            "tts": [provider.capabilities().serializable() for provider in self._tts.values()],
        }

    def list_replay_fixtures(self) -> list[dict]:
        provider = self.get_asr()
        if not hasattr(provider, "list_fixtures"):
            raise speech_error("SPEECH_PROVIDER_NOT_ALLOWED")
        return provider.list_fixtures()

    def get_replay_fixture_audio(self, fixture_id: str) -> tuple[bytes, str]:
        provider = self.get_asr()
        if not hasattr(provider, "fixture_payload"):
            raise speech_error("SPEECH_PROVIDER_NOT_ALLOWED")
        return provider.fixture_payload(fixture_id)
