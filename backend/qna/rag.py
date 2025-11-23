from textwrap import dedent
from typing import Dict, List

from langchain_core.documents import Document

from backend.services.llm_client import LLMClient


def build_context(docs: List[Document]) -> str:
    blocks = []
    for idx, d in enumerate(docs, 1):
        meta = d.metadata or {}
        origin = meta.get("source", "document")
        blocks.append(f"[{idx}] 来源: {origin}\n{d.page_content.strip()}")
    return "\n\n".join(blocks)


def answer_question(question: str, docs: List[Document], llm: LLMClient) -> Dict:
    context = build_context(docs)
    prompt = dedent(
        f"""
        你是一名科研助手。结合提供的文献片段回答用户问题，优先给出变量关系、正负相关性和可能的无量纲公式建议。
        如果无法从上下文确定答案，请诚实说明。

        用户问题: {question}

        文献片段:
        {context}
        """
    )
    answer = llm.chat(system="你擅长阅读学术文献并给出严谨的中文回答。", user=prompt)
    return {"answer": answer, "context": context}
