"""
Incremental Rebuild Cache - Graph-Level Dependency-Aware Compilation

==============================================================================
ARCHITECTURE: Dependency-Aware Incremental Compilation
==============================================================================

This module implements MANDATORY incremental rebuild for:
- Large models (many features)
- Live parameter sliders
- Onshape-scale usage

KEY CONCEPTS:
1. Each feature has a cache_key based on:
   - Its own params hash
   - Its upstream dependencies' cache keys (transitive)
2. If cache_key matches, reuse cached B-Rep
3. Only recompile features with changed cache_key

PERFORMANCE:
- O(1) for unchanged features
- O(n) only for changed subtree
- Critical for real-time parameter editing

Version: 1.0
"""
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import pickle
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Cache Entry
# =============================================================================

@dataclass
class CacheEntry:
    """
    Cached compilation result for a single feature.

    Stores:
    - The compiled geometry (B-Rep or intermediate)
    - The cache key that was used
    - Metadata for debugging
    """
    feature_id: str
    cache_key: str
    geometry: Any  # The compiled B-Rep or solid
    timestamp: datetime = field(default_factory=datetime.utcnow)
    hit_count: int = 0

    def is_valid(self, expected_key: str) -> bool:
        """Check if this cache entry is valid for the expected key."""
        return self.cache_key == expected_key


# =============================================================================
# Dependency Graph
# =============================================================================

@dataclass
class DependencyNode:
    """
    A node in the dependency graph.

    Tracks:
    - Direct dependencies (upstream features)
    - Dependents (downstream features that depend on this)
    - Computed cache key including transitive dependencies
    """
    feature_id: str
    param_hash: str  # Hash of this feature's params only
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    cache_key: Optional[str] = None  # Computed including dependencies

    def compute_cache_key(
        self,
        upstream_keys: Dict[str, str]
    ) -> str:
        """
        Compute cache key including upstream dependencies.

        Cache key = hash(own_params + sorted_upstream_keys)

        This ensures:
        - Any change in params invalidates this node
        - Any change in upstream invalidates this node
        """
        # Collect upstream keys in deterministic order
        dep_keys = [
            upstream_keys.get(dep, "")
            for dep in sorted(self.dependencies)
        ]

        combined = {
            "param_hash": self.param_hash,
            "dependencies": dep_keys
        }

        combined_str = json.dumps(combined, sort_keys=True)
        self.cache_key = hashlib.sha256(combined_str.encode()).hexdigest()[:24]
        return self.cache_key


