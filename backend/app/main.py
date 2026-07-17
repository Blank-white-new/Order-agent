from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.menu import router as menu_router
from app.api.voice import router as voice_router
from app.api.safety import router as safety_router
from app.runtime import text_entry_service, voice_runtime
from app.agents.voice_gateway_agent import VoiceGatewayAgent
from app.voice.status import evaluate_voice_status
from app.domain.errors import DomainError


app = FastAPI(title="Multi-Agent Ordering System")
app.state.voice_runtime = voice_runtime
app.state.voice_gateway = VoiceGatewayAgent(text_entry_service=text_entry_service, config=voice_runtime.config, runtime=voice_runtime)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=int(exc.http_status),
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
def log_voice_config_summary() -> None:
    status = evaluate_voice_status(voice_runtime.config)
    print(
        "voice config: "
        f"enabled={status['voiceEnabled']}, "
        f"asr_engine={status['asrEngine']}, "
        f"tts_engine={status['ttsEngine']}, "
        f"tts_playback_target={status['ttsPlaybackTarget']}, "
        f"vosk_model_path_exists={status['modelPathExists']}, "
        f"env_file={status['envFilePath']}, "
        f"env_file_exists={status['envFileExists']}"
    )
    app.state.voice_runtime = voice_runtime
    if not getattr(app.state, "voice_gateway", None) or app.state.voice_gateway.runtime is not voice_runtime:
        app.state.voice_gateway = VoiceGatewayAgent(text_entry_service=text_entry_service, config=voice_runtime.config, runtime=voice_runtime)
    print(f"voice runtime: runtime_id={voice_runtime.runtime_id}")


app.include_router(menu_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(safety_router, prefix="/api")
