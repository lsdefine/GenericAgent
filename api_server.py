"""
GA Switch API Server
Minimal FastAPI server exposing GA backend functionality via REST API
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sys
import os

# Add GA path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentmain import GeneraticAgent
from ga_switch import get_service

app = FastAPI(title="GA Switch API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
agent = GeneraticAgent()
service = get_service()

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
def get_snapshot():
    return service.get_ui_snapshot(agent)

@app.get("/api/routes")
def list_routes():
    snapshot = service.get_ui_snapshot(agent)
    return snapshot.get("routes", [])

@app.post("/api/routes")
def create_route(payload: RoutePayload):
    service.upsert_route(payload.model_dump())
    return {"success": True}

@app.put("/api/routes/{route_id}")
def update_route(route_id: str, payload: RoutePayload):
    data = payload.model_dump()
    data["id"] = route_id
    service.upsert_route(data)
    return {"success": True}

@app.delete("/api/routes/{route_id}")
def delete_route(route_id: str):
    service.delete_route(route_id)
    return {"success": True}

@app.post("/api/routes/{route_id}/activate")
def activate_route(route_id: str):
    agent.set_active_route(route_id)
    return {"success": True}

@app.get("/api/providers")
def list_providers():
    snapshot = service.get_ui_snapshot(agent)
    return snapshot.get("providers", [])

@app.post("/api/providers")
def create_provider(payload: ProviderPayload):
    service.upsert_provider(payload.model_dump())
    return {"success": True}

@app.put("/api/providers/{provider_id}")
def update_provider(provider_id: str, payload: ProviderPayload):
    data = payload.model_dump()
    data["id"] = provider_id
    service.upsert_provider(data)
    return {"success": True}

@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: str):
    service.delete_provider(provider_id)
    return {"success": True}

@app.post("/api/providers/{provider_id}/test")
def test_provider(provider_id: str):
    result = service.run_model_test(provider_id)
    return result

@app.get("/api/diagnostics")
def get_diagnostics():
    snapshot = service.get_ui_snapshot(agent)
    return snapshot.get("events", [])

@app.post("/api/reload")
def reload_config(preserve_history: bool = True):
    agent.reload_llm_config(preserve_history=preserve_history)
    return {"success": True}

@app.post("/api/import-legacy")
def import_legacy(path: Optional[str] = None):
    service.import_legacy_mykey(path)
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
