from __future__ import annotations

import time
import uuid
import sys
from typing import Any

from .llm_adapter import LLMAdapter
from .memory import MemoryStore, trim_event_history
from .models import IntentResult, PlanStep, SessionState
from .nlu import RuleNLU
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

    def chat(self, session_id: str, user_text: str) -> dict[str, Any]:
        started = time.perf_counter()
        state = self.memory.load(session_id)
        user_text = user_text.strip().strip("\"“”")

        if state.pending_action and self._is_confirm(user_text):
            return self.confirm(session_id, state.pending_action.get("action_id", ""), True, started)
        if state.pending_action and self._is_reject(user_text):
            return self.confirm(session_id, state.pending_action.get("action_id", ""), False, started)

        if state.pending_action and state.pending_action.get("kind") == "slot_fill":
            result = self._continue_slot_fill(user_text, state)
            llm_used = False
            llm_status = self.llm.status().to_dict()
        else:
            result = self.nlu.analyze(user_text, state)
            result, llm_used, llm_status = self._maybe_apply_llm(user_text, result)

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
            )

        if result.missing_slots:
            state.pending_action = {
                "kind": "slot_fill",
                "action_id": self._new_action_id(),
                "intent": result.intent,
                "slots": result.slots,
                "missing_slots": result.missing_slots,
            }
            state.last_intent = result.intent
            self._append_conversation(state, user_text, self._ask_for_missing(result))
            self.memory.save(state)
            return self._response(
                started,
                state,
                self._ask_for_missing(result),
                result,
                [],
                [],
                [],
                False,
                llm_used,
                llm_status,
            )

        if result.intent == "knowledge_query":
            reply, refs = self._answer_with_rag(user_text, state)
            state.pending_action = None
            state.last_intent = result.intent
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, [], [], refs, False, llm_used, llm_status)

        if result.intent == "unknown":
            reply = "我还没有理解这句话。可以试试说：明早 7 点提醒奶奶吃降压药，或者问卧室温度。"
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, [], [], [], False, llm_used, llm_status)

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
            reply = self._confirmation_text(result, action_id)
            state.last_intent = result.intent
            self._append_conversation(state, user_text, reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, plan_steps, [], [], True, llm_used, llm_status)

        events = self._execute_plan(state, plan_steps)
        state.pending_action = None
        state.last_intent = result.intent
        reply = self._reply_for_events(result, events)
        self._append_conversation(state, user_text, reply)
        self.memory.save(state)
        return self._response(started, state, reply, result, plan_steps, events, [], False, llm_used, llm_status)

    def confirm(
        self,
        session_id: str,
        action_id: str,
        approved: bool,
        started: float | None = None,
    ) -> dict[str, Any]:
        started = started or time.perf_counter()
        state = self.memory.load(session_id)
        pending = state.pending_action
        if not pending or pending.get("kind") != "tool_approval":
            result = IntentResult("confirm" if approved else "reject", confidence=0.99)
            return self._response(started, state, "当前没有需要确认的操作。", result, [], [], [], False, False, self.llm.status().to_dict())

        if action_id and action_id != pending.get("action_id"):
            result = IntentResult("confirm", confidence=0.99)
            return self._response(started, state, "确认编号不匹配，操作未执行。", result, [], [], [], True, False, self.llm.status().to_dict())

        result = IntentResult(pending["intent"], pending.get("slots", {}), confidence=0.99)
        plan_steps = [PlanStep(**step) for step in pending.get("plan_steps", [])]
        if not approved:
            state.pending_action = None
            reply = "已取消这次操作。"
            self._append_conversation(state, "拒绝确认", reply)
            self.memory.save(state)
            return self._response(started, state, reply, result, plan_steps, [], [], False, False, self.llm.status().to_dict())

        events = self._execute_plan(state, plan_steps)
        state.pending_action = None
        state.last_intent = result.intent
        reply = self._reply_for_events(result, events)
        self._append_conversation(state, "确认执行", reply)
        self.memory.save(state)
        return self._response(started, state, reply, result, plan_steps, events, [], False, False, self.llm.status().to_dict())

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

    def _maybe_apply_llm(self, user_text: str, result: IntentResult) -> tuple[IntentResult, bool, dict[str, Any]]:
        should_try = result.intent == "unknown" or bool(result.missing_slots)
        if not should_try:
            return result, False, self.llm.status().to_dict()

        llm_data, status = self.llm.parse_intent_json(user_text, result.slots)
        if not llm_data:
            return result, False, status.to_dict()

        intent = llm_data.get("intent")
        if intent not in KNOWN_INTENTS:
            return result, False, status.to_dict()
        slots = {**result.slots, **(llm_data.get("slots") or {})}
        missing = self.nlu.missing_for_intent(intent, slots)
        candidate = IntentResult(intent, slots, float(llm_data.get("confidence", 0.5)), missing, "llm")
        if result.intent == "unknown" or len(candidate.missing_slots) <= len(result.missing_slots):
            return candidate, True, status.to_dict()
        return result, False, status.to_dict()

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
        state.recent_tool_events = trim_event_history(state.recent_tool_events)
        return events

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

    def _confirmation_text(self, result: IntentResult, action_id: str) -> str:
        if result.intent == "notify_family":
            contact = result.slots.get("contact", "家属")
            message = result.slots.get("message", "")
            return f"将模拟通知{contact}：{message}。请确认是否发送。确认编号：{action_id}"
        return f"该操作需要确认。确认编号：{action_id}"

    def _reply_for_events(self, result: IntentResult, events: list[dict[str, Any]]) -> str:
        failed = next((event for event in events if not event["success"]), None)
        if failed:
            return f"操作失败：{failed['output'].get('error', '未知错误')}。"
        output = events[-1]["output"] if events else {}

        if result.intent == "create_reminder":
            reminder = output["reminder"]
            return f"已创建用药提醒：{reminder['person']}于{reminder['time_text']}吃{reminder['medicine']}。"
        if result.intent == "update_reminder":
            reminder = output["reminder"]
            return f"已更新提醒：{reminder['person']}于{reminder['time_text']}吃{reminder['medicine']}。"
        if result.intent == "query_reminder":
            reminders = output.get("reminders", [])
            if not reminders:
                return "当前没有已保存的用药提醒。"
            parts = [f"{item['time_text']} {item['person']}吃{item['medicine']}" for item in reminders]
            return "当前提醒：" + "；".join(parts)
        if result.intent == "query_sensor":
            sensor = output["sensor"]
            return f"{output['room']}当前温度{sensor['temperature']}度，湿度{sensor['humidity']}%，活动状态{sensor['motion']}。"
        if result.intent == "control_device":
            device = output["device"]
            temp = f"，目标温度{device['target_temp']}度" if device.get("target_temp") is not None else ""
            return f"已更新{device['room']}{device['device']}：{device['status']}{temp}。"
        if result.intent == "upsert_env_rule":
            rule = output["rule"]
            target = f"到{rule['target_temp']}度" if rule.get("target_temp") is not None else ""
            return f"已创建环境联动规则：{rule['room']}温度{rule['comparator']}{rule['threshold']}度时，{rule['action']}{rule['device']}{target}。"
        if result.intent == "notify_family":
            return f"已模拟通知{output['contact']}：{output['message']}。"
        return "操作已完成。"

    def _ask_for_missing(self, result: IntentResult) -> str:
        labels = [MISSING_LABELS.get(name, name) for name in result.missing_slots]
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
    ) -> dict[str, Any]:
        return {
            "assistant_text": assistant_text,
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
