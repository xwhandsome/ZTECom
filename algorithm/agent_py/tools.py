from __future__ import annotations

from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any

from .models import PlanStep, SessionState, ToolEvent, now_iso


def _next_id(prefix: str, items: list[dict[str, Any]]) -> str:
    max_index = 0
    for item in items:
        raw_id = str(item.get("id", ""))
        if raw_id.startswith(f"{prefix}-"):
            suffix = raw_id.removeprefix(f"{prefix}-")
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))
    return f"{prefix}-{max_index + 1:03d}"


def _device_key(room: str | None, device: str | None) -> str:
    return f"{room}:{device}"


def _format_time_text(dt: datetime) -> str:
    today = datetime.now().date()
    if dt.date() == today:
        label = "今天"
    elif dt.date() == today + timedelta(days=1):
        label = "明天"
    elif dt.date() == today + timedelta(days=2):
        label = "后天"
    else:
        label = dt.date().isoformat()
    return f"{label} {dt.hour:02d}:{dt.minute:02d}"


class ToolExecutor:
    def __init__(self, id_provider: Callable[[str, SessionState, list[dict[str, Any]]], str] | None = None) -> None:
        self._id_provider = id_provider

    def execute(self, state: SessionState, step: PlanStep) -> ToolEvent:
        try:
            handler = getattr(self, f"_handle_{step.tool_name}")
        except AttributeError:
            step.status = "failed"
            return ToolEvent(step.tool_name, step.args, {"error": "unknown_tool"}, False)

        try:
            output = handler(state, step.args)
            step.status = "done"
            return ToolEvent(step.tool_name, step.args, output, True)
        except Exception as exc:  # Keep demo API stable for controlled tool failures.
            step.status = "failed"
            return ToolEvent(step.tool_name, step.args, {"error": str(exc)}, False)

    def _next_id(self, prefix: str, state: SessionState, items: list[dict[str, Any]]) -> str:
        if self._id_provider is not None:
            return self._id_provider(prefix, state, items)
        return _next_id(prefix, items)

    def _handle_create_reminder(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        ts = now_iso()
        reminder = {
            "id": self._next_id("rem", state, state.reminders),
            "person": args.get("person") or state.profile.get("elder_name", "奶奶"),
            "medicine": args["medicine"],
            "time": args["time"],
            "time_text": args.get("time_text") or args["time"],
            "enabled": True,
            "created_at": ts,
            "updated_at": ts,
        }
        state.reminders.append(reminder)
        state.last_reminder_id = reminder["id"]
        return {"reminder": reminder}

    def _handle_update_reminder(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        reminder_id = args.get("reminder_id") or state.last_reminder_id
        reminder = next((item for item in state.reminders if item.get("id") == reminder_id), None)
        if reminder is None:
            raise ValueError("reminder_not_found")

        if args.get("medicine"):
            reminder["medicine"] = args["medicine"]

        if args.get("time"):
            new_dt = datetime.fromisoformat(args["time"])
            if not args.get("date_explicit") and reminder.get("time"):
                old_dt = datetime.fromisoformat(reminder["time"])
                new_dt = old_dt.replace(hour=int(args.get("hour", new_dt.hour)), minute=int(args.get("minute", new_dt.minute)))
            reminder["time"] = new_dt.isoformat(timespec="minutes")
            reminder["time_text"] = _format_time_text(new_dt)

        reminder["updated_at"] = now_iso()
        state.last_reminder_id = reminder["id"]
        return {"reminder": reminder}

    def _handle_query_reminder(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        return {"reminders": state.reminders}

    def _handle_query_sensor(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        room = args["room"]
        if room not in state.sensors:
            raise ValueError("sensor_room_not_found")
        return {"room": room, "sensor": state.sensors[room]}

    def _handle_control_device(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        key = _device_key(args.get("room"), args.get("device"))
        if key not in state.device_state:
            raise ValueError("device_not_found")
        device = state.device_state[key]
        action = args.get("action")
        if action == "off":
            device["status"] = "off"
        elif action in {"on", "set"}:
            device["status"] = "on"
        if args.get("target_temp") is not None and device.get("device") == "空调":
            device["target_temp"] = args["target_temp"]
        return {"device": device}

    def _handle_upsert_env_rule(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        rule = {
            "id": self._next_id("rule", state, state.env_rules),
            "room": args["room"],
            "comparator": args["comparator"],
            "threshold": args["threshold"],
            "time_after": args.get("time_after"),
            "device": args["device"],
            "action": args["action"],
            "target_temp": args.get("target_temp"),
            "enabled": True,
        }
        state.env_rules.append(rule)
        return {"rule": rule}

    def _handle_notify_family(self, state: SessionState, args: dict[str, Any]) -> dict[str, Any]:
        contact_key = args.get("contact") or "家属"
        contacts = state.profile.get("family_contacts", {})
        contact = contacts.get(contact_key) or contacts.get("家属") or {"name": contact_key, "phone": "SIMULATED"}
        return {
            "contact": contact_key,
            "contact_name": contact.get("name", contact_key),
            "channel": "simulated_local_notification",
            "message": args["message"],
        }
