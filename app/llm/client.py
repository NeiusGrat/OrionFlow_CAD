"""
LLM Client - Provider-agnostic language model interface.

ONE client, ONE canonical method: generate_feature_graph()
Swap providers (Groq, OpenAI, local) without changing service layer.
"""
import os
import re
import json
from groq import AsyncGroq

from app.domain.feature_graph import FeatureGraph
from app.llm.prompts import FEATURE_GRAPH_PROMPT


class LLMClient:
    """
    Unified LLM interface for CAD generation.
    
    This is the ONLY LLM client in the system.
    Provider can be swapped without affecting upstream code.
    
    Canonical Method:
        generate_feature_graph(prompt) -> FeatureGraph
    """
    
    def __init__(self, provider: str = "groq"):
        """
        Initialize LLM client with specified provider.
        
        Args:
            provider: LLM provider ("groq", "openai", "local")
        """
        self.provider = provider
        
        if provider == "groq":
            self._init_groq()
        elif provider == "openai":
            self._init_openai()
        elif provider == "local":
            self._init_local()
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    def _init_groq(self):
        """Initialize Groq provider."""
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            print("WARNING: GROQ_API_KEY not found in environment variables.")
        
        self.client = AsyncGroq(api_key=self.api_key)
        self.model = "llama-3.3-70b-versatile"
    
    def _init_openai(self):
        """Initialize OpenAI provider (future)."""
        raise NotImplementedError("OpenAI provider not yet implemented")
    
    def _init_local(self):
        """Initialize local LLM provider (future)."""
        raise NotImplementedError("Local LLM provider not yet implemented")
    
    async def generate_feature_graph(self, user_prompt: str) -> FeatureGraph:
        """
        Generate FeatureGraph from natural language prompt.
        
        This is the CANONICAL method for LLM-based CAD generation.
        Returns structured data (FeatureGraph), never executable code.
        
        Args:
            user_prompt: User's natural language description
            
        Returns:
            FeatureGraph object ready for compilation
            
        Raises:
            ValueError: If JSON parsing or validation fails
            Exception: If LLM call fails
        """
        if self.provider == "groq":
            return await self._generate_groq(user_prompt)
        elif self.provider == "openai":
            return await self._generate_openai(user_prompt)
        elif self.provider == "local":
            return await self._generate_local(user_prompt)
    
    async def _generate_groq(self, user_prompt: str) -> FeatureGraph:
        """
        Generate using Groq provider.
        
        Args:
            user_prompt: User's prompt
            
        Returns:
            Validated FeatureGraph
        """
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": FEATURE_GRAPH_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temp for structured output
                max_tokens=2048
            )
            
            raw_response = completion.choices[0].message.content.strip()
            return self._parse_and_validate(raw_response)
            
        except Exception as e:
            print(f"Groq LLM Error: {e}")
            raise
    
    async def _generate_openai(self, user_prompt: str) -> FeatureGraph:
        """
        Generate using OpenAI provider (future implementation).
        
        Args:
            user_prompt: User's prompt
            
        Returns:
            Validated FeatureGraph
        """
        # Future: OpenAI API call
        # from openai import AsyncOpenAI
        # client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # ...
        raise NotImplementedError("OpenAI provider not yet implemented")
    
    async def _generate_local(self, user_prompt: str) -> FeatureGraph:
        """
        Generate using local LLM (future implementation).
        
        Args:
            user_prompt: User's prompt
            
        Returns:
            Validated FeatureGraph
        """
        # Future: Local model inference
        # import transformers or llama.cpp
        # ...
        raise NotImplementedError("Local LLM provider not yet implemented")
    
    def _parse_and_validate(self, raw_response: str) -> FeatureGraph:
        """
        Parse LLM response and validate as FeatureGraph.
        
        Args:
            raw_response: Raw text from LLM
            
        Returns:
            Validated FeatureGraph
            
        Raises:
            ValueError: If parsing or validation fails
        """
        # Remove markdown code blocks if present
        json_content = raw_response
        if "```" in raw_response:
            match = re.search(r"```(?:json)?\s*(.*?)```", raw_response, re.DOTALL)
            if match:
                json_content = match.group(1).strip()
        
        # Parse JSON
        try:
            graph_dict = json.loads(json_content)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LLM returned invalid JSON: {e}\n"
                f"Content preview: {json_content[:200]}"
            )
        
        # Validate schema with Pydantic
        try:
            return FeatureGraph(**graph_dict)
        except Exception as e:
            raise ValueError(
                f"Invalid FeatureGraph schema: {e}\n"
                f"Data: {graph_dict}"
            )
