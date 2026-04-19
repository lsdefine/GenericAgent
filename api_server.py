"""
GA Switch API Server
Minimal FastAPI server exposing GA backend functionality via REST API
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager
import sys
import os

# Add GA path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentmain import GeneraticAgent
from ga_switch import get_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize on startup
    app.state.agent = GeneraticAgent()
    app.state.service = get_service()
    yield
    # Cleanup on shutdown (if needed)

app = FastAPI(title="GA Switch API", version="1.0.0", lifespan=lifespan)

# CORS - restrict to local frontend only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
        "tauri://localhost",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Models
class RoutePayload(BaseModel):
    id: Optional[str] = None
    name: str
    kind: str
    provider_id: Optional[str] = None
    member_provider_ids: list[str] = []
    is_default: bool = False
    is_enabled: bool = True
    config: dict = {"max_retries": 3, "base_delay": 1.5, "spring_back": 300}

class ProviderPayload(BaseModel):
    id: Optional[str] = None
    name: str
    backend_kind: str
    apikey: str
    apibase: str
    model: str
    api_mode: str = "chat_completions"
    temperature: float = 1.0
    max_tokens: int = 8192
    timeout: int = 5
    read_timeout: int = 30
    proxy: Optional[str] = None
    extra: dict = {}

# Endpoints
@app.get("/api/health")
def health():
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/api/snapshot")
def get_snapshot(request: Request):
    return request.app.state.service.get_ui_snapshot(request.app.state.agent)

@app.get("/api/routes")
def list_routes(request: Request):
    snapshot = request.app.state.service.get_ui_snapshot(request.app.state.agent)
    return snapshot.get("routes", [])

@app.post("/api/routes")
def create_route(payload: RoutePayload, request: Request):
    request.app.state.service.upsert_route(payload.model_dump())
    return {"success": True}

@app.put("/api/routes/{route_id}")
def update_route(route_id: str, payload: RoutePayload, request: Request):
    data = payload.model_dump()
    data["id"] = route_id
    request.app.state.service.upsert_route(data)
    return {"success": True}

@app.delete("/api/routes/{route_id}")
def delete_route(route_id: str, request: Request):
    request.app.state.service.delete_route(route_id)
    return {"success": True}

@app.post("/api/routes/{route_id}/activate")
def activate_route(route_id: str, request: Request):
    request.app.state.agent.set_active_route(route_id)
    return {"success": True}

@app.get("/api/providers")
def list_providers(request: Request):
    snapshot = request.app.state.service.get_ui_snapshot(request.app.state.agent)
    return snapshot.get("providers", [])

@app.post("/api/providers")
def create_provider(payload: ProviderPayload, request: Request):
    request.app.state.service.upsert_provider(payload.model_dump())
    return {"success": True}

@app.put("/api/providers/{provider_id}")
def update_provider(provider_id: str, payload: ProviderPayload, request: Request):
    data = payload.model_dump()
    data["id"] = provider_id
    request.app.state.service.upsert_provider(data)
    return {"success": True}

@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: str, request: Request):
    request.app.state.service.delete_provider(provider_id)
    return {"success": True}

@app.post("/api/providers/{provider_id}/test")
def test_provider(provider_id: str, request: Request):
    result = request.app.state.service.run_model_test(provider_id)
    return result

@app.get("/api/diagnostics")
def get_diagnostics(request: Request):
    snapshot = request.app.state.service.get_ui_snapshot(request.app.state.agent)
    return snapshot.get("events", [])

@app.post("/api/reload")
def reload_config(preserve_history: bool = True, request: Request = None):
    request.app.state.agent.reload_llm_config(preserve_history=preserve_history)
    return {"success": True}

@app.post("/api/import-legacy")
def import_legacy(path: Optional[str] = None, request: Request = None):
    request.app.state.service.import_legacy_mykey(path)
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
