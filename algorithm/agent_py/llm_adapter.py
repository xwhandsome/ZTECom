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
            "你是老人关怀端侧智能体的意图解析器，只输出一个 JSON 对象。\n"
            "intent 只能是 create_reminder, update_reminder, query_reminder, query_sensor, "
            "control_device, upsert_env_rule, notify_family, knowledge_query, unknown。\n"
            "JSON 字段包括 intent, slots, confidence。不要输出解释。\n"
            f"已知槽位: {known_slots}\n"
            f"用户输入: {user_text}\n"
            "JSON:"
        )

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
