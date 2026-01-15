"""
FeatureGraph Versioning - Phase 6

Git-like version control for CAD designs.

Features:
- Diff algorithm (detect changes between versions)
- Delta storage (only store what changed)
- Undo/redo/branch support
- Commit messages and metadata

Example:
    # Commit current design
    version_mgr.commit(graph, message="Added reinforcement ribs")
    
    # Undo last change
    previous = version_mgr.undo()
    
    # Create variant branch
    variant = version_mgr.create_branch("lightweight_version")
"""
from typing import Optional, List, Tuple, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from app.domain.feature_graph_v3 import FeatureGraphV3


class FeatureGraphDiff(BaseModel):
    """
    Delta between two FeatureGraph versions.
    
    Similar to git diff, but for CAD graph structure.
    """
    # Feature changes
    added_features: List[str] = Field(
        default_factory=list,
        description="IDs of features added"
    )
    removed_features: List[str] = Field(
        default_factory=list,
        description="IDs of features removed"
    )
    modified_features: Dict[str, Dict[str, Tuple[Any, Any]]] = Field(
        default_factory=dict,
        description="feature_id → {param: (old_val, new_val)}"
    )
    
    # Parameter changes
    modified_parameters: Dict[str, Tuple[Any, Any]] = Field(
        default_factory=dict,
        description="param_name → (old_val, new_val)"
    )
    
    # Sketch changes
    added_sketches: List[str] = []
    removed_sketches: List[str] = []
    
    def apply(self, base_graph: FeatureGraphV3) -> FeatureGraphV3:
        """
        Apply diff to base graph to create new version.
        
        Args:
            base_graph: Starting FeatureGraph
            
        Returns:
            New FeatureGraph with changes applied
        """
        # Create copy
        new_graph = base_graph.model_copy(deep=True)
        
        # Apply parameter changes
        for param, (old_val, new_val) in self.modified_parameters.items():
            new_graph.parameters[param] = new_val
        
        # Apply feature changes
        for feature_id in self.removed_features:
            new_graph.features = [
                f for f in new_graph.features if f.id != feature_id
            ]
        
        # Feature modifications
        for feature_id, param_changes in self.modified_features.items():
            for feature in new_graph.features:
                if feature.id == feature_id:
                    for param, (old_val, new_val) in param_changes.items():
                        feature.params[param] = new_val
        
        return new_graph
    
    def is_empty(self) -> bool:
        """Check if diff has any changes."""
        return not any([
            self.added_features,
            self.removed_features,
            self.modified_features,
            self.modified_parameters,
            self.added_sketches,
            self.removed_sketches
        ])


class FeatureGraphVersion(BaseModel):
    """
    Versioned snapshot of a FeatureGraph.
    
    Stores full graph + metadata (commit message, timestamp, author).
    """
    id: str = Field(..., description="Version ID (SHA-like hash)")
    parent_id: Optional[str] = Field(None, description="Parent version ID")
    graph: FeatureGraphV3 = Field(..., description="Full FeatureGraph at this version")
    diff: Optional[FeatureGraphDiff] = Field(None, description="Delta from parent")
    
    # Metadata
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    message: str = Field(..., description="Commit message")
    author: str = Field(default="user", description="Who made this change")
    branch: str = Field(default="main", description="Branch name")
    tags: List[str] = Field(default_factory=list, description="Version tags: v1.0, production, etc.")


