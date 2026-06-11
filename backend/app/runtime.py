from __future__ import annotations

from app.agents.orchestrator import OrchestratorAgent
from app.services.text_entry_service import TextEntryService
from app.state.session_store import InMemorySessionStore
from app.voice.runtime import create_voice_runtime


store = InMemorySessionStore()
orchestrator = OrchestratorAgent()
text_entry_service = TextEntryService(store=store, orchestrator=orchestrator)
voice_runtime = create_voice_runtime()
