from __future__ import annotations

from fastapi.testclient import TestClient

from agent_py.api import create_app
from agent_py.engine import CareAgent
from agent_py.memory import MemoryStore
from agent_py.rag import KeywordRAG


def test_api_chat_reset_state_and_confirm():
    engine = CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG())
    engine.reset("api")
    client = TestClient(create_app(engine))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    created = client.post("/api/chat", json={"session_id": "api", "user_text": "明早7点提醒奶奶吃降压药"})
    assert created.status_code == 200
    assert created.json()["intent"] == "create_reminder"

    short = client.post(
        "/api/chat",
        json={"session_id": "api-short", "user_text": "这个药饭前还是饭后吃", "mode": "tool_short"},
    )
    assert short.status_code == 200
    assert short.json()["mode"] == "tool_short"
    assert short.json()["knowledge_refs"] == []
    assert "请在健康助手中提问" in short.json()["assistant_text"]

    pending = client.post("/api/chat", json={"session_id": "api", "user_text": "通知我儿子我今晚不舒服"}).json()
    assert pending["requires_confirmation"] is True

    confirmed = client.post(
        "/api/confirm",
        json={"session_id": "api", "action_id": pending["pending_action"]["action_id"], "approved": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["tool_events"][0]["tool_name"] == "notify_family"

    state = client.get("/api/state/api")
    assert state.status_code == 200
    assert len(state.json()["reminders"]) == 1
    reminder_id = state.json()["reminders"][0]["id"]

    disabled = client.post(f"/api/reminders/api/{reminder_id}/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "ok"
    assert disabled.json()["state"]["reminders"][0]["enabled"] is False

    deleted = client.delete(f"/api/reminders/api/{reminder_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "ok"
    assert deleted.json()["state"]["reminders"] == []

    rule_created = client.post(
        "/api/chat",
        json={"session_id": "api", "user_text": "如果卧室低于20度，晚上9点后自动开空调到24度"},
    )
    rule_id = rule_created.json()["tool_events"][0]["output"]["rule"]["id"]

    rule_disabled = client.post(f"/api/env-rules/api/{rule_id}/enabled", json={"enabled": False})
    assert rule_disabled.status_code == 200
    assert rule_disabled.json()["status"] == "ok"
    assert rule_disabled.json()["state"]["env_rules"][0]["enabled"] is False

    rule_deleted = client.delete(f"/api/env-rules/api/{rule_id}")
    assert rule_deleted.status_code == 200
    assert rule_deleted.json()["status"] == "ok"
    assert rule_deleted.json()["state"]["env_rules"] == []

    reset = client.post("/api/reset", json={"session_id": "api"})
    assert reset.status_code == 200
    assert reset.json()["state"]["reminders"] == []