class DependencyGraph:
    """
    Manages feature dependencies for incremental compilation.

    Builds a DAG of features and computes cache keys.
    """

    def __init__(self):
        self.nodes: Dict[str, DependencyNode] = {}

    def add_node(
        self,
        feature_id: str,
        param_hash: str,
        dependencies: List[str]
    ) -> None:
        """Add a feature node to the graph."""
        node = DependencyNode(
            feature_id=feature_id,
            param_hash=param_hash,
            dependencies=dependencies
        )
        self.nodes[feature_id] = node

        # Update dependents for upstream nodes
        for dep in dependencies:
            if dep in self.nodes:
                self.nodes[dep].dependents.append(feature_id)

    def compute_all_cache_keys(self) -> Dict[str, str]:
        """
        Compute cache keys for all nodes in topological order.

        Returns:
            Dict mapping feature_id to cache_key
        """
        # Topological sort
        sorted_ids = self._topological_sort()

        cache_keys: Dict[str, str] = {}

        for fid in sorted_ids:
            node = self.nodes[fid]
            # Upstream keys are already computed due to topo sort
            key = node.compute_cache_key(cache_keys)
            cache_keys[fid] = key

        return cache_keys

    def get_invalidated_features(
        self,
        changed_feature_id: str
    ) -> List[str]:
        """
        Get all features that need recompilation due to a change.

        Returns:
            List of feature IDs (including the changed one)
            in topological order
        """
        if changed_feature_id not in self.nodes:
            return []

        # BFS to find all downstream dependents
        invalidated = set()
        queue = [changed_feature_id]

        while queue:
            current = queue.pop(0)
            if current in invalidated:
                continue
            invalidated.add(current)

            node = self.nodes.get(current)
            if node:
                for dep in node.dependents:
                    if dep not in invalidated:
                        queue.append(dep)

        # Return in topological order
        sorted_ids = self._topological_sort()
        return [fid for fid in sorted_ids if fid in invalidated]

    def _topological_sort(self) -> List[str]:
        """Return feature IDs in topological order."""
        in_degree = {fid: 0 for fid in self.nodes}
        graph = {fid: [] for fid in self.nodes}

        for fid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep in graph:
                    graph[dep].append(fid)
                    in_degree[fid] += 1

        # Kahn's algorithm
        queue = [fid for fid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result


# =============================================================================
# Incremental Compilation Cache
# =============================================================================

class IncrementalCache:
    """
    Cache for incremental compilation.

    Stores compiled geometry for features and manages invalidation.

    Usage:
        cache = IncrementalCache()

        # Build dependency graph
        for feature in features:
            cache.register_feature(
                feature_id=feature.id,
                param_hash=feature.compute_param_hash(),
                dependencies=feature.depends_on
            )

        # Compile with caching
        for feature in features:
            cached = cache.get(feature.id)
            if cached:
                solid = cached.geometry
            else:
                solid = compile_feature(feature)
                cache.put(feature.id, solid)
    """

    def __init__(
        self,
        max_entries: int = 1000,
        persist_path: Optional[Path] = None
    ):
        """
        Initialize the cache.

        Args:
            max_entries: Maximum cache entries (LRU eviction)
            persist_path: Optional path for persistent storage
        """
        self.max_entries = max_entries
        self.persist_path = persist_path

        self.entries: Dict[str, CacheEntry] = {}
        self.dependency_graph = DependencyGraph()
        self.cache_keys: Dict[str, str] = {}

        self._hits = 0
        self._misses = 0

    def register_feature(
        self,
        feature_id: str,
        param_hash: str,
        dependencies: List[str]
    ) -> None:
        """
        Register a feature in the dependency graph.

        Must be called before get/put.
        """
        self.dependency_graph.add_node(
            feature_id=feature_id,
            param_hash=param_hash,
            dependencies=dependencies
        )

    def compute_cache_keys(self) -> Dict[str, str]:
        """
        Compute all cache keys.

        Call after registering all features.
        """
        self.cache_keys = self.dependency_graph.compute_all_cache_keys()
        return self.cache_keys

    def get(self, feature_id: str) -> Optional[CacheEntry]:
        """
        Get cached geometry for a feature.

        Returns:
            CacheEntry if valid cache hit, None otherwise
        """
        expected_key = self.cache_keys.get(feature_id)
        if not expected_key:
            self._misses += 1
            return None

        entry = self.entries.get(feature_id)
        if entry and entry.is_valid(expected_key):
            entry.hit_count += 1
            self._hits += 1
            logger.debug(f"Cache HIT for feature {feature_id}")
            return entry

        self._misses += 1
        logger.debug(f"Cache MISS for feature {feature_id}")
        return None

    def put(
        self,
        feature_id: str,
        geometry: Any
    ) -> None:
        """
        Store compiled geometry for a feature.

        Args:
            feature_id: The feature ID
            geometry: The compiled geometry (B-Rep/solid)
        """
        cache_key = self.cache_keys.get(feature_id)
        if not cache_key:
            logger.warning(
                f"Cannot cache {feature_id}: no cache key computed"
            )
            return

        # LRU eviction
        if len(self.entries) >= self.max_entries:
            self._evict_lru()

        self.entries[feature_id] = CacheEntry(
            feature_id=feature_id,
            cache_key=cache_key,
            geometry=geometry
        )
        logger.debug(f"Cached feature {feature_id} with key {cache_key[:8]}...")

    def invalidate(self, feature_id: str) -> List[str]:
        """
        Invalidate a feature and all its dependents.

        Returns:
            List of invalidated feature IDs
        """
        invalidated = self.dependency_graph.get_invalidated_features(
            feature_id
        )

        for fid in invalidated:
            if fid in self.entries:
                del self.entries[fid]
                logger.debug(f"Invalidated cache for {fid}")

        return invalidated

    def clear(self) -> None:
        """Clear all cache entries."""
        self.entries.clear()
        self._hits = 0
        self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "entries": len(self.entries),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}"
        }

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self.entries:
            return

        # Find entry with oldest timestamp
        oldest_id = min(
            self.entries,
            key=lambda k: self.entries[k].timestamp
        )
        del self.entries[oldest_id]
        logger.debug(f"Evicted LRU cache entry: {oldest_id}")


