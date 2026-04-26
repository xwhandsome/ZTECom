from __future__ import annotations

import time
import uuid
import sys
import re
from typing import Any

from .llm_adapter import LLMAdapter
from .memory import MemoryStore, trim_event_history
from .models import IntentResult, PlanStep, SessionState
from .nlu import (
    RuleNLU,
    extract_action,
    extract_contact,
    extract_device,
    extract_medicine,
    extract_room,
    parse_time_text,
)
from .rag import KeywordRAG
from .tools import ToolExecutor


MISSING_LABELS = {
    "medicine": "药品名称",
    "time": "提醒时间",
    "reminder_id": "要修改的提醒",
    "room": "房间",
    "device": "设备",
    "action": "操作",
    "threshold": "触发温度",
    "comparator": "触发条件",
    "contact": "联系人",
    "message": "通知内容",
    "query": "问题",
}

TOOL_BY_INTENT = {
    "create_reminder": "create_reminder",
    "update_reminder": "update_reminder",
    "query_reminder": "query_reminder",
    "query_sensor": "query_sensor",
    "control_device": "control_device",
    "upsert_env_rule": "upsert_env_rule",
    "notify_family": "notify_family",
}

KNOWN_INTENTS = set(TOOL_BY_INTENT) | {"knowledge_query", "unknown"}
CHAT_MODES = {"health_assistant", "tool_short"}
TOOL_SHORT_REDIRECT = "请在健康助手中提问，我这里只处理提醒、设备、环境和通知。"


