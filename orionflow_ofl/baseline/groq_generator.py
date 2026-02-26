"""Generate OFL code using Groq API with few-shot prompting.

No GPU, no fine-tuning. This is the BASELINE to beat.

Setup:
    pip install groq
    export GROQ_API_KEY=your_key_here
    Get key at: https://console.groq.com/keys
"""

from __future__ import annotations

import os
import re

from .few_shot_examples import FEW_SHOT_EXAMPLES, SYSTEM_PROMPT


class GroqOFLGenerator:
    """Generate OFL code via Groq API with few-shot prompting."""

    def __init__(
        self,
        model: str = "qwen-qwq-32b",
        api_key: str | None = None,
    ):
        try:
            from groq import Groq
        except ImportError:
            raise ImportError(
                "groq package required: pip install groq\n"
                "Get API key at: https://console.groq.com/keys"
            )
        self.client = Groq(api_key=api_key or os.environ.get("GROQ_API_KEY"))
        self.model = model

    def generate(self, prompt: str) -> str:
        """Generate OFL code from natural language prompt."""
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["text"]})
            messages.append({"role": "assistant", "content": example["code"]})

        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
        )

        raw = response.choices[0].message.content
        return self._extract_code(raw)

    @staticmethod
    def _extract_code(text: str) -> str:
        """Extract Python code from response (handle markdown fences)."""
        # ```python ... ```
        m = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # ``` ... ```
        m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # no fences — return as-is
        return text.strip()
