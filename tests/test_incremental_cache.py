"""
Tests for Incremental Rebuild Cache (STEP 3).

Tests the dependency-aware caching system for:
1. Correct cache key computation
2. Dependency graph traversal
3. Invalidation propagation
4. Cache hit/miss behavior
"""
import pytest
from app.compilers.incremental_cache import (
    CacheEntry,
    DependencyNode,
    DependencyGraph,
    IncrementalCache,
    compute_param_hash,
    get_changed_features
)
from datetime import datetime


class TestCacheEntry:
    """Tests for CacheEntry."""

    def test_valid_entry(self):
        """Valid cache entry."""
        entry = CacheEntry(
            feature_id="f1",
            cache_key="abc123",
            geometry="mock_solid"
        )
        assert entry.feature_id == "f1"
        assert entry.hit_count == 0

    def test_is_valid_matching_key(self):
        """Entry is valid when key matches."""
        entry = CacheEntry(
            feature_id="f1",
            cache_key="abc123",
            geometry="mock_solid"
        )
        assert entry.is_valid("abc123")
        assert not entry.is_valid("different")


class TestDependencyNode:
    """Tests for DependencyNode."""

    def test_compute_cache_key_no_deps(self):
        """Node without dependencies uses only param hash."""
        node = DependencyNode(
            feature_id="f1",
            param_hash="hash123"
        )
        key = node.compute_cache_key({})
        assert key is not None
        assert len(key) == 24

    def test_compute_cache_key_with_deps(self):
        """Node with dependencies includes upstream keys."""
        node = DependencyNode(
            feature_id="f2",
            param_hash="hash456",
            dependencies=["f1"]
        )
        key = node.compute_cache_key({"f1": "upstream_key"})
        assert key is not None

    def test_different_deps_different_keys(self):
        """Different upstream keys produce different cache keys."""
        node = DependencyNode(
            feature_id="f2",
            param_hash="hash456",
            dependencies=["f1"]
        )
        key1 = node.compute_cache_key({"f1": "key_a"})

        node2 = DependencyNode(
            feature_id="f2",
            param_hash="hash456",
            dependencies=["f1"]
        )
        key2 = node2.compute_cache_key({"f1": "key_b"})

        assert key1 != key2


class TestDependencyGraph:
    """Tests for DependencyGraph."""

    @pytest.fixture
    def linear_graph(self):
        """Create a linear dependency chain: f1 -> f2 -> f3."""
        graph = DependencyGraph()
        graph.add_node("f1", "hash1", [])
        graph.add_node("f2", "hash2", ["f1"])
        graph.add_node("f3", "hash3", ["f2"])
        return graph

    @pytest.fixture
    def diamond_graph(self):
        """Create a diamond dependency: f1 -> (f2, f3) -> f4."""
        graph = DependencyGraph()
        graph.add_node("f1", "hash1", [])
        graph.add_node("f2", "hash2", ["f1"])
        graph.add_node("f3", "hash3", ["f1"])
        graph.add_node("f4", "hash4", ["f2", "f3"])
        return graph

    def test_add_node(self):
        """Adding nodes to graph."""
        graph = DependencyGraph()
        graph.add_node("f1", "hash1", [])
        assert "f1" in graph.nodes

    def test_compute_cache_keys_linear(self, linear_graph):
        """Cache keys computed correctly for linear chain."""
        keys = linear_graph.compute_all_cache_keys()
        assert len(keys) == 3
        assert "f1" in keys
        assert "f2" in keys
        assert "f3" in keys

    def test_compute_cache_keys_diamond(self, diamond_graph):
        """Cache keys computed correctly for diamond graph."""
        keys = diamond_graph.compute_all_cache_keys()
        assert len(keys) == 4

    def test_topological_sort_linear(self, linear_graph):
        """Topological sort of linear chain."""
        sorted_ids = linear_graph._topological_sort()
        assert sorted_ids == ["f1", "f2", "f3"]

    def test_topological_sort_diamond(self, diamond_graph):
        """Topological sort of diamond graph."""
        sorted_ids = diamond_graph._topological_sort()
        # f1 must come first, f4 must come last
        assert sorted_ids[0] == "f1"
        assert sorted_ids[-1] == "f4"
        # f2 and f3 must come before f4
        assert sorted_ids.index("f2") < sorted_ids.index("f4")
        assert sorted_ids.index("f3") < sorted_ids.index("f4")

    def test_get_invalidated_features_linear(self, linear_graph):
        """Invalidating f1 should invalidate entire chain."""
        invalidated = linear_graph.get_invalidated_features("f1")
        assert set(invalidated) == {"f1", "f2", "f3"}

    def test_get_invalidated_features_middle(self, linear_graph):
        """Invalidating f2 should only invalidate f2, f3."""
        invalidated = linear_graph.get_invalidated_features("f2")
        assert set(invalidated) == {"f2", "f3"}

    def test_get_invalidated_features_leaf(self, linear_graph):
        """Invalidating leaf should only invalidate itself."""
        invalidated = linear_graph.get_invalidated_features("f3")
        assert set(invalidated) == {"f3"}

    def test_get_invalidated_features_diamond(self, diamond_graph):
        """Invalidating f1 in diamond should invalidate all."""
        invalidated = diamond_graph.get_invalidated_features("f1")
        assert set(invalidated) == {"f1", "f2", "f3", "f4"}

    def test_get_invalidated_features_diamond_branch(self, diamond_graph):
        """Invalidating f2 should invalidate f2 and f4."""
        invalidated = diamond_graph.get_invalidated_features("f2")
        assert set(invalidated) == {"f2", "f4"}


