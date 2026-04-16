from __future__ import annotations

import json

from agent_py.engine import CareAgent
from agent_py.memory import MemoryStore
from agent_py.rag import KeywordRAG


def test_memory_store_uses_relational_tables():
    store = MemoryStore(":memory:")
    agent = CareAgent(memory=store, rag=KeywordRAG())

    agent.chat("schema", "明早7点提醒奶奶吃降压药")
    agent.chat("schema", "卧室温度怎么样")

    conn = store._connect()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert "state_json" not in {
        row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    assert {
        "sessions",
        "family_contacts",
        "reminders",
        "device_states",
        "sensors",
        "env_rules",
        "tool_events",
        "conversation_messages",
    } <= tables
    assert conn.execute("SELECT count(*) FROM reminders WHERE session_id = 'schema'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM device_states WHERE session_id = 'schema'").fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM sensors WHERE session_id = 'schema'").fetchone()[0] == 2

    event = conn.execute(
        "SELECT input_json FROM tool_events WHERE session_id = 'schema' AND tool_name = 'create_reminder'"
    ).fetchone()
    assert json.loads(event["input_json"])["medicine"] == "降压药"
