from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import CareAgent


class ChatRequest(BaseModel):
    session_id: str = Field(default="demo")
    user_text: str
    mode: str = Field(default="health_assistant")


class ConfirmRequest(BaseModel):
    session_id: str = Field(default="demo")
    action_id: str
    approved: bool
    mode: str = Field(default="health_assistant")


class ResetRequest(BaseModel):
    session_id: str = Field(default="demo")


def create_app(engine: CareAgent | None = None) -> FastAPI:
    app = FastAPI(title="ZTECom Local Elder Care Agent", version="0.1.0")
    app.state.engine = engine or CareAgent()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return app.state.engine.health()

    @app.post("/api/chat")
    def chat(req: ChatRequest) -> dict[str, Any]:
        return app.state.engine.chat(req.session_id, req.user_text, mode=req.mode)

    @app.post("/api/confirm")
    def confirm(req: ConfirmRequest) -> dict[str, Any]:
        return app.state.engine.confirm(req.session_id, req.action_id, req.approved, mode=req.mode)

    @app.get("/api/state/{session_id}")
    def state(session_id: str) -> dict[str, Any]:
        return app.state.engine.state(session_id)

    @app.post("/api/reset")
    def reset(req: ResetRequest) -> dict[str, Any]:
        return app.state.engine.reset(req.session_id)

    return app
