"""
Conversational Edit Service - Natural language CAD modifications for CFG v1.

Enables users to modify existing designs with prompts like:
- "Make it taller"
- "Increase hole diameter to 8mm"
- "Add fillet of 2mm to the top edge"

Architecture:
    (existing_graph, edit_prompt) → LLM → Modified FeatureGraph → Recompile
"""
import logging
import json
import re
from typing import Optional, Dict, Any, List
from app.domain.feature_graph import FeatureGraph, Feature, Sketch
from app.llm import LLMClient

logger = logging.getLogger(__name__)


# Template for editing prompts - strictly enforces CFG v1 schema
EDIT_PROMPT_TEMPLATE = """You are an expert CAD editing assistant.
Your task is to MODIFY an existing Canonical Feature Graph (CFG) based on a user's request.

⚠️ CRITICAL RULES:
1. PRESERVE existing structure: Do NOT regenerate the graph from scratch.
2. MODIFY ONLY what is requested: Change parameters, add/remove features, but strictly keep the rest.
3. MAINTAIN VALIDITY: Ensure all IDs are unique and dependencies (depends_on) point to existing IDs.
4. OUTPUT: Return the COMPLETE, valid JSON of the modified FeatureGraph.

═════════════════════════════════════════════════════════════════════

CURRENT DESIGN (JSON):
{current_graph}

USER EDIT REQUEST:
"{edit_request}"

═════════════════════════════════════════════════════════════════════

GUIDANCE FOR EDITS:

1. Parameter Change ("Make it taller"):
   - Locate the relevant parameter (e.g., "height", "length").
   - Update its value in "parameters" dict.
   
2. Feature Addition ("Add a fillet"):
   - Add a new feature object to the "features" list.
   - Type: "fillet" or "chamfer".
   - Params: {"radius": value} or {"distance": value}.
   - Depends On: Check the last feature ID in the list and set it as dependency.

3. Feature Removal ("Remove the chamfer"):
   - Remove the feature object from the list.
   - Update any downstream dependencies to point to the removed feature's parent.

═════════════════════════════════════════════════════════════════════

OUTPUT THE COMPLETE MODIFIED FEATUREGRAPH AS JSON (NO MARKDOWN).
"""


class ConversationalEditor:
    """
    Enables natural language editing of CFG v1.
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize conversational editor.
        
        Args:
            llm_client: LLM client for edit interpretation
        """
        self.llm_client = llm_client or LLMClient()
    
    async def apply_edit(
        self,
        current_graph: FeatureGraph,
        edit_request: str
    ) -> FeatureGraph:
        """
        Apply conversational edit to existing FeatureGraph.
        
        Args:
            current_graph: Existing FeatureGraph
            edit_request: User's natural language edit request
            
        Returns:
            Modified FeatureGraph
            
        Raises:
            ValueError: If edit cannot be interpreted
        """
        logger.info(f"Applying conversational edit: '{edit_request}'")
        
        # 1. Try heuristics first (fast, reliable for simple param changes)
        simple_edit = self._try_heuristic_edit(current_graph, edit_request)
        if simple_edit:
            logger.info("Applied heuristic parameter edit")
            return simple_edit
        
        # 2. Fall back to LLM for structural/complex edits
        return await self._llm_based_edit(current_graph, edit_request)
    
    def _try_heuristic_edit(
        self,
        graph: FeatureGraph,
        request: str
    ) -> Optional[FeatureGraph]:
        """
        Attempt simple parameter edit without LLM.
        
        Matches patterns like:
        - "set length to 100"
        - "width = 50mm"
        - "change radius to 10"
        """
        request = request.lower().strip()
        
        # Regex for "param = value" or "set param to value"
        # Captures: 1=name, 2=value
        patterns = [
            r'set\s+(\w+)\s+to\s+([\d.]+)',  # set len to 10
            r'(\w+)\s*=\s*([\d.]+)',         # len = 10
            r'change\s+(\w+)\s+to\s+([\d.]+)', # change len to 10
            r'make\s+(\w+)\s+([\d.]+)'       # make len 10
        ]
        
        for pattern in patterns:
            match = re.search(pattern, request)
            if match:
                param_name = match.group(1)
                try:
                    value = float(match.group(2))
                except ValueError:
                    continue
                
                # Check fuzzy match against existing params
                # If exact match exists, update it
                if param_name in graph.parameters:
                    graph.parameters[param_name] = value
                    return graph
                    
                # If not exact, try partial match (e.g. "len" -> "length")
                # Simple exact match for now to be safe
        
        return None
    
    async def _llm_based_edit(
        self,
        current_graph: FeatureGraph,
        edit_request: str
    ) -> FeatureGraph:
        """
        Use LLM to interpret and apply complex edit.
        """
        # Serialize current graph to JSON
        current_json = current_graph.model_dump_json(indent=2)
        
        # Create edit prompt
        prompt = EDIT_PROMPT_TEMPLATE.format(
            current_graph=current_json,
            edit_request=edit_request
        )
        
        try:
            # Call LLM (using the generic client but with our custom prompt logic)
            # We bypass the specific 'generate_feature_graph' helper because we
            # want to send a different system prompt for EDITING.
            # Assuming LLMClient exposes a raw generate method or we can reuse `_generate_groq`
            # But `generate_feature_graph` relies on `FEATURE_GRAPH_PROMPT`
            
            # Implementation detail: We'll construct a new prompt and ask LLMClient to parse it
            # Or use the internal client directly if accessible. 
            # Ideally LLMClient should have `edit_feature_graph` method.
            # Since I cannot modify LLMClient interface essentially in this step without
            # revisiting previous files, I will use a workaround or use the prompt directly if client allows.
            
            # Let's import AsyncGroq directly here to keep logic contained, 
            # or better, add `edit_feature_graph` to LLMClient in future refactor.
            # For now, I'll access the client's internal client (hacky but effective)
            
            from groq import AsyncGroq
            if hasattr(self.llm_client, "client") and isinstance(self.llm_client.client, AsyncGroq):
                 response = await self.llm_client.client.chat.completions.create(
                    model=self.llm_client.model,
                    messages=[
                        {"role": "user", "content": prompt} # Prompt contains system instructions effectively
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                    response_format={"type": "json_object"}
                )
                 raw_text = response.choices[0].message.content
            else:
                raise NotImplementedError("Only Groq supported for edits currently")

            # Parse and validate using the client's robust parser
            # This ensures auto-repair and schema validation apply
            edited_graph = self.llm_client._parse_and_validate(raw_text)
            
            return edited_graph
            
        except Exception as e:
            logger.error(f"LLM edit failed: {e}")
            raise ValueError(f"Could not apply edit: {e}") from e
