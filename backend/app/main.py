import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import agora, tools

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("multilingual-syncup")

app = FastAPI(
    title="Multilingual Voice SyncUp Backend",
    description=(
        "Engineering backend for Track 2: Voice AI at Work: Beyond the Call Center. "
        "Integrates Agora Conversational AI Engine + Murf.ai Falcon 2.1 streaming TTS."
    ),
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(agora.router)
app.include_router(tools.router)

@app.get("/")
async def root():
    return {
        "service": "Multilingual Voice SyncUp",
        "track": "Track 2: Voice AI at Work: Beyond the Call Center",
        "engine": "Agora Conversational AI + Murf Falcon 2.1",
        "status": "OPERATIONAL",
        "endpoints": {
            "config": "/api/config",
            "agent_start": "/api/agent/start",
            "agent_stop": "/api/agent/stop",
            "triage_tool": "/tools/triage",
            "route_tool": "/tools/route",
            "context": "/tools/context"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "default_voice": settings.MURF_DEFAULT_VOICE_ID,
        "llm_model": settings.LLM_MODEL
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True
    )
