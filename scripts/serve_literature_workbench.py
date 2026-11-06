"""Explicit localhost UI acceptance server: real local RAG, in-memory Mock chat/answers.

uv run --extra rag --offline python scripts/serve_literature_workbench.py
Only upload scripts/literature_samples.py self-authored PDFs to this acceptance instance.
No real provider, system credential access, model download or user document loading.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import uvicorn

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def set(self, ref, value):
        self.values[ref] = value

    def get(self, ref):
        return self.values.get(ref)

    def delete(self, ref):
        self.values.pop(ref, None)


class MockModel:
    async def ainvoke(self, messages):
        await asyncio.sleep(0.5)
        evidence = json.loads(messages[-1].content)["evidence"]
        return SimpleNamespace(
            content=json.dumps(
                {
                    "answer": (
                        "Mock 本地文献回答：请核对下列正文、表格和图片图注。"
                        "图片仅依据图注/OCR，未进行视觉理解。"
                    )
                    * 6,
                    "citations": [item["chunk_id"] for item in evidence],
                },
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/task40/ui"))
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    root = args.data.resolve()
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=root,
        runs_dir=root / "runs",
        checkpoint_db=root / "cp.sqlite",
        workbench_db=root / "wb.sqlite",
        knowledge_dir=root / "knowledge",
        knowledge_models_dir=Path("data/task38/models").resolve(),
        knowledge_embedding_models_dir=Path("data/embedding-models").resolve(),
    )
    holder = {}

    def prepare(identity, fixed):
        profiles = holder["app"].state.dependencies.model_profiles
        snapshot = fixed or TurnModelSnapshot.model_validate(
            profiles.get(identity).snapshot().model_dump()
        )

        async def stream(messages):
            await asyncio.sleep(0.2)
            latest = next(message for message in reversed(messages) if message.role == "user")
            if latest.knowledge_base_ids and any(
                word in latest.content for word in ["文献", "图", "表", "paper"]
            ):
                yield {"kind": "knowledge_ask", "question": latest.content[:4096]}
            else:
                yield "Mock 普通聊天：知识库选择不会拦截普通对话。"

        return PreparedChat(snapshot, stream, answer_model=MockModel())

    app = create_app(
        settings, overrides={"secret_store": MemorySecrets(), "chat_model_factory": prepare}
    )
    holder["app"] = app
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
