"""
LLM Client - Provider-agnostic language model interface.

ONE client, ONE canonical method: generate_feature_graph()
Swap providers (Groq, OpenAI, local) without changing service layer.

Phase 4: Added two-stage pipeline for designer intelligence.
"""
import os
import re
import json
import logging
from groq import AsyncGroq

from typing import Optional
from app.domain.feature_graph_v1 import FeatureGraphV1 as FeatureGraph
from app.domain.execution_trace import ExecutionTrace
from app.llm.prompts import FEATURE_GRAPH_PROMPT, RETRY_PROMPT_TEMPLATE

# Phase 4: Two-stage prompts
from app.llm.prompts_v2 import (
    INTENT_EXTRACTION_SYSTEM_PROMPT,
    INTENT_EXTRACTION_USER_TEMPLATE
)

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM interface for CAD generation.
    
    This is the ONLY LLM client in the system.
    Provider can be swapped without affecting upstream code.
    
    Methods:
        generate_feature_graph(prompt) -> FeatureGraph (original, V1)
        generate_design_intent(prompt) -> DesignIntent (Phase 4 Stage 1)
        generate_from_template(intent) -> FeatureGraphV3 (Phase 4 Stage 2)
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
    
    async def generate_feature_graph(self, user_prompt: str, trace: Optional[ExecutionTrace] = None, intent_context: Optional[dict] = None) -> FeatureGraph:
        """
        Generate FeatureGraph from natural language prompt.
        
        This is the CANONICAL method for LLM-based CAD generation.
        Returns structured data (FeatureGraph), never executable code.
        
        Args:
            user_prompt: User's natural language description
            trace: Optional execution trace for retry context
            intent_context: Optional decomposed intent to constrain generation
            
        Returns:
            FeatureGraph object ready for compilation
            
        Raises:
            ValueError: If JSON parsing or validation fails
            Exception: If LLM call fails
        """
        if self.provider == "groq":
            return await self._generate_groq(user_prompt, trace, intent_context)
        elif self.provider == "openai":
            return await self._generate_openai(user_prompt, trace)
        elif self.provider == "local":
            return await self._generate_local(user_prompt, trace)
    
    async def _generate_groq(self, user_prompt: str, trace: Optional[ExecutionTrace] = None, intent_context: Optional[dict] = None) -> FeatureGraph:
        """
        Generate using Groq provider.
        
        Args:
            user_prompt: User's prompt
            trace: Optional execution trace
            intent_context: Optional decomposed intent
            
        Returns:
            Validated FeatureGraph
        """
        try:
            # Select prompt based on retry status
            if trace:
                system_prompt = RETRY_PROMPT_TEMPLATE.format(
                    execution_trace=trace.model_dump_json(indent=2)
                )
                logger.info("Generating using RETRY prompt")
            else:
                system_prompt = FEATURE_GRAPH_PROMPT

            # Inject Intent Constraints if present
            if intent_context:
                intent_str = json.dumps(intent_context, indent=2)
                system_prompt += f"\n\nSTRICT DECOMPOSED INTENT:\n{intent_str}\n\n"
                system_prompt += "You must ONLY generate features/constraints allowed by the strict intent above."
                
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
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
    
    async def generate_design_intent(self, user_prompt: str):
        """
        Phase 4 Stage 1: Extract design intent from user prompt.
        
        Focuses LLM on engineering reasoning, not topology.
        
        Args:
            user_prompt: User's natural language description
            
        Returns:
            DesignIntent object
        """
        from app.domain.design_intent import DesignIntent
        
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": INTENT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": INTENT_EXTRACTION_USER_TEMPLATE.format(prompt=user_prompt)}
                ],
                temperature=0.2,
                max_tokens=512
            )
            
            raw_response = completion.choices[0].message.content.strip()
            json_content = self._extract_json(raw_response)
            intent_dict = json.loads(json_content)
            
            # Add original prompt
            intent_dict["original_prompt"] = user_prompt
            
            logger.info(f"Extracted intent: part_type={intent_dict.get('part_type')}")
            return DesignIntent(**intent_dict)
            
        except Exception as e:
            logger.error(f"Design intent extraction failed: {e}")
            raise
    
    async def generate_from_template(self, intent):
        """
        Phase 4 Stage 2: Generate FeatureGraph from intent using template.
        
        Templates eliminate topology hallucinations.
        
        Args:
            intent: DesignIntent object
            
        Returns:
            FeatureGraphV3
        """
        from app.templates.parametric_templates import TemplateRegistry
        
        # Select template
        template = TemplateRegistry.select_template(intent)
        if not template:
            raise ValueError(f"No template found for part_type: {intent.part_type}")
        
        # Validate intent has required dimensions
        if not template.validate_intent(intent):
            missing = [d for d in template.required_dimensions() if d not in intent.key_dimensions]
            raise ValueError(
                f"Intent missing required dimensions for {template.name}: {missing}"
            )
        
        # Generate FeatureGraph
        logger.info(f"Generating from template: {template.name}")
        feature_graph = template.generate(intent)
        
        return feature_graph
    
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
        Parse LLM response and validate as FeatureGraph (with auto-repair).
        
        Implements retry logic with auto-repair for common issues:
        - Missing version field
        - Missing optional fields (parameters, metadata)
        - Markdown formatting
        
        Args:
            raw_response: Raw text from LLM
            
        Returns:
            Validated FeatureGraph
            
        Raises:
            ValueError: If parsing or validation fails after repair attempts
        """
        # Remove markdown code blocks if present
        json_content = self._extract_json(raw_response)
        
        # Parse JSON
        try:
            graph_dict = json.loads(json_content)
        except json.JSONDecodeError as e:
            # Try to repair common JSON issues
            repaired_json = self._repair_json(json_content)
            try:
                graph_dict = json.loads(repaired_json)
                logger.info("JSON repaired successfully")
            except json.JSONDecodeError:
                raise ValueError(
                    f"LLM returned invalid JSON (even after repair): {e}\n"
                    f"Content preview: {json_content[:200]}"
                )
        
        # Auto-repair missing fields
        graph_dict = self._auto_repair_graph(graph_dict)
        
        # Validate schema with Pydantic
        try:
            return FeatureGraph(**graph_dict)
        except Exception as e:
            logger.error(f"FeatureGraph validation failed: {e}")
            logger.error(f"Graph data: {graph_dict}")
            raise ValueError(
                f"Invalid FeatureGraph schema: {e}\n"
                f"This may indicate LLM hallucinated invalid structure.\n"
                f"Data: {graph_dict}"
            )
    
    def _extract_json(self, raw_response: str) -> str:
        """
        Extract JSON from LLM response, handling markdown formatting.
        
        Args:
            raw_response: Raw LLM response
            
        Returns:
            Cleaned JSON string
        """
        content = raw_response.strip()
        
        # Remove markdown code blocks
        if "```" in content:
            # Try ```json format
            match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()
        
        # Find JSON object boundaries
        start = content.find('{')
        end = content.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            content = content[start:end+1]
        
        return content
    
    def _repair_json(self, json_str: str) -> str:
        """
        Attempt to repair common JSON formatting issues.
        
        Args:
            json_str: Potentially malformed JSON
            
        Returns:
            Repaired JSON string
        """
        # Remove trailing commas (common LLM mistake)
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # Fix single quotes to double quotes
        json_str = json_str.replace("'", '"')
        
        # Remove comments (LLMs sometimes add them)
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        
        return json_str
    
    def _auto_repair_graph(self, graph_dict: dict) -> dict:
        """
        Auto-repair common FeatureGraph issues (CFG v1).
        
        Adds missing required/optional fields with sensible defaults.
        
        Args:
            graph_dict: Parsed graph dictionary
            
        Returns:
            Repaired graph dictionary
        """
        # Add version if missing
        if 'version' not in graph_dict:
            graph_dict['version'] = 'v1'
            logger.info("Auto-repair: Added missing 'version' field")
        
        # Add units if missing
        if 'units' not in graph_dict:
            graph_dict['units'] = 'mm'
            logger.info("Auto-repair: Added missing 'units' field")
        
        # Add empty parameters if missing
        if 'parameters' not in graph_dict:
            graph_dict['parameters'] = {}
            logger.info("Auto-repair: Added empty 'parameters' dict")
            
        # Add empty sketches if missing
        if 'sketches' not in graph_dict:
            graph_dict['sketches'] = []
            logger.info("Auto-repair: Added empty 'sketches' list")
            
        # Add empty features if missing
        if 'features' not in graph_dict:
            graph_dict['features'] = []
            logger.info("Auto-repair: Added empty 'features' list")
        
        # Add empty metadata if missing
        if 'metadata' not in graph_dict:
            graph_dict['metadata'] = {}
        
        # Repair sketches
        if 'sketches' in graph_dict and isinstance(graph_dict['sketches'], list):
            for sketch in graph_dict['sketches']:
                if 'constraints' not in sketch:
                    sketch['constraints'] = []
                if 'entities' not in sketch:
                    sketch['entities'] = []
        
        # Repair features
        if 'features' in graph_dict and isinstance(graph_dict['features'], list):
            for feature in graph_dict['features']:
                if 'depends_on' not in feature:
                    feature['depends_on'] = []
                # Ensure params exists
                if 'params' not in feature:
                    feature['params'] = {}
        
        return graph_dict
