"""In-memory acceptance double, never a claim of real Wiki semantic quality."""

import asyncio
import json
from types import SimpleNamespace


class MockWikiAdapter:
    calls = 0

    def prepare(self, identity, fixed):
        assert fixed.model.startswith("mock")
        self.delay = 2 if fixed.model == "mock-wiki-ui-slow" else 0.15
        return self, fixed

    def bind(self, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        await asyncio.sleep(getattr(self, "delay", 0.15))
        data = json.loads(messages[-1].content)
        item = data["evidence"][0]
        if "stage" not in data:
            return SimpleNamespace(
                content=json.dumps(
                    {"answer": "Mock original RAG answer", "citations": [item["chunk_id"]]}
                )
            )
        kinds = ["paper"] if data["stage"] == "paper" else ["concept", "topic"]
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pages": [
                        {
                            "key": data["page_key"] if kind == "paper" else "mock-" + kind,
                            "kind": kind,
                            "title": "Mock Wiki " + kind,
                            "statements": [
                                {
                                    "text": "Mock 导航陈述，请核对原文；未评价语义质量。",
                                    "conditions": "研究对象、样本、方法、日期和限制需人工核对。",
                                    "candidate_disagreement": True,
                                    "citations": [
                                        {
                                            "chunk_id": item["chunk_id"],
                                            "content_sha256": item["content_sha256"],
                                            "quote": item["text"][:100],
                                        }
                                    ],
                                }
                            ],
                            "links": data["page_keys"] if kind != "paper" else [],
                        }
                        for kind in kinds
                    ]
                },
                ensure_ascii=False,
            )
        )
