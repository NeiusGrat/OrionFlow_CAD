"""
Kernel Abstraction Layer - Phase 6

Protects OrionFlow from build123d changes/deprecation by abstracting the CAD kernel.

Benefits:
- Swap kernels without changing service layer
- Multi-backend support (build123d, Onshape, OCCT)
- Future-proof architecture

Architecture:
    KernelAdapter (interface)
         ↓
    ┌────────┬──────────┬──────────┐
    Build123d  Onshape    OCCT
    Adapter    Adapter    Adapter
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple, Dict, Any
from app.domain.feature_graph_v3 import FeatureGraphV3
from app.domain.execution_trace import ExecutionTrace


class GeometryResult:
    """
    Kernel-agnostic geometry result.
    
    Encapsulates compiled geometry without exposing kernel-specific types.
    """
    def __init__(
        self,
        step_path: Path,
        stl_path: Path,
        glb_path: Path,
        trace: ExecutionTrace,
        metadata: Dict[str, Any] = None
    ):
        self.step_path = step_path
        self.stl_path = stl_path
        self.glb_path = glb_path
        self.trace = trace
        self.metadata = metadata or {}


class KernelAdapter(ABC):
    """
    Abstract CAD kernel interface.
    
    All compilers implement this interface, enabling swappable backends.
    
    Example:
        adapter = KernelRegistry.get("build123d")
        result = adapter.compile(feature_graph, job_id)
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Kernel name for registry."""
        pass
    
    @abstractmethod
    def compile(
        self,
        feature_graph: FeatureGraphV3,
        job_id: str
    ) -> GeometryResult:
        """
        Compile FeatureGraph to geometry.
        
        Args:
            feature_graph: Design to compile
            job_id: Unique job identifier
            
        Returns:
            GeometryResult with file paths and trace
        """
        pass
    
    @abstractmethod
    def export(self, result: GeometryResult, format: str) -> bytes:
        """
        Export geometry to specific format.
        
        Args:
            result: Previously compiled geometry
            format: "step", "stl", "glb", etc.
            
        Returns:
            File bytes
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this kernel is available.
        
        Returns:
            True if dependencies installed and configured
        """
        pass


class Build123dAdapter(KernelAdapter):
    """
    Adapter for build123d kernel (current default).
    
    Wraps Build123dCompilerV3 with KernelAdapter interface.
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        self.output_dir = output_dir
        self._compiler = None
    
    @property
    def name(self) -> str:
        return "build123d"
    
    def compile(
        self,
        feature_graph: FeatureGraphV3,
        job_id: str
    ) -> GeometryResult:
        """Compile using Build123dCompilerV3."""
        from app.compilers import Build123dCompilerV3
        
        if not self._compiler:
            self._compiler = Build123dCompilerV3(self.output_dir)
        
        step_path, stl_path, glb_path, trace = self._compiler.compile(
            feature_graph,
            job_id
        )
        
        return GeometryResult(
            step_path=step_path,
            stl_path=stl_path,
            glb_path=glb_path,
            trace=trace,
            metadata={"kernel": "build123d"}
        )
    
    def export(self, result: GeometryResult, format: str) -> bytes:
        """Read exported file bytes."""
        path_map = {
            "step": result.step_path,
            "stl": result.stl_path,
            "glb": result.glb_path
        }
        
        if format not in path_map:
            raise ValueError(f"Unsupported format: {format}")
        
        with open(path_map[format], "rb") as f:
            return f.read()
    
    def is_available(self) -> bool:
        """Check if build123d is installed."""
        try:
            import build123d
            return True
        except ImportError:
            return False


class OnshapeAdapter(KernelAdapter):
    """
    Adapter for Onshape cloud API.
    
    Translates FeatureGraph to FeatureScript and pushes via API.
    """
    
    def __init__(self):
        self._client = None
        self._compiler = None
    
    @property
    def name(self) -> str:
        return "onshape"
    
    def compile(
        self,
        feature_graph: FeatureGraphV3,
        job_id: str
    ) -> GeometryResult:
        """Compile via Onshape API."""
        # Import Onshape components
        from app.clients.onshape_client import OnshapeClient
        from app.compilers.onshape_compiler import OnshapeCompiler
        
        if not self._client:
            self._client = OnshapeClient()
        if not self._compiler:
            self._compiler = OnshapeCompiler()
        
        # This would:
        # 1. Convert FeatureGraph → FeatureScript
        # 2. Push to Onshape document via API
        # 3. Trigger regeneration
        # 4. Download result files
        
        # Simplified placeholder
        raise NotImplementedError("Onshape adapter needs API credentials")
    
    def export(self, result: GeometryResult, format: str) -> bytes:
        """Export from Onshape."""
        raise NotImplementedError("Onshape export not yet implemented")
    
    def is_available(self) -> bool:
        """Check if Onshape is configured."""
        try:
            from app.clients.onshape_client import OnshapeClient
            client = OnshapeClient()
            return client.is_configured()
        except:
            return False


class OCCTAdapter(KernelAdapter):
    """
    Adapter for raw OCCT bindings (future).
    
    Direct OCCT calls without build123d wrapper.
    Useful for fine-grained control or if build123d is deprecated.
    """
    
    @property
    def name(self) -> str:
        return "occt"
    
    def compile(
        self,
        feature_graph: FeatureGraphV3,
        job_id: str
    ) -> GeometryResult:
        """Compile using raw OCCT."""
        # Would use python-occ or similar
        raise NotImplementedError("OCCT adapter not yet implemented")
    
    def export(self, result: GeometryResult, format: str) -> bytes:
        """Export using OCCT IO."""
        raise NotImplementedError("OCCT export not yet implemented")
    
    def is_available(self) -> bool:
        """Check if OCCT bindings are installed."""
        try:
            import OCC
            return True
        except ImportError:
            return False


class KernelRegistry:
    """
    Central registry of available CAD kernels.
    
    Usage:
        # Get adapter by name
        adapter = KernelRegistry.get("build123d")
        result = adapter.compile(graph, job_id)
        
        # List available kernels
        available = KernelRegistry.list_available()
    """
    
    _adapters = {
        "build123d": Build123dAdapter,
        "onshape": OnshapeAdapter,
        "occt": OCCTAdapter
    }
    
    _instances = {}  # Cached instances
    
    @classmethod
    def get(cls, name: str, **kwargs) -> KernelAdapter:
        """
        Get kernel adapter by name.
        
        Args:
            name: Kernel name ("build123d", "onshape", "occt")
            **kwargs: Adapter-specific initialization args
            
        Returns:
            KernelAdapter instance
        """
        if name not in cls._adapters:
            raise ValueError(f"Unknown kernel: {name}. Available: {list(cls._adapters.keys())}")
        
        # Return cached instance or create new
        if name not in cls._instances:
            adapter_class = cls._adapters[name]
            cls._instances[name] = adapter_class(**kwargs)
        
        return cls._instances[name]
    
    @classmethod
    def list_available(cls) -> list[str]:
        """
        List kernels that are installed and configured.
        
        Returns:
            List of available kernel names
        """
        available = []
        for name, adapter_class in cls._adapters.items():
            try:
                adapter = adapter_class()
                if adapter.is_available():
                    available.append(name)
            except:
                continue
        
        return available
    
    @classmethod
    def register(cls, name: str, adapter_class: type):
        """
        Register a custom kernel adapter.
        
        Args:
            name: Kernel name
            adapter_class: KernelAdapter subclass
        """
        cls._adapters[name] = adapter_class
