"""
Tests for Context Engine (VERSION 0.4).

Tests context management, reference resolution, and prompt generation.
"""
import pytest
from datetime import datetime

from app.context.context_engine import ContextEngine, DesignContext
from app.domain.feature_graph_v2 import FeatureGraphV2, FeatureV2, SketchGraphV2, SketchPrimitiveV2


class TestDesignContext:
    """Test DesignContext dataclass."""
    
    def test_create_context(self):
        """Test basic context creation."""
        ctx = DesignContext(
            design_id="design_1",
            session_id="session_1"
        )
        
        assert ctx.design_id == "design_1"
        assert ctx.session_id == "session_1"
        assert ctx.feature_graph is None
        assert ctx.conversation == []
        assert ctx.feature_history == []
        assert ctx.current_parameters == {}
    
    def test_context_default_values(self):
        """Test default values are properly initialized."""
        ctx = DesignContext(design_id="d1", session_id="s1")
        
        assert isinstance(ctx.created_at, datetime)
        assert ctx.last_feature_id is None
        assert ctx.last_topology_refs == {}


class TestContextEngine:
    """Test ContextEngine class."""
    
    @pytest.fixture
    def engine(self):
        """Create fresh context engine."""
        return ContextEngine()
    
    def test_create_and_get_context(self, engine):
        """Test context creation and retrieval."""
        ctx = engine.create_context("design_1", "session_1")
        
        assert ctx is not None
        assert ctx.design_id == "design_1"
        
        # Retrieve
        retrieved = engine.get_context("session_1")
        assert retrieved is ctx
    
    def test_get_nonexistent_context(self, engine):
        """Test getting context that doesn't exist."""
        ctx = engine.get_context("nonexistent")
        assert ctx is None
    
    def test_get_or_create_context(self, engine):
        """Test get_or_create behavior."""
        # First call creates
        ctx1 = engine.get_or_create_context("session_1", "design_1")
        assert ctx1 is not None
        
        # Second call returns existing
        ctx2 = engine.get_or_create_context("session_1")
        assert ctx2 is ctx1


class TestConversationHistory:
    """Test conversation tracking."""
    
    @pytest.fixture
    def engine_with_context(self):
        """Create engine with active context."""
        engine = ContextEngine()
        engine.create_context("design_1", "session_1")
        return engine
    
    def test_add_conversation_turn(self, engine_with_context):
        """Test adding conversation messages."""
        engine_with_context.add_conversation_turn(
            "session_1", "user", "Create a box 30x20x10"
        )
        
        ctx = engine_with_context.get_context("session_1")
        assert len(ctx.conversation) == 1
        assert ctx.conversation[0]["role"] == "user"
        assert ctx.conversation[0]["content"] == "Create a box 30x20x10"
    
    def test_multiple_turns(self, engine_with_context):
        """Test multiple conversation turns."""
        engine_with_context.add_conversation_turn(
            "session_1", "user", "Create a box"
        )
        engine_with_context.add_conversation_turn(
            "session_1", "assistant", "Created box feature"
        )
        engine_with_context.add_conversation_turn(
            "session_1", "user", "Make it taller"
        )
        
        ctx = engine_with_context.get_context("session_1")
        assert len(ctx.conversation) == 3