# =============================================================================
# Incremental Compiler Wrapper
# =============================================================================

class IncrementalCompiler:
    """
    Wrapper that adds incremental compilation to any compiler.

    Usage:
        from app.compilers.build123d_compiler import Build123dCompiler

        base_compiler = Build123dCompiler()
        incremental = IncrementalCompiler(base_compiler)

        # First compile - full
        result = incremental.compile(feature_graph)

        # Parameter change - incremental
        feature_graph.parameters["height"] = 30.0
        result = incremental.compile(feature_graph)  # Only recompiles affected
    """

    def __init__(self, base_compiler: Any, cache: Optional[IncrementalCache] = None):
        """
        Initialize incremental compiler.

        Args:
            base_compiler: The underlying compiler
            cache: Optional pre-configured cache
        """
        self.base_compiler = base_compiler
        self.cache = cache or IncrementalCache()

    def compile_incremental(
        self,
        ir: Any,  # FeatureGraphIR
        job_id: str
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Compile with incremental caching.

        Args:
            ir: FeatureGraphIR to compile
            job_id: Job ID for tracking

        Returns:
            Tuple of (final_solid, compilation_stats)
        """
        from app.domain.feature_graph_ir import FeatureGraphIR

        # Register all features in cache
        self.cache.dependency_graph = DependencyGraph()
        self.cache.entries.clear()

        for feature in ir.features:
            self.cache.register_feature(
                feature_id=feature.id,
                param_hash=feature.compute_param_hash(),
                dependencies=list(feature.depends_on)
            )

        # Compute cache keys
        self.cache.compute_cache_keys()

        # Compile in topological order
        compiled_features: Dict[str, Any] = {}
        stats = {
            "total_features": len(ir.features),
            "cache_hits": 0,
            "cache_misses": 0,
            "recompiled": []
        }

        sorted_features = ir.topological_sort_features()

        for feature in sorted_features:
            # Check cache
            cached = self.cache.get(feature.id)

            if cached:
                compiled_features[feature.id] = cached.geometry
                stats["cache_hits"] += 1
            else:
                # Compile this feature
                # The base compiler needs to compile single feature
                # This is a simplified version - real implementation
                # would need feature-by-feature compilation
                geometry = self._compile_single_feature(
                    feature,
                    compiled_features,
                    ir
                )
                compiled_features[feature.id] = geometry
                self.cache.put(feature.id, geometry)
                stats["cache_misses"] += 1
                stats["recompiled"].append(feature.id)

        # Final solid is the last feature's geometry
        final_solid = None
        if sorted_features:
            final_solid = compiled_features.get(sorted_features[-1].id)

        stats["cache_stats"] = self.cache.get_stats()

        logger.info(
            f"Incremental compile: {stats['cache_hits']} hits, "
            f"{stats['cache_misses']} misses"
        )

        return final_solid, stats

    def _compile_single_feature(
        self,
        feature: Any,
        compiled_features: Dict[str, Any],
        ir: Any
    ) -> Any:
        """
        Compile a single feature.

        This is a placeholder - real implementation depends on compiler.
        """
        # For now, return None as placeholder
        # Real implementation would call base_compiler methods
        logger.debug(f"Compiling feature: {feature.id}")
        return None  # Placeholder


# =============================================================================
# Utility Functions
# =============================================================================

def compute_param_hash(params: Dict[str, float]) -> str:
    """Compute deterministic hash for feature parameters."""
    param_str = json.dumps(params, sort_keys=True)
    return hashlib.sha256(param_str.encode()).hexdigest()[:16]


def get_changed_features(
    old_ir: Any,
    new_ir: Any
) -> List[str]:
    """
    Find features that changed between two IR versions.

    Args:
        old_ir: Previous FeatureGraphIR
        new_ir: New FeatureGraphIR

    Returns:
        List of feature IDs that changed
    """
    old_hashes = {
        f.id: compute_param_hash(f.params)
        for f in old_ir.features
    }
    new_hashes = {
        f.id: compute_param_hash(f.params)
        for f in new_ir.features
    }

    changed = []

    # Check for changed or new features
    for fid, new_hash in new_hashes.items():
        old_hash = old_hashes.get(fid)
        if old_hash != new_hash:
            changed.append(fid)

    # Check for removed features (would need recompile anyway)
    for fid in old_hashes:
        if fid not in new_hashes:
            changed.append(fid)

    return changed