class CareAgent:
    def __init__(
        self,
        memory: MemoryStore | None = None,
        rag: KeywordRAG | None = None,
        llm: LLMAdapter | None = None,
    ) -> None:
        self.memory = memory or MemoryStore()
        self.rag = rag or KeywordRAG()
        self.llm = llm or LLMAdapter()
        self.nlu = RuleNLU()
        self.tools = ToolExecutor()

    def chat(self, session_id: str, user_text: str, mode: str = "health_assistant") -> dict[str, Any]:
        started = time.perf_counter()
        mode = self._normalize_mode(mode)
        state = self.memory.load(session_id)
        user_text = user_text.strip().strip("\"“”")

        if state.pending_action and self._is_confirm(user_text):
            return self.confirm(session_id, state.pending_action.get("action_id", ""), True, started, mode=mode)
        if state.pending_action and self._is_reject(user_text):
            return self.confirm(session_id, state.pending_action.get("action_id", ""), False, started, mode=mode)

        if state.pending_action and state.pending_action.get("kind") == "slot_fill":
            result = self._continue_slot_fill(user_text, state)
            llm_used = False
            llm_status = self.llm.status().to_dict()
        else:
            result = self.nlu.analyze(user_text, state)
            result, llm_used, llm_status = self._maybe_apply_llm(user_text, result, state)

        if result.intent == "confirm" or result.intent == "reject":
            return self._response(
                started,
                state,
                "当前没有需要确认的操作。",
                result,
                [],
                [],
                [],
                False,
                llm_used,
                llm_status,
                mode,
            )

        if mode == "tool_short" and result.intent in {"knowledge_query", "unknown"}:
            state.last_intent = result.intent
            self._append_conversation(state, user_text, TOOL_SHORT_REDIRECT)
            self.memory.save(state)
            return self._response(started, state, TOOL_SHORT_REDIRECT, result, [], [], [], False, llm_used, llm_status, mode)

        if result.missing_slots:
            state.pending_action = {
                "kind": "slot_fill",
                "action_id": self._new_action_id(),
                "intent": result.intent,
                "slots": result.slots,
                "missing_slots": result.missing_slots,
            }
            state.last_intent = result.intent
            reply = self._ask_for_missing(result, short=mode == "tool_short")
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(
                started,
                state,
                reply,
                result,
                [],
                [],
                [],
                False,
                llm_used,
                llm_status,
                mode,
            )

        if result.intent == "knowledge_query":
            reply, refs = self._answer_with_rag(user_text, state)
            state.pending_action = None
            state.last_intent = result.intent
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, [], [], refs, False, llm_used, llm_status, mode)

        if result.intent == "unknown":
            reply = "我还没有理解这句话。可以试试说：明早 7 点提醒奶奶吃降压药，或者问卧室温度。"
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, [], [], [], False, llm_used, llm_status, mode)

        plan_steps = self._plan(result)
        if self._requires_confirmation(result, plan_steps):
            action_id = self._new_action_id()
            state.pending_action = {
                "kind": "tool_approval",
                "action_id": action_id,
                "intent": result.intent,
                "slots": result.slots,
                "plan_steps": [step.to_dict() for step in plan_steps],
            }
            reply = self._confirmation_text(result, action_id, short=mode == "tool_short")
            state.last_intent = result.intent
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, plan_steps, [], [], True, llm_used, llm_status, mode)

        events = self._execute_plan(state, plan_steps)
        state.pending_action = None
        state.last_intent = result.intent
        reply = self._reply_for_events(result, events, short=mode == "tool_short")
        self._append_conversation(state, user_text, reply)
        self.memory.save(state)
        return self._response(started, state, reply, result, plan_steps, events, [], False, llm_used, llm_status, mode)

    def confirm(
        self,
        session_id: str,
        action_id: str,
        approved: bool,
        started: float | None = None,
        mode: str = "health_assistant",
    ) -> dict[str, Any]:
        started = started or time.perf_counter()
        mode = self._normalize_mode(mode)
        state = self.memory.load(session_id)
        pending = state.pending_action
        if not pending or pending.get("kind") != "tool_approval":
            result = IntentResult("confirm" if approved else "reject", confidence=0.99)
            return self._response(started, state, "当前没有需要确认的操作。", result, [], [], [], False, False, self.llm.status().to_dict(), mode)

        if action_id and action_id != pending.get("action_id"):
            result = IntentResult("confirm", confidence=0.99)
            return self._response(started, state, "确认编号不匹配，操作未执行。", result, [], [], [], True, False, self.llm.status().to_dict(), mode)

        result = IntentResult(pending["intent"], pending.get("slots", {}), confidence=0.99)
        plan_steps = [PlanStep(**step) for step in pending.get("plan_steps", [])]
        if not approved:
            state.pending_action = None
            reply = "已取消这次操作。"
            self._append_conversation(state, "拒绝确认", reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, plan_steps, [], [], False, False, self.llm.status().to_dict(), mode)

        events = self._execute_plan(state, plan_steps)
        state.pending_action = None
        state.last_intent = result.intent
        reply = self._reply_for_events(result, events, short=mode == "tool_short")
        self._append_conversation(state, "确认执行", reply)
        self.memory.save(state)
        return self._response(started, state, reply, result, plan_steps, events, [], False, False, self.llm.status().to_dict(), mode)

    def reset(self, session_id: str = "demo") -> dict[str, Any]:
        state = self.memory.reset(session_id)
        self.rag.reload()
        return {"session_id": session_id, "state": state.to_dict()}

    def state(self, session_id: str) -> dict[str, Any]:
        return self.memory.load(session_id).to_dict()

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "python_runtime": sys.version,
            "llm": self.llm.status(probe_runtime=True).to_dict(),
            "kb_chunks": len(self.rag.chunks),
        }

    def _maybe_apply_llm(
        self,
        user_text: str,
        result: IntentResult,
        state: SessionState,
    ) -> tuple[IntentResult, bool, dict[str, Any]]:
        should_try = result.intent == "unknown" or (bool(result.missing_slots) and result.confidence < 0.75)
        if not should_try:
            return result, False, self.llm.status().to_dict()

        llm_data, status = self.llm.parse_intent_json(user_text, result.slots)
        if not llm_data:
            return result, False, status.to_dict()

        intent = llm_data.get("intent")
        if intent not in KNOWN_INTENTS:
            return result, False, status.to_dict()
        slots = self._normalize_llm_slots(user_text, intent, result.slots, llm_data.get("slots") or {}, state)
        missing = self.nlu.missing_for_intent(intent, slots)
        candidate = IntentResult(intent, slots, float(llm_data.get("confidence", 0.5)), missing, "llm")
        if result.intent == "unknown" or len(candidate.missing_slots) <= len(result.missing_slots):
            return candidate, True, status.to_dict()
        return result, False, status.to_dict()

    def _normalize_llm_slots(
        self,
        user_text: str,
        intent: str,
        rule_slots: dict[str, Any],
        llm_slots: dict[str, Any],
        state: SessionState,
    ) -> dict[str, Any]:
        slots = self.nlu.extract_generic_slots(user_text, state)
        slots.update({key: value for key, value in rule_slots.items() if value is not None})

        aliases = {
            "medicine": ["medicine", "drug", "medicine_name", "medication", "reminder_type", "task"],
            "person": ["person", "to", "target", "person_name", "elder"],
            "time_text": ["time_text", "time", "remind_time", "schedule_time", "datetime"],
            "room": ["room", "location"],
            "device": ["device", "appliance"],
            "action": ["action", "operation"],
            "contact": ["contact", "relation"],
            "message": ["message", "content", "notify_message"],
            "query": ["query", "question"],
            "target_temp": ["target_temp", "temperature", "temp"],
            "threshold": ["threshold", "trigger_temp"],
            "comparator": ["comparator", "condition"],
        }

        for canonical, names in aliases.items():
            value = next((llm_slots.get(name) for name in names if llm_slots.get(name) is not None), None)
            if value is None:
                continue
            if canonical == "medicine":
                medicine = self._normalize_medicine_value(str(value)) or extract_medicine(user_text)
                if medicine:
                    slots["medicine"] = medicine
            elif canonical == "person":
                person = self._normalize_person_value(str(value))
                if person:
                    slots["person"] = person
            elif canonical == "time_text":
                time_info = parse_time_text(str(value)) or parse_time_text(user_text)
                if time_info:
                    slots.update(time_info)
                elif "time" not in slots:
                    slots["time_text"] = str(value)
            elif canonical == "room":
                room = extract_room(str(value)) or str(value).strip()
                if room:
                    slots["room"] = room
            elif canonical == "device":
                device = extract_device(str(value)) or str(value).strip()
                if device:
                    slots["device"] = device
            elif canonical == "action":
                action = self._normalize_action_value(str(value))
                if action:
                    slots["action"] = action
            elif canonical == "target_temp":
                temp = self._normalize_number(value)
                if temp is not None:
                    slots["target_temp"] = temp
            elif canonical == "threshold":
                threshold = self._normalize_number(value)
                if threshold is not None:
                    slots["threshold"] = threshold
            elif canonical == "comparator":
                comparator = self._normalize_comparator_value(str(value))
                if comparator:
                    slots["comparator"] = comparator
            elif canonical == "contact":
                contact = extract_contact(str(value)) or str(value).strip()
                if contact:
                    slots["contact"] = contact
            elif canonical == "message":
                message = str(value).strip()
                if message:
                    slots["message"] = message
            elif canonical == "query":
                query = str(value).strip()
                if query:
                    slots["query"] = query

        if intent == "create_reminder" and "medicine" not in slots:
            medicine = self._normalize_medicine_value(user_text)
            if medicine:
                slots["medicine"] = medicine
        if "time" not in slots:
            time_info = parse_time_text(user_text)
            if time_info:
                slots.update(time_info)
        if "person" not in slots:
            slots["person"] = state.profile.get("elder_name", "奶奶")
        return slots

    def _normalize_medicine_value(self, value: str) -> str | None:
        value = value.strip(" ，。,.！？!?\"“”")
        medicine = extract_medicine(value) or extract_medicine("吃" + value)
        if medicine:
            return medicine
        for prefix in ["提醒", "安排", "服用", "口服", "吃", "用"]:
            if value.startswith(prefix):
                value = value[len(prefix) :].strip()
        value = value.replace("的事项", "").replace("事项", "").strip(" ，。,.！？!?")
        return value if value and len(value) <= 16 and "药" in value else None

    def _normalize_person_value(self, value: str) -> str | None:
        value = value.strip(" ，。,.！？!?\"“”")
        if value in {"老人", "家里老人"}:
            return "奶奶"
        return value or None

    def _normalize_action_value(self, value: str) -> str | None:
        value = value.strip().lower()
        if value in {"on", "off", "set"}:
            return value
        return extract_action(value)

    def _normalize_comparator_value(self, value: str) -> str | None:
        value = value.strip()
        if value in {"<", "低于", "小于", "less_than"}:
            return "<"
        if value in {">", "高于", "大于", "超过", "greater_than"}:
            return ">"
        return None

    def _normalize_number(self, value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)
        match = re.search(r"\d{1,2}", str(value))
        return int(match.group(0)) if match else None

    def _continue_slot_fill(self, user_text: str, state: SessionState) -> IntentResult:
        pending = state.pending_action or {}
        intent = pending.get("intent", "unknown")
        slots = dict(pending.get("slots", {}))
        new_slots = self.nlu.extract_generic_slots(user_text, state)
        slots.update({key: value for key, value in new_slots.items() if value is not None})

        missing = pending.get("missing_slots", [])
        if "medicine" in missing and not slots.get("medicine") and "药" in user_text:
            slots["medicine"] = user_text.strip(" ，。,.")
        if "message" in missing and not slots.get("message"):
            slots["message"] = user_text.strip(" ，。,.")
        if "contact" in missing and not slots.get("contact"):
            slots["contact"] = "家属"

        current_missing = self.nlu.missing_for_intent(intent, slots)
        if not current_missing:
            state.pending_action = None
        else:
            state.pending_action = {
                "kind": "slot_fill",
                "action_id": pending.get("action_id") or self._new_action_id(),
                "intent": intent,
                "slots": slots,
                "missing_slots": current_missing,
            }
        return IntentResult(intent, slots, 0.85, current_missing, "rules")

    def _plan(self, result: IntentResult) -> list[PlanStep]:
        tool_name = TOOL_BY_INTENT.get(result.intent)
        if not tool_name:
            return []
        return [PlanStep(step_id=f"step-{uuid.uuid4().hex[:8]}", tool_name=tool_name, args=result.slots)]

    def _execute_plan(self, state: SessionState, plan_steps: list[PlanStep]) -> list[dict[str, Any]]:
        events = []
        for step in plan_steps:
            event = self.tools.execute(state, step)
            event_dict = event.to_dict()
            events.append(event_dict)
            state.recent_tool_events.append(event_dict)
            follow_up = self._plan_env_rule_immediate_check(state, event_dict)
            if follow_up:
                follow_event = self.tools.execute(state, follow_up)
                follow_event_dict = follow_event.to_dict()
                events.append(follow_event_dict)
                state.recent_tool_events.append(follow_event_dict)
        state.recent_tool_events = trim_event_history(state.recent_tool_events)
        return events

    def _plan_env_rule_immediate_check(self, state: SessionState, event: dict[str, Any]) -> PlanStep | None:
        if event.get("tool_name") != "upsert_env_rule" or not event.get("success"):
            return None
        rule = event.get("output", {}).get("rule") or {}
        room = rule.get("room")
        comparator = rule.get("comparator")
        threshold = rule.get("threshold")
        if not room or comparator not in {"<", ">"} or threshold is None:
            return None
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            return None
        sensor = state.sensors.get(room) or {}
        temperature = sensor.get("temperature")
        if temperature is None:
            return None
        matched = temperature < threshold_value if comparator == "<" else temperature > threshold_value
        if not matched:
            return None
        return PlanStep(
            step_id=f"step-{uuid.uuid4().hex[:8]}",
            tool_name="control_device",
            args={
                "room": room,
                "device": rule.get("device"),
                "action": rule.get("action"),
                "target_temp": rule.get("target_temp"),
                "trigger": "env_rule_immediate_check",
                "rule_id": rule.get("id"),
                "comparator": comparator,
                "threshold": threshold,
            },
        )

    def _answer_with_rag(self, user_text: str, state: SessionState) -> tuple[str, list[dict[str, Any]]]:
        context_terms = []
        if state.last_reminder_id:
            reminder = next((item for item in state.reminders if item.get("id") == state.last_reminder_id), None)
            if reminder and reminder.get("medicine"):
                context_terms.append(reminder["medicine"])
        refs = self.rag.search(user_text, context_terms=context_terms)
        if not refs:
            return "本地知识库没有相关内容。我不能编造医疗建议，建议以医生或药品说明书为准。", []
        first = refs[0]
        reply = f"根据本地知识库《{first.title}》：{first.snippet}"
        return reply, [ref.to_dict() for ref in refs]

    def _requires_confirmation(self, result: IntentResult, plan_steps: list[PlanStep]) -> bool:
        if result.intent == "notify_family":
            return True
        return result.intent == "control_device" and bool(result.slots.get("batch"))

    def _confirmation_text(self, result: IntentResult, action_id: str, short: bool = False) -> str:
        if result.intent == "notify_family":
            contact = result.slots.get("contact", "家属")
            message = result.slots.get("message", "")
            if short:
                return f"请确认是否通知{contact}。"
            return f"将模拟通知{contact}：{message}。请确认是否发送。确认编号：{action_id}"
        return f"该操作需要确认。确认编号：{action_id}"

    def _reply_for_events(self, result: IntentResult, events: list[dict[str, Any]], short: bool = False) -> str:
        failed = next((event for event in events if not event["success"]), None)
        if failed:
            return f"操作失败：{failed['output'].get('error', '未知错误')}。"
        output = events[-1]["output"] if events else {}

        if result.intent == "create_reminder":
            if short:
                return "已创建提醒。"
            reminder = output["reminder"]
            return f"已创建用药提醒：{reminder['person']}于{reminder['time_text']}吃{reminder['medicine']}。"
        if result.intent == "update_reminder":
            if short:
                return "已更新提醒。"
            reminder = output["reminder"]
            return f"已更新提醒：{reminder['person']}于{reminder['time_text']}吃{reminder['medicine']}。"
        if result.intent == "query_reminder":
            reminders = output.get("reminders", [])
            if not reminders:
                return "当前没有已保存的用药提醒。"
            if short:
                return f"当前有{len(reminders)}条提醒。"
            parts = [f"{item['time_text']} {item['person']}吃{item['medicine']}" for item in reminders]
            return "当前提醒：" + "；".join(parts)
        if result.intent == "query_sensor":
            sensor = output["sensor"]
            if short:
                return f"{output['room']} {sensor['temperature']}度，湿度{sensor['humidity']}%。"
            return f"{output['room']}当前温度{sensor['temperature']}度，湿度{sensor['humidity']}%，活动状态{sensor['motion']}。"
        if result.intent == "control_device":
            if short:
                return "已更新设备。"
            device = output["device"]
            temp = f"，目标温度{device['target_temp']}度" if device.get("target_temp") is not None else ""
            return f"已更新{device['room']}{device['device']}：{device['status']}{temp}。"
        if result.intent == "upsert_env_rule":
            if short:
                return "已保存环境规则。"
            rule_output = next((event["output"] for event in events if event.get("tool_name") == "upsert_env_rule"), output)
            rule = rule_output["rule"]
            target = f"到{rule['target_temp']}度" if rule.get("target_temp") is not None else ""
            triggered = any(
                event.get("tool_name") == "control_device"
                and event.get("input", {}).get("trigger") == "env_rule_immediate_check"
                and event.get("success")
                for event in events
            )
            suffix = "当前条件已满足，已执行设备联动。" if triggered else ""
            return f"已创建环境联动规则：{rule['room']}温度{rule['comparator']}{rule['threshold']}度时，{rule['action']}{rule['device']}{target}。{suffix}"
        if result.intent == "notify_family":
            if short:
                return "已模拟通知。"
            return f"已模拟通知{output['contact']}：{output['message']}。"
        return "操作已完成。"

    def _ask_for_missing(self, result: IntentResult, short: bool = False) -> str:
        labels = [MISSING_LABELS.get(name, name) for name in result.missing_slots]
        if short:
            return "还需要：" + "、".join(labels) + "。"
        return "还需要补充：" + "、".join(labels) + "。"

    def _response(
        self,
        started: float,
        state: SessionState,
        assistant_text: str,
        result: IntentResult,
        plan_steps: list[PlanStep],
        tool_events: list[dict[str, Any]],
        knowledge_refs: list[dict[str, Any]],
        requires_confirmation: bool,
        llm_used: bool,
        llm_status: dict[str, Any],
        mode: str = "health_assistant",
    ) -> dict[str, Any]:
        return {
            "assistant_text": assistant_text,
            "mode": mode,
            "intent": result.intent,
            "slots": result.slots,
            "missing_slots": result.missing_slots,
            "plan_steps": [step.to_dict() for step in plan_steps],
            "tool_events": tool_events,
            "knowledge_refs": knowledge_refs,
            "requires_confirmation": requires_confirmation,
            "pending_action": state.pending_action,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "llm_used": llm_used,
            "llm_status": llm_status,
        }

    def _append_conversation(self, state: SessionState, user_text: str, assistant_text: str) -> None:
        state.conversation.append({"role": "user", "text": user_text})
        state.conversation.append({"role": "assistant", "text": assistant_text})
        state.conversation = state.conversation[-20:]

    def _is_confirm(self, text: str) -> bool:
        return text in {"确认", "同意", "可以", "执行", "发送", "好的", "是", "对"}

    def _is_reject(self, text: str) -> bool:
        return text in {"取消", "不要", "不用", "拒绝", "否", "不是", "别发", "不发"}

    def _new_action_id(self) -> str:
        return f"act-{uuid.uuid4().hex[:8]}"

    def _normalize_mode(self, mode: str | None) -> str:
        return mode if mode in CHAT_MODES else "health_assistant"