class TestReferenceResolution:
    """Test reference resolution for natural language."""
    
    @pytest.fixture
    def engine_with_history(self):
        """Create engine with feature history."""
        engine = ContextEngine()
        ctx = engine.create_context("design_1", "session_1")
        
        # Add a mock feature graph with features
        ctx.feature_graph = FeatureGraphV2(
            version="2.0",
            sketches=[],
            features=[
                FeatureV2(id="f1", type="extrude", params={"depth": 10}),
                FeatureV2(id="f2", type="fillet", params={"radius": 2}),
                FeatureV2(id="f3", type="extrude", params={"depth": 5}),
            ]
        )
        
        # Add feature history
        ctx.feature_history = [
            {"feature_id": "f1", "timestamp": "2026-01-15T10:00:00"},
            {"feature_id": "f2", "timestamp": "2026-01-15T10:01:00"},
            {"feature_id": "f3", "timestamp": "2026-01-15T10:02:00"},
        ]
        
        # Set last topology refs
        ctx.last_topology_refs = {
            "edges": [">Z", "parallel_X"],
            "faces": [">Z"]
        }
        
        return engine
    
    def test_resolve_that_edge(self, engine_with_history):
        """Test 'that edge' resolution."""
        result = engine_with_history.resolve_reference(
            "session_1", "fillet that edge"
        )
        
        assert result is not None
        assert result["type"] == "topology"
        assert result["topology_type"] == "edge"
        assert ">Z" in result["refs"]
    
    def test_resolve_previous_extrusion(self, engine_with_history):
        """Test 'previous extrusion' resolution."""
        result = engine_with_history.resolve_reference(
            "session_1", "modify the previous extrusion"
        )
        
        assert result is not None
        assert result["type"] == "feature"
        assert result["feature_id"] == "f3"  # Last extrude
    
    def test_resolve_last_feature(self, engine_with_history):
        """Test 'last feature' resolution."""
        result = engine_with_history.resolve_reference(
            "session_1", "undo the last feature"
        )
        
        assert result is not None
        assert result["type"] == "feature"
        assert result["feature_id"] == "f3"
    
    def test_resolve_make_taller(self, engine_with_history):
        """Test 'make it taller' resolution."""
        result = engine_with_history.resolve_reference(
            "session_1", "make it taller"
        )
        
        assert result is not None
        assert result["type"] == "parameter"
        assert result["param"] == "height"
        assert result["action"] == "increase"
    
    def test_resolve_make_wider(self, engine_with_history):
        """Test 'make it wider' resolution."""
        result = engine_with_history.resolve_reference(
            "session_1", "make the box wider"
        )
        
        assert result is not None
        assert result["type"] == "parameter"
        assert result["param"] == "width"
        assert result["action"] == "increase"
    
    def test_resolve_unknown_reference(self, engine_with_history):
        """Test unknown reference returns None."""
        result = engine_with_history.resolve_reference(
            "session_1", "something completely unrelated"
        )
        
        assert result is None


class TestContextPromptGeneration:
    """Test context prompt generation for LLM."""
    
    @pytest.fixture
    def engine_with_full_context(self):
        """Create engine with complete context."""
        engine = ContextEngine()
        ctx = engine.create_context("design_1", "session_1")
        
        # Add conversation
        ctx.conversation = [
            {"role": "user", "content": "Create a box", "timestamp": "2026-01-15T10:00:00"},
            {"role": "assistant", "content": "Created box", "timestamp": "2026-01-15T10:00:01"},
        ]
        
        # Add parameters
        ctx.current_parameters = {
            "width": 30,
            "height": 20,
            "depth": 10
        }
        
        # Add feature history
        ctx.feature_history = [
            {"feature_id": "extrude_1", "timestamp": "2026-01-15T10:00:00"},
        ]
        
        return engine
    
    def test_generate_context_prompt(self, engine_with_full_context):
        """Test context prompt generation."""
        prompt = engine_with_full_context.generate_context_prompt("session_1")
        
        assert "Recent Conversation" in prompt
        assert "Create a box" in prompt
        assert "Current Design Parameters" in prompt
        assert "width: 30" in prompt
        assert "Recent Features" in prompt
        assert "extrude_1" in prompt
    
    def test_empty_context_prompt(self):
        """Test prompt for empty context."""
        engine = ContextEngine()
        engine.create_context("d1", "s1")
        
        prompt = engine.generate_context_prompt("s1")
        assert prompt == ""  # No content to include


class TestParameterExtraction:
    """Test parameter extraction from feature graph."""
    
    def test_extract_parameters(self):
        """Test parameter extraction."""
        engine = ContextEngine()
        ctx = engine.create_context("design_1", "session_1")
        
        ctx.feature_graph = FeatureGraphV2(
            version="2.0",
            parameters={
                "width": {"type": "float", "value": 30},
                "height": {"type": "float", "value": 20},
            },
            sketches=[],
            features=[]
        )
        
        params = engine.extract_parameters("session_1")
        
        assert params["width"] == 30
        assert params["height"] == 20
        assert ctx.current_parameters == params


class TestContextClearing:
    """Test context clearing."""
    
    def test_clear_context(self):
        """Test context deletion."""
        engine = ContextEngine()
        engine.create_context("d1", "s1")
        
        assert engine.get_context("s1") is not None
        
        result = engine.clear_context("s1")
        
        assert result is True
        assert engine.get_context("s1") is None
    
    def test_clear_nonexistent_context(self):
        """Test clearing context that doesn't exist."""
        engine = ContextEngine()
        result = engine.clear_context("nonexistent")
        assert result is False
