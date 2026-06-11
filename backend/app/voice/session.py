from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


VOICE_STATUSES = {"idle", "listening", "recognizing", "thinking", "speaking", "error"}


@dataclass
class ProcessedUtteranceCache:
    max_ids: int = 50
    ttl_seconds: int = 600
    ids: OrderedDict[str, float] = field(default_factory=OrderedDict)

    def has(self, utterance_id: str) -> bool:
        self.cleanup()
        return utterance_id in self.ids

    def add(self, utterance_id: str) -> None:
        self.cleanup()
        self.ids[utterance_id] = time.monotonic()
        self.ids.move_to_end(utterance_id)
        while len(self.ids) > self.max_ids:
            self.ids.popitem(last=False)

    def cleanup(self) -> None:
        now = time.monotonic()
        expired = [key for key, seen_at in self.ids.items() if now - seen_at > self.ttl_seconds]
        for key in expired:
            self.ids.pop(key, None)


@dataclass
class VoiceSession:
    session_id: str
    status: str = "idle"
    muted: bool = False
    recognizer: Any = None
    current_utterance_id: str | None = None
    tts_enabled: bool = True
    utterance_tts_preferences: OrderedDict[str, bool] = field(default_factory=OrderedDict)
    last_seen: float = field(default_factory=time.monotonic)
    processed_utterances: ProcessedUtteranceCache = field(default_factory=ProcessedUtteranceCache)

    def set_status(self, status: str) -> None:
        if status not in VOICE_STATUSES:
            raise ValueError(f"Invalid voice status: {status}")
        self.status = status
        self.last_seen = time.monotonic()

    def set_utterance_tts_preference(self, utterance_id: str, enabled: bool) -> None:
        if not utterance_id:
            return
        self.utterance_tts_preferences[utterance_id] = enabled
        self.utterance_tts_preferences.move_to_end(utterance_id)
        while len(self.utterance_tts_preferences) > 50:
            self.utterance_tts_preferences.popitem(last=False)

    def get_utterance_tts_preference(self, utterance_id: str) -> bool:
        return bool(self.utterance_tts_preferences.get(utterance_id, False))

    def has_utterance_tts_preference(self, utterance_id: str) -> bool:
        return utterance_id in self.utterance_tts_preferences

    def clear_active_utterance(self, utterance_id: str) -> None:
        if self.current_utterance_id == utterance_id:
            self.current_utterance_id = None


class VoiceSessionController:
    def __init__(self, ttl_seconds: int = 600, max_sessions: int = 512) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, VoiceSession] = OrderedDict()

    def get_session(self, session_id: str) -> VoiceSession:
        self.cleanup()
        session = self._sessions.get(session_id)
        if not session:
            session = VoiceSession(session_id=session_id)
            self._sessions[session_id] = session
        session.last_seen = time.monotonic()
        self._sessions.move_to_end(session_id)
        return session

    def release_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session and session.recognizer:
            session.recognizer.stop()
            session.recognizer = None

    def cleanup(self) -> None:
        now = time.monotonic()
        expired = [session_id for session_id, session in self._sessions.items() if now - session.last_seen > self.ttl_seconds]
        for session_id in expired:
            self.release_session(session_id)
        while len(self._sessions) > self.max_sessions:
            self.release_session(next(iter(self._sessions)))
