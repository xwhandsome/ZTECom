from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .models import IntentResult, SessionState


ROOMS = ["卧室", "客厅", "厨房", "卫生间", "书房"]
DEVICES = ["空调", "灯光", "灯", "加湿器"]
CONTACTS = ["儿子", "女儿", "家属", "联系人"]
CONFIRM_WORDS = {"确认", "同意", "可以", "执行", "发送", "好的", "是", "对"}
REJECT_WORDS = {"取消", "不要", "不用", "拒绝", "否", "不是", "别发", "不发"}


REQUIRED_SLOTS = {
    "create_reminder": ["medicine", "time"],
    "update_reminder": ["reminder_id", "time"],
    "query_sensor": ["room"],
    "control_device": ["room", "device", "action"],
    "upsert_env_rule": ["room", "comparator", "threshold", "device", "action"],
    "notify_family": ["contact", "message"],
    "knowledge_query": ["query"],
}


CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def cn_to_int(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if raw.startswith("十"):
        return 10 + CN_DIGITS.get(raw[1:], 0)
    if "十" in raw:
        left, right = raw.split("十", 1)
        return CN_DIGITS.get(left, 1) * 10 + CN_DIGITS.get(right, 0)
    return CN_DIGITS.get(raw)


def normalize_device(device: str | None) -> str | None:
    if not device:
        return None
    return "灯" if device == "灯光" else device


def extract_room(text: str) -> str | None:
    for room in ROOMS:
        if room in text:
            return room
    if "房间" in text:
        return "卧室"
    return None


def extract_device(text: str) -> str | None:
    for device in DEVICES:
        if device in text:
            return normalize_device(device)
    return None


def extract_person(text: str, state: SessionState | None = None) -> str:
    for person in ["奶奶", "爷爷", "外婆", "外公", "老人", "妈妈", "爸爸"]:
        if person in text:
            return "奶奶" if person == "老人" else person
    if state:
        return state.profile.get("elder_name", "奶奶")
    return "奶奶"


def parse_time_text(text: str, base: datetime | None = None) -> dict[str, Any] | None:
    base = base or datetime.now()
    hour_pat = r"(?P<hour>\d{1,2}|[一二两三四五六七八九十]{1,3})"
    minute_pat = r"(?P<minute>半|(?:\d{1,2}|[一二两三四五六七八九十]{1,3})\s*分?)?"
    match = re.search(rf"{hour_pat}\s*[点:：]\s*{minute_pat}", text)
    if not match:
        return None

    hour = cn_to_int(match.group("hour"))
    if hour is None:
        return None

    raw_minute = (match.group("minute") or "").strip()
    if raw_minute == "半":
        minute = 30
    elif raw_minute:
        minute = cn_to_int(raw_minute.replace("分", "").strip()) or 0
    else:
        minute = 0

    date = base.date()
    date_explicit = False
    if "后天" in text:
        date = date + timedelta(days=2)
        date_explicit = True
    elif "明天" in text or "明早" in text or "明晚" in text:
        date = date + timedelta(days=1)
        date_explicit = True
    elif "今天" in text or "今晚" in text or "今早" in text:
        date_explicit = True

    if any(word in text for word in ["下午", "晚上", "今晚", "晚间", "夜里"]) and hour < 12:
        hour += 12
    if any(word in text for word in ["中午"]) and hour < 11:
        hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None

    dt = datetime.combine(date, datetime.min.time()).replace(hour=hour, minute=minute)
    day_label = "今天"
    if date == (base.date() + timedelta(days=1)):
        day_label = "明天"
    elif date == (base.date() + timedelta(days=2)):
        day_label = "后天"
    elif date != base.date():
        day_label = date.isoformat()

    return {
        "time": dt.isoformat(timespec="minutes"),
        "time_text": f"{day_label} {hour:02d}:{minute:02d}",
        "hour": hour,
        "minute": minute,
        "date_explicit": date_explicit,
    }


def extract_medicine(text: str) -> str | None:
    match = re.search(r"吃(?P<medicine>[^，。,.！？!?]+)", text)
    if not match:
        return None
    medicine = match.group("medicine").strip()
    medicine = medicine.strip("\"“”")
    medicine = re.sub(r"^(点|半|药|一下|一个)$", "", medicine)
    medicine = re.sub(r"(的时候|提醒|吧|吗|呢)$", "", medicine).strip()
    medicine = re.sub(r"^(饭前|饭后|早上|晚上|明天|今天)", "", medicine).strip()
    if not medicine or medicine in {"药", "这个药"}:
        return None
    if len(medicine) > 16:
        medicine = medicine[:16]
    return medicine


def extract_action(text: str) -> str | None:
    if any(word in text for word in ["关闭", "关掉", "关上"]):
        return "off"
    if any(word in text for word in ["打开", "开启", "开空调", "开灯", "自动开"]):
        return "on"
    if any(word in text for word in ["调到", "设到", "设为", "设置到"]):
        return "set"
    return None


def extract_target_temp(text: str) -> int | None:
    match = re.search(r"(?:调到|设到|设置到|设为|到|为|至)\s*(?P<temp>\d{1,2})\s*度", text)
    if not match:
        if "低于" in text or "高于" in text or "超过" in text:
            return None
        match = re.search(r"(?P<temp>\d{1,2})\s*度", text)
        if not match:
            return None
    value = int(match.group("temp"))
    return value if 5 <= value <= 40 else None


def extract_threshold(text: str) -> tuple[str | None, int | None]:
    match = re.search(r"(低于|小于|高于|大于|超过)\s*(?P<value>\d{1,2})\s*度", text)
    if not match:
        return None, None
    comparator = "<" if match.group(1) in {"低于", "小于"} else ">"
    return comparator, int(match.group("value"))


def extract_contact(text: str) -> str | None:
    for contact in CONTACTS:
        if contact in text:
            return "家属" if contact == "联系人" else contact
    return None


def extract_notify_message(text: str, contact: str | None) -> str | None:
    if not contact:
        return None
    pattern = rf"(?:通知|告诉|联系)(?:我)?{re.escape(contact)}(?P<message>.*)"
    match = re.search(pattern, text)
    message = (match.group("message") if match else "").strip()
    if message.startswith("说"):
        message = message[1:].strip()
    return message or None


class RuleNLU:
    def analyze(self, text: str, state: SessionState) -> IntentResult:
        text = text.strip()
        if not text:
            return IntentResult("unknown", confidence=0.0)

        if text in CONFIRM_WORDS:
            return IntentResult("confirm", confidence=0.99)
        if text in REJECT_WORDS:
            return IntentResult("reject", confidence=0.99)

        if self._looks_like_knowledge(text):
            slots = {"query": text}
            return IntentResult("knowledge_query", slots, 0.85, self.missing_for_intent("knowledge_query", slots))

        if any(word in text for word in ["通知", "告诉", "联系"]):
            slots = self.extract_generic_slots(text, state)
            slots["contact"] = slots.get("contact") or "家属"
            slots["message"] = extract_notify_message(text, slots["contact"])
            return IntentResult("notify_family", slots, 0.9, self.missing_for_intent("notify_family", slots))

        if ("如果" in text or "自动" in text) and ("低于" in text or "高于" in text or "超过" in text):
            slots = self.extract_generic_slots(text, state)
            comparator, threshold = extract_threshold(text)
            slots.update({"comparator": comparator, "threshold": threshold})
            after_time = parse_time_text(text)
            if after_time:
                slots["time_after"] = after_time
            return IntentResult("upsert_env_rule", slots, 0.92, self.missing_for_intent("upsert_env_rule", slots))

        if any(word in text for word in ["温度", "湿度", "传感器", "环境"]) and not extract_device(text):
            slots = self.extract_generic_slots(text, state)
            return IntentResult("query_sensor", slots, 0.86, self.missing_for_intent("query_sensor", slots))

        if extract_device(text) and any(word in text for word in ["打开", "关闭", "关掉", "开启", "调到", "设为", "设置"]):
            slots = self.extract_generic_slots(text, state)
            return IntentResult("control_device", slots, 0.9, self.missing_for_intent("control_device", slots))

        if any(word in text for word in ["改成", "改到", "修改", "调成", "换成"]):
            slots = self.extract_generic_slots(text, state)
            slots["reminder_id"] = state.last_reminder_id
            medicine = extract_medicine(text)
            if medicine:
                slots["medicine"] = medicine
            return IntentResult("update_reminder", slots, 0.88, self.missing_for_intent("update_reminder", slots))

        if "提醒" in text and any(word in text for word in ["查", "看", "有哪些", "查询"]):
            return IntentResult("query_reminder", confidence=0.82)

        if "提醒" in text or "吃" in text and "药" in text:
            slots = self.extract_generic_slots(text, state)
            medicine = extract_medicine(text)
            if medicine:
                slots["medicine"] = medicine
            return IntentResult("create_reminder", slots, 0.86, self.missing_for_intent("create_reminder", slots))

        return IntentResult("unknown", {"query": text}, 0.2, [])

    def extract_generic_slots(self, text: str, state: SessionState | None = None) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        room = extract_room(text)
        if room:
            slots["room"] = room
        device = extract_device(text)
        if device:
            slots["device"] = device
        action = extract_action(text)
        if action:
            slots["action"] = action
        target_temp = extract_target_temp(text)
        if target_temp is not None:
            slots["target_temp"] = target_temp
            if "action" not in slots:
                slots["action"] = "set"
        time_info = parse_time_text(text)
        if time_info:
            slots.update(time_info)
        medicine = extract_medicine(text)
        if medicine:
            slots["medicine"] = medicine
        contact = extract_contact(text)
        if contact:
            slots["contact"] = contact
        person = extract_person(text, state)
        if person:
            slots["person"] = person
        return slots

    def missing_for_intent(self, intent: str, slots: dict[str, Any]) -> list[str]:
        required = REQUIRED_SLOTS.get(intent, [])
        return [name for name in required if not slots.get(name)]

    def _looks_like_knowledge(self, text: str) -> bool:
        question_words = ["为什么", "怎么", "如何", "什么时候", "饭前", "饭后", "说明", "注意", "这个药"]
        if not any(word in text for word in question_words):
            return False
        if any(word in text for word in ["提醒我", "提醒奶奶", "打开", "关闭"]):
            return False
        if "通知" in text and not any(word in text for word in ["为什么", "规则", "说明", "注意"]):
            return False
        return True
