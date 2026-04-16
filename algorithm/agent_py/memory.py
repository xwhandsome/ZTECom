from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import DEFAULT_DB_PATH, ensure_data_dirs
from .models import SessionState, now_iso


def build_default_state(session_id: str) -> SessionState:
    return SessionState(
        session_id=session_id,
        profile={
            "elder_name": "奶奶",
            "family_contacts": {
                "儿子": {"name": "王先生", "phone": "SIMULATED-SON"},
                "女儿": {"name": "李女士", "phone": "SIMULATED-DAUGHTER"},
                "家属": {"name": "主要联系人", "phone": "SIMULATED-FAMILY"},
            },
        },
        device_state={
            "卧室:空调": {"room": "卧室", "device": "空调", "status": "off", "target_temp": None},
            "卧室:灯": {"room": "卧室", "device": "灯", "status": "off"},
            "客厅:空调": {"room": "客厅", "device": "空调", "status": "off", "target_temp": None},
            "客厅:灯": {"room": "客厅", "device": "灯", "status": "on"},
        },
        sensors={
            "卧室": {"temperature": 19, "humidity": 46, "motion": "正常"},
            "客厅": {"temperature": 23, "humidity": 42, "motion": "正常"},
        },
    )


class MemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._memory_conn: sqlite3.Connection | None = None
        if str(db_path) == ":memory:":
            self.db_path: Path | None = None
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.execute("PRAGMA foreign_keys = ON")
        else:
            ensure_data_dirs()
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            legacy_states = self._read_legacy_states(conn)
            if legacy_states:
                conn.execute("DROP TABLE IF EXISTS sessions")

            self._create_schema(conn)
            for state in legacy_states:
                self._save_state(conn, state)
            conn.commit()

    def _read_legacy_states(self, conn: sqlite3.Connection) -> list[SessionState]:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
        ).fetchone()
        if row is None:
            return []
        columns = [item["name"] for item in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "state_json" not in columns:
            return []

        states: list[SessionState] = []
        rows = conn.execute("SELECT state_json FROM sessions").fetchall()
        for item in rows:
            try:
                states.append(SessionState.from_dict(json.loads(item["state_json"])))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return states

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                elder_name TEXT NOT NULL,
                pending_action_json TEXT,
                last_intent TEXT,
                last_reminder_id TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS family_contacts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                person TEXT NOT NULL,
                medicine TEXT NOT NULL,
                remind_time TEXT NOT NULL,
                time_text TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS device_states (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                room TEXT NOT NULL,
                device TEXT NOT NULL,
                status TEXT NOT NULL,
                target_temp INTEGER,
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, room, device),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sensors (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                room TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                motion TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, room),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS env_rules (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                room TEXT NOT NULL,
                comparator TEXT NOT NULL,
                threshold REAL NOT NULL,
                time_after TEXT,
                device TEXT NOT NULL,
                action TEXT NOT NULL,
                target_temp INTEGER,
                enabled INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tool_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                success INTEGER NOT NULL,
                ts TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                ts TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )

    def load(self, session_id: str) -> SessionState:
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT session_id, elder_name, pending_action_json, last_intent, last_reminder_id
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if session is None:
                state = build_default_state(session_id)
                self._save_state(conn, state)
                conn.commit()
                return state
            return self._load_state(conn, session)

    def save(self, state: SessionState) -> None:
        with self._connect() as conn:
            self._save_state(conn, state)
            conn.commit()

    def reset(self, session_id: str = "demo") -> SessionState:
        state = build_default_state(session_id)
        self.save(state)
        return state

    def reset_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def _load_state(self, conn: sqlite3.Connection, session: sqlite3.Row) -> SessionState:
        session_id = session["session_id"]
        contacts = {
            row["relation"]: {"name": row["name"], "phone": row["phone"]}
            for row in conn.execute(
                """
                SELECT relation, name, phone
                FROM family_contacts
                WHERE session_id = ?
                ORDER BY relation
                """,
                (session_id,),
            ).fetchall()
        }
        reminders = [
            {
                "id": row["id"],
                "person": row["person"],
                "medicine": row["medicine"],
                "time": row["remind_time"],
                "time_text": row["time_text"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in conn.execute(
                """
                SELECT id, person, medicine, remind_time, time_text, enabled, created_at, updated_at
                FROM reminders
                WHERE session_id = ?
                ORDER BY remind_time, id
                """,
                (session_id,),
            ).fetchall()
        ]
        device_state = {
            f"{row['room']}:{row['device']}": {
                "room": row["room"],
                "device": row["device"],
                "status": row["status"],
                "target_temp": row["target_temp"],
            }
            for row in conn.execute(
                """
                SELECT room, device, status, target_temp
                FROM device_states
                WHERE session_id = ?
                ORDER BY room, device
                """,
                (session_id,),
            ).fetchall()
        }
        sensors = {
            row["room"]: {
                "temperature": self._number(row["temperature"]),
                "humidity": self._number(row["humidity"]),
                "motion": row["motion"],
            }
            for row in conn.execute(
                """
                SELECT room, temperature, humidity, motion
                FROM sensors
                WHERE session_id = ?
                ORDER BY room
                """,
                (session_id,),
            ).fetchall()
        }
        env_rules = [
            {
                "id": row["id"],
                "room": row["room"],
                "comparator": row["comparator"],
                "threshold": self._number(row["threshold"]),
                "time_after": json.loads(row["time_after"]) if row["time_after"] else None,
                "device": row["device"],
                "action": row["action"],
                "target_temp": row["target_temp"],
                "enabled": bool(row["enabled"]),
            }
            for row in conn.execute(
                """
                SELECT id, room, comparator, threshold, time_after, device, action, target_temp, enabled
                FROM env_rules
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        ]
        recent_tool_events = [
            {
                "tool_name": row["tool_name"],
                "input": json.loads(row["input_json"]),
                "output": json.loads(row["output_json"]),
                "success": bool(row["success"]),
                "ts": row["ts"],
            }
            for row in conn.execute(
                """
                SELECT tool_name, input_json, output_json, success, ts
                FROM tool_events
                WHERE session_id = ?
                ORDER BY ts, id
                """,
                (session_id,),
            ).fetchall()
        ]
        conversation = [
            {"role": row["role"], "text": row["text"], "ts": row["ts"]}
            for row in conn.execute(
                """
                SELECT role, text, ts
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY ts, id
                """,
                (session_id,),
            ).fetchall()
        ]
        pending_action = (
            json.loads(session["pending_action_json"])
            if session["pending_action_json"]
            else None
        )

        return SessionState(
            session_id=session_id,
            profile={"elder_name": session["elder_name"], "family_contacts": contacts},
            reminders=reminders,
            device_state=device_state,
            sensors=sensors,
            env_rules=env_rules,
            pending_action=pending_action,
            recent_tool_events=recent_tool_events,
            conversation=conversation,
            last_intent=session["last_intent"],
            last_reminder_id=session["last_reminder_id"],
        )

    def _save_state(self, conn: sqlite3.Connection, state: SessionState) -> None:
        ts = now_iso()
        profile = state.profile or {}
        conn.execute(
            """
            INSERT INTO sessions(session_id, elder_name, pending_action_json, last_intent, last_reminder_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET
                elder_name = excluded.elder_name,
                pending_action_json = excluded.pending_action_json,
                last_intent = excluded.last_intent,
                last_reminder_id = excluded.last_reminder_id,
                updated_at = excluded.updated_at
            """,
            (
                state.session_id,
                profile.get("elder_name", "奶奶"),
                self._json_or_none(state.pending_action),
                state.last_intent,
                state.last_reminder_id,
                ts,
            ),
        )

        self._clear_child_rows(conn, state.session_id)
        self._save_contacts(conn, state, ts)
        self._save_reminders(conn, state, ts)
        self._save_devices(conn, state, ts)
        self._save_sensors(conn, state, ts)
        self._save_env_rules(conn, state)
        self._save_tool_events(conn, state)
        self._save_conversation(conn, state)

    def _clear_child_rows(self, conn: sqlite3.Connection, session_id: str) -> None:
        for table in [
            "family_contacts",
            "reminders",
            "device_states",
            "sensors",
            "env_rules",
            "tool_events",
            "conversation_messages",
        ]:
            conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))

    def _save_contacts(self, conn: sqlite3.Connection, state: SessionState, ts: str) -> None:
        del ts
        contacts = state.profile.get("family_contacts", {})
        for relation, contact in contacts.items():
            conn.execute(
                """
                INSERT INTO family_contacts(id, session_id, relation, name, phone)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"{state.session_id}:contact:{relation}",
                    state.session_id,
                    relation,
                    contact.get("name", relation),
                    contact.get("phone", "SIMULATED"),
                ),
            )

    def _save_reminders(self, conn: sqlite3.Connection, state: SessionState, ts: str) -> None:
        for reminder in state.reminders:
            created_at = reminder.get("created_at") or ts
            updated_at = reminder.get("updated_at") or ts
            reminder["created_at"] = created_at
            reminder["updated_at"] = updated_at
            conn.execute(
                """
                INSERT INTO reminders(id, session_id, person, medicine, remind_time, time_text, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reminder["id"],
                    state.session_id,
                    reminder.get("person", state.profile.get("elder_name", "奶奶")),
                    reminder["medicine"],
                    reminder["time"],
                    reminder.get("time_text") or reminder["time"],
                    1 if reminder.get("enabled", True) else 0,
                    created_at,
                    updated_at,
                ),
            )

    def _save_devices(self, conn: sqlite3.Connection, state: SessionState, ts: str) -> None:
        for key, device in state.device_state.items():
            room = device.get("room")
            name = device.get("device")
            conn.execute(
                """
                INSERT INTO device_states(id, session_id, room, device, status, target_temp, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{state.session_id}:device:{key}",
                    state.session_id,
                    room,
                    name,
                    device.get("status", "off"),
                    device.get("target_temp"),
                    ts,
                ),
            )

    def _save_sensors(self, conn: sqlite3.Connection, state: SessionState, ts: str) -> None:
        for room, sensor in state.sensors.items():
            conn.execute(
                """
                INSERT INTO sensors(id, session_id, room, temperature, humidity, motion, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{state.session_id}:sensor:{room}",
                    state.session_id,
                    room,
                    sensor.get("temperature"),
                    sensor.get("humidity"),
                    sensor.get("motion"),
                    ts,
                ),
            )

    def _save_env_rules(self, conn: sqlite3.Connection, state: SessionState) -> None:
        for rule in state.env_rules:
            conn.execute(
                """
                INSERT INTO env_rules(id, session_id, room, comparator, threshold, time_after, device, action, target_temp, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["id"],
                    state.session_id,
                    rule["room"],
                    rule["comparator"],
                    rule["threshold"],
                    self._json_or_none(rule.get("time_after")),
                    rule["device"],
                    rule["action"],
                    rule.get("target_temp"),
                    1 if rule.get("enabled", True) else 0,
                ),
            )

    def _save_tool_events(self, conn: sqlite3.Connection, state: SessionState) -> None:
        for index, event in enumerate(state.recent_tool_events, start=1):
            conn.execute(
                """
                INSERT INTO tool_events(id, session_id, tool_name, input_json, output_json, success, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("id") or f"{state.session_id}:event:{index:04d}",
                    state.session_id,
                    event["tool_name"],
                    json.dumps(event.get("input", {}), ensure_ascii=False),
                    json.dumps(event.get("output", {}), ensure_ascii=False),
                    1 if event.get("success") else 0,
                    event.get("ts") or now_iso(),
                ),
            )

    def _save_conversation(self, conn: sqlite3.Connection, state: SessionState) -> None:
        for index, message in enumerate(state.conversation, start=1):
            conn.execute(
                """
                INSERT INTO conversation_messages(id, session_id, role, text, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message.get("id") or f"{state.session_id}:message:{index:04d}",
                    state.session_id,
                    message.get("role", "assistant"),
                    message.get("text", ""),
                    message.get("ts") or now_iso(),
                ),
            )

    def _json_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def _number(self, value: Any) -> int | float | None:
        if value is None:
            return None
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


def trim_event_history(events: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    return events[-limit:]