class TestIncrementalCache:
    """Tests for IncrementalCache."""

    @pytest.fixture
    def cache_with_features(self):
        """Create cache with registered features."""
        cache = IncrementalCache(max_entries=10)
        cache.register_feature("f1", "hash1", [])
        cache.register_feature("f2", "hash2", ["f1"])
        cache.register_feature("f3", "hash3", ["f2"])
        cache.compute_cache_keys()
        return cache

    def test_cache_miss_without_entry(self, cache_with_features):
        """Cache miss when entry doesn't exist."""
        entry = cache_with_features.get("f1")
        assert entry is None

    def test_cache_hit_after_put(self, cache_with_features):
        """Cache hit after storing entry."""
        cache_with_features.put("f1", "solid_f1")
        entry = cache_with_features.get("f1")
        assert entry is not None
        assert entry.geometry == "solid_f1"

    def test_cache_invalidation(self, cache_with_features):
        """Invalidating feature removes from cache."""
        cache_with_features.put("f1", "solid_f1")
        cache_with_features.put("f2", "solid_f2")
        cache_with_features.put("f3", "solid_f3")

        invalidated = cache_with_features.invalidate("f1")

        assert set(invalidated) == {"f1", "f2", "f3"}
        assert cache_with_features.get("f1") is None
        assert cache_with_features.get("f2") is None
        assert cache_with_features.get("f3") is None

    def test_cache_stats(self, cache_with_features):
        """Cache stats track hits and misses."""
        # Miss
        cache_with_features.get("f1")
        # Put
        cache_with_features.put("f1", "solid_f1")
        # Hit
        cache_with_features.get("f1")
        # Hit
        cache_with_features.get("f1")

        stats = cache_with_features.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["entries"] == 1

    def test_lru_eviction(self):
        """Oldest entry evicted when cache full."""
        cache = IncrementalCache(max_entries=2)
        cache.register_feature("f1", "hash1", [])
        cache.register_feature("f2", "hash2", [])
        cache.register_feature("f3", "hash3", [])
        cache.compute_cache_keys()

        cache.put("f1", "solid_f1")
        cache.put("f2", "solid_f2")
        # This should evict f1
        cache.put("f3", "solid_f3")

        assert len(cache.entries) == 2
        # f1 should be evicted (oldest)
        assert "f1" not in cache.entries


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_compute_param_hash_deterministic(self):
        """Same params produce same hash."""
        params = {"width": 10.0, "height": 20.0}
        hash1 = compute_param_hash(params)
        hash2 = compute_param_hash(params)
        assert hash1 == hash2

    def test_compute_param_hash_order_independent(self):
        """Parameter order doesn't affect hash."""
        params1 = {"width": 10.0, "height": 20.0}
        params2 = {"height": 20.0, "width": 10.0}
        assert compute_param_hash(params1) == compute_param_hash(params2)

    def test_compute_param_hash_different_values(self):
        """Different values produce different hash."""
        params1 = {"width": 10.0}
        params2 = {"width": 20.0}
        assert compute_param_hash(params1) != compute_param_hash(params2)


class TestChangedFeatureDetection:
    """Tests for detecting changed features between IR versions."""

    def test_detect_changed_feature(self):
        """Should detect feature with changed params."""
        # Create mock IR objects
        class MockFeature:
            def __init__(self, fid, params):
                self.id = fid
                self.params = params

        class MockIR:
            def __init__(self, features):
                self.features = features

        old_ir = MockIR([
            MockFeature("f1", {"width": 10.0}),
            MockFeature("f2", {"height": 20.0})
        ])
        new_ir = MockIR([
            MockFeature("f1", {"width": 10.0}),  # Same
            MockFeature("f2", {"height": 30.0})  # Changed
        ])

        changed = get_changed_features(old_ir, new_ir)
        assert "f2" in changed
        assert "f1" not in changed

    def test_detect_new_feature(self):
        """Should detect newly added feature."""
        class MockFeature:
            def __init__(self, fid, params):
                self.id = fid
                self.params = params

        class MockIR:
            def __init__(self, features):
                self.features = features

        old_ir = MockIR([
            MockFeature("f1", {"width": 10.0})
        ])
        new_ir = MockIR([
            MockFeature("f1", {"width": 10.0}),
            MockFeature("f2", {"height": 20.0})  # New
        ])

        changed = get_changed_features(old_ir, new_ir)
        assert "f2" in changed
