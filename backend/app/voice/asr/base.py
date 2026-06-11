from __future__ import annotations

from abc import ABC, abstractmethod


class ASRProvider(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def accept_audio_chunk(self, chunk: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_partial_transcript(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_final_transcript(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError
