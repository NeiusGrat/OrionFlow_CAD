"""
Topological Identity System - Phase 2

Provides stable identity tracking for CAD topology entities (edges, faces, vertices).
Eliminates geometric guessing by tagging entities at creation time.

Key Concepts:
- EntityIdentity: Metadata attached to each edge/face/vertex
- EntityRegistry: Lookup table mapping UUIDs to geometry
- Resolution Order: ID → Feature → Role → Geometric fallback
"""
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from uuid import uuid4


class EntityIdentity(BaseModel):
    """
    Metadata attached to topology entities at creation time.
    
    This makes semantic selection deterministic and regeneration-safe.
    
    Attributes:
        id: Unique identifier for this entity (UUID)
        created_by: Feature ID that created this entity
        role: Semantic tag (e.g., "top_edge", "bottom_face")
        axis: Orientation hint (X, Y, or Z)
        primitive_ref: Source sketch primitive ID (if applicable)
        feature_type: Type of feature that created this (extrude, fillet, etc.)
    
    Example:
        ```python
        edge_metadata = EntityIdentity(
            id="edge_a3f2b1",
            created_by="extrude_1",
            role="top_edge",
            axis="Z"
        )
        ```
    """
    id: str = Field(default_factory=lambda: f"entity_{uuid4().hex[:8]}")
    created_by: str = Field(..., description="Feature ID that created this entity")
    role: Optional[str] = Field(None, description="Semantic tag: 'top_edge', 'side_face', etc.")
    axis: Optional[Literal["X", "Y", "Z"]] = Field(None, description="Primary orientation")
    primitive_ref: Optional[str] = Field(None, description="Source sketch primitive ID")
    feature_type: Optional[str] = Field(None, description="Type of creating feature")
    
    # Additional metadata for advanced use cases
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")
    
    class Config:
        extra = "allow"  # Allow future extensions


class EntityRegistry(BaseModel):
    """
    Lookup table for topology entities created during compilation.
    
    Maps entity UUIDs to their metadata. The actual geometry references
    are stored separately in the compiler context.
    
    Attributes:
        entities: Map of entity_id -> EntityIdentity
        feature_map: Reverse index: feature_id -> [entity_id, ...]
        role_map: Reverse index: role -> [entity_id, ...]
    """
    entities: Dict[str, EntityIdentity] = Field(default_factory=dict)
    feature_map: Dict[str, list[str]] = Field(default_factory=dict)
    role_map: Dict[str, list[str]] = Field(default_factory=dict)
    
    def register(self, identity: EntityIdentity) -> str:
        """
        Register a new entity and update reverse indexes.
        
        Args:
            identity: EntityIdentity to register
            
        Returns:
            The entity ID
        """
        eid = identity.id
        self.entities[eid] = identity
        
        # Update feature_map
        if identity.created_by:
            if identity.created_by not in self.feature_map:
                self.feature_map[identity.created_by] = []
            self.feature_map[identity.created_by].append(eid)
        
        # Update role_map
        if identity.role:
            if identity.role not in self.role_map:
                self.role_map[identity.role] = []
            self.role_map[identity.role].append(eid)
        
        return eid
    
    def get_by_feature(self, feature_id: str) -> list[EntityIdentity]:
        """Get all entities created by a specific feature."""
        entity_ids = self.feature_map.get(feature_id, [])
        return [self.entities[eid] for eid in entity_ids if eid in self.entities]
    
    def get_by_role(self, role: str) -> list[EntityIdentity]:
        """Get all entities with a specific semantic role."""
        entity_ids = self.role_map.get(role, [])
        return [self.entities[eid] for eid in entity_ids if eid in self.entities]
    
    def get(self, entity_id: str) -> Optional[EntityIdentity]:
        """Get entity metadata by ID."""
        return self.entities.get(entity_id)


def infer_edge_role(edge, feature_type: str, feature_params: dict) -> Optional[str]:
    """
    Infer semantic role for an edge based on its geometry and creating feature.
    
    This provides default tagging when explicit roles aren't specified.
    
    Args:
        edge: build123d Edge object
        feature_type: Type of feature (extrude, fillet, etc.)
        feature_params: Feature parameters
        
    Returns:
        Inferred role string or None
    """
    try:
        center = edge.center()
        
        if feature_type == "extrude":
            # Try to determine if edge is top, bottom, or side
            # This is heuristic but better than nothing
            edges = edge.parent.edges() if hasattr(edge, 'parent') else []
            if edges:
                z_positions = [e.center().Z for e in edges]
                max_z = max(z_positions)
                min_z = min(z_positions)
                
                if abs(center.Z - max_z) < 0.01:
                    return "top_edge"
                elif abs(center.Z - min_z) < 0.01:
                    return "bottom_edge"
                else:
                    return "side_edge"
        
        elif feature_type in ["fillet", "chamfer"]:
            return f"{feature_type}_edge"
        
    except Exception:
        pass
    
    return None


def infer_edge_axis(edge) -> Optional[Literal["X", "Y", "Z"]]:
    """
    Infer primary axis orientation for an edge.
    
    Args:
        edge: build123d Edge object
        
    Returns:
        Primary axis ("X", "Y", or "Z") or None
    """
    try:
        tangent = edge.tangent_at(0)
        
        # Determine dominant direction
        abs_x = abs(tangent.X)
        abs_y = abs(tangent.Y)
        abs_z = abs(tangent.Z)
        
        max_component = max(abs_x, abs_y, abs_z)
        
        if abs_x == max_component and abs_x > 0.9:
            return "X"
        elif abs_y == max_component and abs_y > 0.9:
            return "Y"
        elif abs_z == max_component and abs_z > 0.9:
            return "Z"
    
    except Exception:
        pass
    
    return None
