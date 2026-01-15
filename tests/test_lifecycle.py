"""
Test Phase 6: Design Lifecycle System

Tests for:
- Kernel abstraction (adapter pattern)
- Kernel registry
- FeatureGraph versioning
- Diff algorithm
- Undo/redo/branch operations
"""
import pytest
from pathlib import Path
from app.compilers.kernel_adapter import (
    KernelAdapter, KernelRegistry, Build123dAdapter, GeometryResult
)
from app.domain.versioning import VersionManager, FeatureGraphDiff
from app.domain.feature_graph_v3 import FeatureGraphV3


def test_kernel_registry_list():
    """Test that kernel registry lists available kernels."""
    available = KernelRegistry.list_available()
    
    # build123d should be available (installed)
    assert "build123d" in available
    
    print(f"✓ Available kernels: {available}")


def test_build123d_adapter_available():
    """Test build123d adapter is available."""
    adapter = KernelRegistry.get("build123d", output_dir=Path("outputs"))
    
    assert adapter.is_available()
    assert adapter.name == "build123d"
    
    print("✓ Build123d adapter available")


def test_kernel_adapter_interface():
    """Test that adapters implement KernelAdapter interface."""
    adapter = Build123dAdapter(output_dir=Path("outputs"))
    
    # Check interface methods exist
    assert hasattr(adapter, 'compile')
    assert hasattr(adapter, 'export')
    assert hasattr(adapter, 'is_available')
    assert hasattr(adapter, 'name')
    
    print("✓ Kernel adapter interface complete")


def test_version_manager_commit():
    """Test committing versions."""
    from app.domain.feature_graph_v3 import FeatureGraphV3, SketchGraphV2, FeatureV2
    
    # Create simple graph
    graph_v1 = FeatureGraphV3(
        version="3.0",
        parameters={"width": 100.0},
        sketches=[],
        features=[]
    )
    
    vm = VersionManager()
    version = vm.commit(graph_v1, message="Initial commit")
    
    assert version.id is not None
    assert version.message == "Initial commit"
    assert vm.current_version_id == version.id
    
    print("✓ Version commit works")


def test_version_manager_undo():
    """Test undo functionality."""
    from app.domain.feature_graph_v3 import FeatureGraphV3
    
    graph_v1 = FeatureGraphV3(version="3.0", parameters={"width": 100.0}, sketches=[], features=[])
    graph_v2 = FeatureGraphV3(version="3.0", parameters={"width": 200.0}, sketches=[], features=[])
    
    vm = VersionManager()
    v1 = vm.commit(graph_v1, "Version 1")
    v2 = vm.commit(graph_v2, "Version 2 - increased width")
    
    # Undo should return to v1
    previous = vm.undo()
    
    assert previous is not None
    assert previous.parameters["width"] == 100.0
    assert vm.current_version_id == v1.id
    
    print("✓ Undo works")


def test_diff_computation():
    """Test computing diff between graphs."""
    from app.domain.feature_graph_v3 import FeatureGraphV3
    
    graph_a = FeatureGraphV3(
        version="3.0",
        parameters={"width": 100.0, "height": 50.0},
        sketches=[],
        features=[]
    )
    
    graph_b = FeatureGraphV3(
        version="3.0",
        parameters={"width": 200.0, "height": 50.0},  # width changed
        sketches=[],
        features=[]
    )
    
    vm = VersionManager()
    diff = vm._compute_diff(graph_a, graph_b)
    
    assert "width" in diff.modified_parameters
    assert diff.modified_parameters["width"] == (100.0, 200.0)
    assert "height" not in diff.modified_parameters  # unchanged
    
    print("✓ Diff computation works")


def test_branch_creation():
    """Test creating design variants via branching."""
    from app.domain.feature_graph_v3 import FeatureGraphV3
    
    graph = FeatureGraphV3(version="3.0", parameters={"width": 100.0}, sketches=[], features=[])
    
    vm = VersionManager()
    v1 = vm.commit(graph, "Main design")
    
    # Create variant branch
    branch = vm.create_branch("lightweight_variant", from_version_id=v1.id)
    
    assert branch == "lightweight_variant"
    assert "lightweight_variant" in vm.branches
    
    print("✓ Branch creation works")


def test_version_history():
    """Test getting commit history."""
    from app.domain.feature_graph_v3 import FeatureGraphV3
    
    vm = VersionManager()
    
    # Create 3 commits
    for i in range(3):
        graph = FeatureGraphV3(
            version="3.0",
            parameters={"iteration": i},
            sketches=[],
            features=[]
        )
        vm.commit(graph, f"Commit {i}")
    
    history = vm.get_history("main", limit=10)
    
    assert len(history) == 3
    assert history[0].message == "Commit 2"  # Most recent first
    assert history[2].message == "Commit 0"
    
    print("✓ Version history works")


if __name__ == "__main__":
    test_kernel_registry_list()
    test_build123d_adapter_available()
    test_kernel_adapter_interface()
    test_version_manager_commit()
    test_version_manager_undo()
    test_diff_computation()
    test_branch_creation()
    test_version_history()
    print("\n✅ All Phase 6 lifecycle tests passed!")
