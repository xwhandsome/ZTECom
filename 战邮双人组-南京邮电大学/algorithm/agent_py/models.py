from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class IntentResult:
    intent: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    missing_slots: list[str] = field(default_factory=list)
    source: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    step_id: str
    tool_name: str
    args: dict[str, Any]
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolEvent:
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    success: bool
    ts: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeRef:
    doc_id: str
    title: str
    chunk_id: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionState:
    session_id: str
    profile: dict[str, Any] = field(default_factory=dict)
    reminders: list[dict[str, Any]] = field(default_factory=list)
    device_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    sensors: dict[str, dict[str, Any]] = field(default_factory=dict)
    env_rules: list[dict[str, Any]] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    recent_tool_events: list[dict[str, Any]] = field(default_factory=list)
    conversation: list[dict[str, Any]] = field(default_factory=list)
    last_intent: str | None = None
    last_reminder_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(
            session_id=data["session_id"],
            profile=data.get("profile", {}),
            reminders=data.get("reminders", []),
            device_state=data.get("device_state", {}),
            sensors=data.get("sensors", {}),
            env_rules=data.get("env_rules", []),
            pending_action=data.get("pending_action"),
            recent_tool_events=data.get("recent_tool_events", []),
            conversation=data.get("conversation", []),
            last_intent=data.get("last_intent"),
            last_reminder_id=data.get("last_reminder_id"),
        )
