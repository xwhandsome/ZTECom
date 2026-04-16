from __future__ import annotations

import argparse
import json

from agent_py.api import create_app
from agent_py.engine import CareAgent


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="老人关怀端侧智能体 Python 主入口")
    parser.add_argument("--api", action="store_true", help="启动 FastAPI 服务供 Java 展示层调用")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--session", default="demo")
    parser.add_argument("--once", help="执行单轮文本输入并输出 JSON，便于脚本测试")
    args = parser.parse_args(argv)

    if args.api:
        import uvicorn

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return

    engine = CareAgent()
    if args.once:
        print(json.dumps(engine.chat(args.session, args.once), ensure_ascii=False, indent=2))
        return

    _run_cli(engine, args.session)


def _run_cli(engine: CareAgent, session_id: str) -> None:
    print("老人关怀端侧智能体 CLI。输入 exit 退出，输入 reset 重置演示状态。")
    while True:
        try:
            text = input("用户> ").strip()
        except EOFError:
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            break
        if text.lower() == "reset":
            engine.reset(session_id)
            print("助手> 已重置演示状态。")
            continue
        response = engine.chat(session_id, text)
        print(f"助手> {response['assistant_text']}")


if __name__ == "__main__":
    run()