class VersionManager:
    """
    Manage FeatureGraph version history.
    
    Similar to git for CAD designs.
    """
    
    def __init__(self):
        self.versions: Dict[str, FeatureGraphVersion] = {}
        self.current_version_id: Optional[str] = None
        self.branches: Dict[str, str] = {"main": None}  # branch → latest version_id
    
    def commit(
        self,
        graph: FeatureGraphV3,
        message: str,
        author: str = "user",
        branch: str = "main"
    ) -> FeatureGraphVersion:
        """
        Commit new version of FeatureGraph.
        
        Args:
            graph: Current FeatureGraph
            message: Commit message
            author: Author name
            branch: Branch name
            
        Returns:
            New FeatureGraphVersion
        """
        # Compute diff from parent
        parent_id = self.current_version_id
        diff = None
        
        if parent_id and parent_id in self.versions:
            parent_graph = self.versions[parent_id].graph
            diff = self._compute_diff(parent_graph, graph)
        
        # Generate version ID (simple hash for now)
        version_id = self._generate_version_id(graph, message)
        
        # Create version
        version = FeatureGraphVersion(
            id=version_id,
            parent_id=parent_id,
            graph=graph,
            diff=diff,
            message=message,
            author=author,
            branch=branch
        )
        
        # Store
        self.versions[version_id] = version
        self.current_version_id = version_id
        self.branches[branch] = version_id
        
        return version
    
    def undo(self) -> Optional[FeatureGraphV3]:
        """
        Undo to previous version.
        
        Returns:
            Previous FeatureGraph or None if at root
        """
        if not self.current_version_id:
            return None
        
        current = self.versions[self.current_version_id]
        if not current.parent_id:
            return None  # At root
        
        parent = self.versions[current.parent_id]
        self.current_version_id = parent.id
        
        return parent.graph
    
    def redo(self) -> Optional[FeatureGraphV3]:
        """
        Redo (move forward in history).
        
        Note: Simplified - real redo needs to track forward pointers.
        """
        # Find child of current version
        if not self.current_version_id:
            return None
        
        for version_id, version in self.versions.items():
            if version.parent_id == self.current_version_id:
                self.current_version_id = version_id
                return version.graph
        
        return None  # No child found
    
    def create_branch(
        self,
        branch_name: str,
        from_version_id: Optional[str] = None
    ) -> str:
        """
        Create new branch from version.
        
        Args:
            branch_name: New branch name
            from_version_id: Starting point (defaults to current)
            
        Returns:
            New branch name
        """
        if branch_name in self.branches:
            raise ValueError(f"Branch '{branch_name}' already exists")
        
        start_version = from_version_id or self.current_version_id
        self.branches[branch_name] = start_version
        
        return branch_name
    
    def diff(
        self,
        version_a_id: str,
        version_b_id: str
    ) -> FeatureGraphDiff:
        """
        Compute diff between two versions.
        
        Args:
            version_a_id: Base version
            version_b_id: Comparison version
            
        Returns:
            FeatureGraphDiff
        """
        graph_a = self.versions[version_a_id].graph
        graph_b = self.versions[version_b_id].graph
        
        return self._compute_diff(graph_a, graph_b)
    
    def get_history(self, branch: str = "main", limit: int = 10) -> List[FeatureGraphVersion]:
        """
        Get commit history for branch.
        
        Args:
            branch: Branch name
            limit: Max commits to return
            
        Returns:
            List of versions in reverse chronological order
        """
        if branch not in self.branches:
            return []
        
        history = []
        current_id = self.branches[branch]
        
        while current_id and len(history) < limit:
            version = self.versions.get(current_id)
            if not version:
                break
            
            history.append(version)
            current_id = version.parent_id
        
        return history
    
    def _compute_diff(
        self,
        graph_a: FeatureGraphV3,
        graph_b: FeatureGraphV3
    ) -> FeatureGraphDiff:
        """Compute delta between two graphs."""
        diff = FeatureGraphDiff()
        
        # Compare parameters
        for param, val_b in graph_b.parameters.items():
            val_a = graph_a.parameters.get(param)
            if val_a != val_b:
                diff.modified_parameters[param] = (val_a, val_b)
        
        # Compare features
        features_a = {f.id: f for f in graph_a.features}
        features_b = {f.id: f for f in graph_b.features}
        
        # Added features
        diff.added_features = [
            fid for fid in features_b if fid not in features_a
        ]
        
        # Removed features
        diff.removed_features = [
            fid for fid in features_a if fid not in features_b
        ]
        
        # Modified features
        for fid in features_a:
            if fid in features_b:
                feat_a = features_a[fid]
                feat_b = features_b[fid]
                
                param_changes = {}
                for param, val_b in feat_b.params.items():
                    val_a = feat_a.params.get(param)
                    if val_a != val_b:
                        param_changes[param] = (val_a, val_b)
                
                if param_changes:
                    diff.modified_features[fid] = param_changes
        
        return diff
    
    def _generate_version_id(self, graph: FeatureGraphV3, message: str) -> str:
        """Generate unique version ID (simplified hash)."""
        import hashlib
        content = f"{graph.model_dump_json()}{message}{datetime.utcnow().isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]
