import os
import re
from groq import AsyncGroq
from app.agent.prompts import SYSTEM_PROMPT, SOLIDWORKS_VBA_PROMPT

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            print("WARNING: GROQ_API_KEY not found in environment variables.")
        
        self.client = AsyncGroq(api_key=self.api_key)
        self.model = "llama-3.3-70b-versatile" # "llama3-70b-8192" was decommissioned

    def _sanitize_code(self, raw_text: str) -> str:
        """
        Removes markdown backticks and unsafe imports.
        """
        # 1. Strip Markdown Code Blocks
        clean_text = raw_text
        code_block_pattern = r"```(?:python)?\s*(.*?)```"
        match = re.search(code_block_pattern, raw_text, re.DOTALL)
        if match:
            clean_text = match.group(1)
            
        clean_text = clean_text.strip()
        
        # 2. Safety Check (Basic)
        forbidden = ["import os", "import sys", "subprocess", "exec(", "eval(", "open("]
        for term in forbidden:
            if term in clean_text:
                raise ValueError(f"Generated code contains forbidden term: {term}")
                
        return clean_text

    async def generate_cad_script(self, user_prompt: str) -> str:
        """
        Generates a clean build123d script from a user prompt.
        """
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1, # Low temperature for code
                max_tokens=2048
            )
            
            raw_response = completion.choices[0].message.content
            return self._sanitize_code(raw_response)
            
        except Exception as e:
            print(f"LLM Generation Error: {e}")
            raise e

    async def generate_solidworks_macro(self, user_prompt: str) -> str:
        """
        Generates a SolidWorks VBA macro from a user prompt.
        """
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SOLIDWORKS_VBA_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=2048
            )
            
            raw_response = completion.choices[0].message.content
            # Reuse sanitization as it removes markdown ticks
            return self._sanitize_code(raw_response)
            
        except Exception as e:
            print(f"LLM Macro Generation Error: {e}")
            raise e
