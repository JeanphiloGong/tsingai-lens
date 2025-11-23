from typing import List, Optional

from openai import OpenAI


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat endpoints for flexibility."""

    def __init__(self, api_key: str, base_url: Optional[str], model: str, max_tokens: int = 512):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content

    def summarize(self, text: str) -> str:
        prompt = f"请用中文总结以下内容的关键结论和要点：\n\n{text}"
        return self.chat(system="你是科研助手，擅长总结文献。", user=prompt)
