from __future__ import annotations

import ctypes
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONDA_PREFIX


_DLL_HANDLES: list[Any] = []
_DLL_DIR_HANDLES: list[Any] = []


@dataclass
class LLMStatus:
    enabled: bool
    runtime_available: bool
    model_path: str | None
    model_exists: bool
    loaded: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMAdapter:
    def __init__(self, conda_prefix: str | Path | None = None) -> None:
        self.conda_prefix = Path(conda_prefix or os.environ.get("CONDA_PREFIX") or DEFAULT_CONDA_PREFIX)
        self.enabled = os.environ.get("ZTECOM_ENABLE_LLM", "0") == "1"
        self.model_path = os.environ.get("ZTECOM_MODEL_PATH")
        self._runtime_checked = False
        self._runtime_available = False
        self._runtime_message = "runtime_not_checked"
        self._llama = None

    def status(self, probe_runtime: bool = False) -> LLMStatus:
        if probe_runtime and not self._runtime_checked:
            self._ensure_runtime()
        model_exists = bool(self.model_path and Path(self.model_path).is_file())
        message = self._runtime_message
        if not self.enabled:
            message = f"disabled; {message}"
        elif not self.model_path:
            message = f"model_path_missing; {message}"
        elif not model_exists:
            message = f"model_file_missing; {message}"
        return LLMStatus(
            enabled=self.enabled,
            runtime_available=self._runtime_available,
            model_path=self.model_path,
            model_exists=model_exists,
            loaded=self._llama is not None,
            message=message,
        )

    def parse_intent_json(self, user_text: str, slots: dict[str, Any]) -> tuple[dict[str, Any] | None, LLMStatus]:
        if not self.enabled:
            return None, self.status()
        if not self.model_path or not Path(self.model_path).is_file():
            return None, self.status(probe_runtime=True)
        try:
            self._load_model()
            prompt = self._build_prompt(user_text, slots)
            raw = self._llama(
                prompt,
                max_tokens=int(os.environ.get("ZTECOM_LLM_MAX_TOKENS", "256")),
                temperature=float(os.environ.get("ZTECOM_LLM_TEMPERATURE", "0.1")),
                stop=["\n\n"],
            )
            content = raw["choices"][0]["text"]
            parsed = self._extract_json(content)
            return parsed, self.status()
        except Exception as exc:
            self._runtime_message = f"llm_failed: {exc}"
            return None, self.status()

    def synthesize_rag_answer(
        self,
        user_text: str,
        refs: list[dict[str, Any]],
        context_hint: str | None = None,
    ) -> tuple[str | None, LLMStatus]:
        if not self.enabled:
            return None, self.status()
        if not self.model_path or not Path(self.model_path).is_file():
            return None, self.status(probe_runtime=True)
        if not refs:
            return None, self.status()
        try:
            self._load_model()
            prompt = self._build_rag_prompt(user_text, refs, context_hint)
            raw = self._llama(
                prompt,
                max_tokens=int(os.environ.get("ZTECOM_RAG_LLM_MAX_TOKENS", os.environ.get("ZTECOM_LLM_MAX_TOKENS", "256"))),
                temperature=float(os.environ.get("ZTECOM_LLM_TEMPERATURE", "0.1")),
                stop=["\n\n用户", "\n\n问题", "\n\n本地知识片段"],
            )
            content = raw["choices"][0]["text"]
            answer = self._clean_text_answer(content)
            return answer, self.status()
        except Exception as exc:
            self._runtime_message = f"llm_failed: {exc}"
            return None, self.status()

    def _ensure_runtime(self) -> None:
        self._runtime_checked = True
        if os.name != "nt":
            self._runtime_available = True
            self._runtime_message = "non_windows_runtime"
            return

        try:
            os.environ.setdefault("PYTHONNOUSERSITE", "1")
            prefix = self.conda_prefix
            dll_dirs = [
                prefix,
                prefix / "Library" / "bin",
                prefix / "Lib" / "site-packages" / "llama_cpp" / "lib",
                prefix / "Lib" / "site-packages" / "nvidia" / "cuda_runtime" / "bin",
                prefix / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin",
            ]
            existing_dirs = [path for path in dll_dirs if path.exists()]
            os.environ["PATH"] = os.pathsep.join(str(path) for path in existing_dirs) + os.pathsep + os.environ.get("PATH", "")
            for path in existing_dirs:
                handle = os.add_dll_directory(str(path))
                _DLL_DIR_HANDLES.append(handle)

            llama_lib = prefix / "Lib" / "site-packages" / "llama_cpp" / "lib"
            for dll_name in ["ggml-base.dll", "ggml-cpu.dll", "ggml-cuda.dll", "ggml.dll", "llama.dll"]:
                dll_path = llama_lib / dll_name
                if dll_path.exists():
                    _DLL_HANDLES.append(ctypes.CDLL(str(dll_path)))

            import llama_cpp  # noqa: F401

            self._runtime_available = True
            self._runtime_message = "runtime_ok"
        except Exception as exc:
            self._runtime_available = False
            self._runtime_message = f"runtime_error: {exc}"

    def _load_model(self) -> None:
        if self._llama is not None:
            return
        self._ensure_runtime()
        if not self._runtime_available:
            raise RuntimeError(self._runtime_message)
        from llama_cpp import Llama

        self._llama = Llama(
            model_path=str(self.model_path),
            n_ctx=int(os.environ.get("ZTECOM_LLM_N_CTX", "1024")),
            n_gpu_layers=int(os.environ.get("ZTECOM_LLM_GPU_LAYERS", "0")),
            verbose=False,
        )

    def _build_prompt(self, user_text: str, slots: dict[str, Any]) -> str:
        known_slots = json.dumps(slots, ensure_ascii=False)
        return (
            "你是老人关怀端侧智能体的意图和槽位解析器。只输出一个 JSON 对象，不要解释，不要 Markdown。\n"
            "顶层 schema 固定为: {\"intent\": string, \"slots\": object, \"confidence\": number}。\n"
            "intent 只能取: create_reminder, update_reminder, query_reminder, query_sensor, control_device, "
            "upsert_env_rule, notify_family, knowledge_query, unknown。\n"
            "slots 只能使用这些字段: medicine, person, time_text, room, device, action, target_temp, "
            "brightness, brightness_delta, comparator, threshold, contact, message, query。\n"
            "不要使用 drug, medicine_name, reminder_type, to, target, person_name 等别名字段。\n"
            "提醒吃药时，medicine 填药品名，例如 降压药；person 填老人称呼，例如 奶奶；time_text 填自然语言时间。\n"
            "设备动作 action 只能取 on, off, set；低于用 comparator '<'，高于或超过用 comparator '>'。\n"
            "灯光亮度用 brightness 表示百分比整数 0-100，例如 70；调亮/调暗可用 brightness_delta。\n"
            f"已知规则槽位: {known_slots}\n"
            "示例1 用户输入: 给奶奶安排明天早晨七点服用降压药\n"
            "示例1 JSON: {\"intent\":\"create_reminder\",\"slots\":{\"person\":\"奶奶\",\"medicine\":\"降压药\",\"time_text\":\"明天早晨七点\"},\"confidence\":0.9}\n"
            "示例2 用户输入: 帮我查一下卧室现在温度\n"
            "示例2 JSON: {\"intent\":\"query_sensor\",\"slots\":{\"room\":\"卧室\"},\"confidence\":0.9}\n"
            f"用户输入: {user_text}\n"
            "JSON:"
        )

    def _build_rag_prompt(self, user_text: str, refs: list[dict[str, Any]], context_hint: str | None = None) -> str:
        ref_lines = []
        for index, ref in enumerate(refs[:3], start=1):
            title = ref.get("title") or ref.get("doc_id") or f"片段{index}"
            snippet = ref.get("snippet") or ""
            ref_lines.append(f"[{index}] {title}: {snippet}")
        hint = f"上下文提示: {context_hint}\n" if context_hint else ""
        return (
            "你是老人关怀端侧智能体的本地知识归纳器。只能根据给出的本地知识片段回答，不要使用片段外知识。\n"
            "要求: 用中文回答，2到4句；不要编造诊断、处方或片段外剂量；涉及用药时提醒遵医嘱或咨询医生/药师。\n"
            "本地知识片段按相关性排序，优先使用[1]；如果[1]已经直接回答问题，不要说依据不足。\n"
            "只有所有片段都没有相关依据时，才说本地知识库依据不足。\n"
            f"{hint}"
            "本地知识片段:\n"
            + "\n".join(ref_lines)
            + f"\n用户问题: {user_text}\n"
            "回答:"
        )

    def _clean_text_answer(self, content: str) -> str | None:
        answer = re.sub(r"^\s*(回答|答案)[:：]\s*", "", content or "").strip()
        answer = re.sub(r"\s+", " ", answer)
        if not answer:
            return None
        return answer[:500]

    def _extract_json(self, content: str) -> dict[str, Any] | None:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        if not isinstance(data, dict) or "intent" not in data:
            return None
        data.setdefault("slots", {})
        data.setdefault("confidence", 0.5)
        return data
