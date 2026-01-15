"""
Context Engine - Manages design context for conversational editing.

VERSION 0.4: Context-aware conversation system enabling:
- "that edge" → last referenced topology
- "make it taller" → modify correct parameter
- "previous extrusion" → find last extrude feature

Key components:
- DesignContext: Session state (feature graph, conversation, parameters)
- ContextEngine: Context management and reference resolution
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class DesignContext:
    """
    Maintains context for a single design session.
    
    Tracks:
    - Design state (current feature graph)
    - Conversation history
    - Active references (last mentioned topology)
    - Parameter values
    """
    
    # Identity
    design_id: str
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    
    # Design state
    feature_graph: Optional[Any] = None  # Current FeatureGraph (V1 or V2)
    feature_history: List[Dict] = field(default_factory=list)  # Chronological feature log
    
    # Conversation
    conversation: List[Dict] = field(default_factory=list)  # [{role, content, timestamp}]
    
    # Active references (for "that edge", "this face" resolution)
    last_feature_id: Optional[str] = None
    last_topology_refs: Dict[str, List] = field(default_factory=dict)  # {edges: [...], faces: [...]}
    
    # Parameters
    current_parameters: Dict[str, float] = field(default_factory=dict)  # {width: 30, height: 20}
    parameter_history: List[Dict] = field(default_factory=list)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextEngine:
    """
    Manages design contexts for conversational editing.
    
    Features:
    - Create/retrieve session contexts
    - Track conversation and feature history
    - Resolve natural language references
    - Generate context prompts for LLM
    """
    
    def __init__(self):
        """Initialize the context engine."""
        self.contexts: Dict[str, DesignContext] = {}
        logger.info("ContextEngine initialized")
    
    def create_context(self, design_id: str, session_id: str) -> DesignContext:
        """
        Create a new design context for a session.
        
        Args:
            design_id: Unique design identifier
            session_id: Session/conversation identifier
            
        Returns:
            New DesignContext instance
        """
        ctx = DesignContext(design_id=design_id, session_id=session_id)
        self.contexts[session_id] = ctx
        logger.info(f"Created context for session={session_id}, design={design_id}")
        return ctx
    
    def get_context(self, session_id: str) -> Optional[DesignContext]:
        """Retrieve context for session."""
        return self.contexts.get(session_id)
    
    def get_or_create_context(
        self,
        session_id: str,
        design_id: Optional[str] = None
    ) -> DesignContext:
        """Get existing context or create new one."""
        ctx = self.get_context(session_id)
        if ctx is None:
            ctx = self.create_context(
                design_id=design_id or session_id,
                session_id=session_id
            )
        return ctx
    
    def add_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> None:
        """
        Add message to conversation history.
        
        Args:
            session_id: Session identifier
            role: "user" or "assistant"
            content: Message content
        """
        ctx = self.get_context(session_id)
        if ctx:
            ctx.conversation.append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            })
    
    def update_feature_graph(
        self,
        session_id: str,
        feature_graph: Any,
        new_features: Optional[List[str]] = None
    ) -> None:
        """
        Update design state with new/modified feature graph.
        
        Args:
            session_id: Session identifier
            feature_graph: The updated FeatureGraph
            new_features: List of newly added feature IDs
        """
        ctx = self.get_context(session_id)
        if not ctx:
            return
        
        ctx.feature_graph = feature_graph
        
        if new_features:
            ctx.last_feature_id = new_features[-1]
            
            # Add to history
            for feature_id in new_features:
                ctx.feature_history.append({
                    "feature_id": feature_id,
                    "timestamp": datetime.now().isoformat()
                })
    
    def set_topology_refs(
        self,
        session_id: str,
        edges: Optional[List[str]] = None,
        faces: Optional[List[str]] = None
    ) -> None:
        """
        Set last referenced topology for "that edge" resolution.
        
        Args:
            session_id: Session identifier
            edges: Edge identifiers/selectors
            faces: Face identifiers/selectors
        """
        ctx = self.get_context(session_id)
        if ctx:
            ctx.last_topology_refs = {
                "edges": edges or [],
                "faces": faces or []
            }
    
    def resolve_reference(
        self,
        session_id: str,
        reference: str
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve conversational references to concrete entities.
        
        Examples:
        - "that edge" → {"type": "topology", "edges": [...]}
        - "previous extrusion" → {"type": "feature", "feature_id": "f1"}
        - "the box" → {"type": "feature", "feature_id": "extrude_box"}
        - "make it taller" → {"type": "parameter", "param": "height", "action": "increase"}
        
        Args:
            session_id: Session identifier
            reference: The natural language reference
            
        Returns:
            Dict with resolution type and details, or None
        """
        ctx = self.get_context(session_id)
        if not ctx:
            return None
        
        ref_lower = reference.lower()
        
        # Demonstrative references ("that", "this", "these")
        if any(word in ref_lower for word in ["that edge", "this edge", "these edges"]):
            if ctx.last_topology_refs.get("edges"):
                return {
                    "type": "topology",
                    "topology_type": "edge",
                    "refs": ctx.last_topology_refs["edges"],
                    "source": "last_reference"
                }
        
        if any(word in ref_lower for word in ["that face", "this face", "these faces"]):
            if ctx.last_topology_refs.get("faces"):
                return {
                    "type": "topology",
                    "topology_type": "face",
                    "refs": ctx.last_topology_refs["faces"],
                    "source": "last_reference"
                }
        
        # Temporal references ("previous", "last")
        if any(word in ref_lower for word in ["previous", "last"]):
            if "extrude" in ref_lower or "extrusion" in ref_lower:
                feat = self._find_last_feature_of_type(ctx, "extrude")
                if feat:
                    return {"type": "feature", "feature_id": feat, "source": "history"}
            
            if "fillet" in ref_lower:
                feat = self._find_last_feature_of_type(ctx, "fillet")
                if feat:
                    return {"type": "feature", "feature_id": feat, "source": "history"}
            
            if "feature" in ref_lower:
                if ctx.feature_history:
                    return {
                        "type": "feature",
                        "feature_id": ctx.feature_history[-1]["feature_id"],
                        "source": "history"
                    }
        
        # Parameter modification references
        param_actions = {
            "taller": ("height", "increase"),
            "shorter": ("height", "decrease"),
            "wider": ("width", "increase"),
            "narrower": ("width", "decrease"),
            "deeper": ("depth", "increase"),
            "shallower": ("depth", "decrease"),
            "bigger": ("scale", "increase"),
            "smaller": ("scale", "decrease"),
            "thicker": ("thickness", "increase"),
            "thinner": ("thickness", "decrease"),
        }
        
        for word, (param, action) in param_actions.items():
            if word in ref_lower:
                return {
                    "type": "parameter",
                    "param": param,
                    "action": action,
                    "source": "semantic"
                }
        
        return None
    
    def _find_last_feature_of_type(
        self,
        ctx: DesignContext,
        feature_type: str
    ) -> Optional[str]:
        """Find the last feature of a specific type in history."""
        if not ctx.feature_graph:
            return None
        
        # Get features from graph
        features = getattr(ctx.feature_graph, "features", [])
        
        # Search in reverse order
        for feat in reversed(features):
            if getattr(feat, "type", None) == feature_type:
                return getattr(feat, "id", None)
        
        return None
    
    def extract_parameters(self, session_id: str) -> Dict[str, float]:
        """
        Extract current parameter values from feature graph.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict of parameter name → value
        """
        ctx = self.get_context(session_id)
        if not ctx or not ctx.feature_graph:
            return {}
        
        params = {}
        fg = ctx.feature_graph
        
        # Extract from parameters table
        if hasattr(fg, "parameters"):
            for key, value in fg.parameters.items():
                if isinstance(value, dict) and "value" in value:
                    params[key] = value["value"]
                elif isinstance(value, (int, float)):
                    params[key] = value
        
        ctx.current_parameters = params
        return params
    
    def generate_context_prompt(self, session_id: str) -> str:
        """
        Generate context section for LLM prompt.
        
        Includes recent conversation, current parameters, and feature history.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Formatted context string for LLM
        """
        ctx = self.get_context(session_id)
        if not ctx:
            return ""
        
        parts = []
        
        # Recent conversation (last 5 messages)
        if ctx.conversation:
            parts.append("## Recent Conversation")
            for msg in ctx.conversation[-5:]:
                role = msg["role"].upper()
                content = msg["content"][:100]  # Truncate long messages
                parts.append(f"[{role}]: {content}")
        
        # Current parameters
        if ctx.current_parameters:
            parts.append("\n## Current Design Parameters")
            for key, value in list(ctx.current_parameters.items())[:10]:
                parts.append(f"- {key}: {value}")
        
        # Feature history (last 3)
        if ctx.feature_history:
            parts.append("\n## Recent Features")
            for entry in ctx.feature_history[-3:]:
                parts.append(f"- {entry['feature_id']}")
        
        # Last referenced topology
        if ctx.last_topology_refs.get("edges") or ctx.last_topology_refs.get("faces"):
            parts.append("\n## Active References")
            if ctx.last_topology_refs.get("edges"):
                parts.append(f"- Last edges: {ctx.last_topology_refs['edges']}")
            if ctx.last_topology_refs.get("faces"):
                parts.append(f"- Last faces: {ctx.last_topology_refs['faces']}")
        
        return "\n".join(parts)
    
    def clear_context(self, session_id: str) -> bool:
        """
        Clear/delete context for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if context was removed
        """
        if session_id in self.contexts:
            del self.contexts[session_id]
            logger.info(f"Cleared context for session={session_id}")
            return True
        return False
