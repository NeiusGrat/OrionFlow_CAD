"""
Dataset Manager - Collection, filtering, and versioning for fine-tuning.

VERSION 0.6: Production-grade dataset management.

Features:
- DatasetSample with quality metrics
- Save/load samples from disk
- Quality-based filtering
- Versioned datasets in JSONL format
"""
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


@dataclass
class DatasetSample:
    """
    Enhanced dataset sample with quality metrics.
    
    Captures prompt → FeatureGraph pairs with metadata
    for fine-tuning and quality analysis.
    """
    
    # Core data
    prompt: str
    feature_graph: Dict[str, Any]
    
    # Generation metadata
    timestamp: str = ""
    model_used: str = "unknown"
    attempt_number: int = 1
    success: bool = True
    
    # Quality metrics
    complexity_score: float = 0.0
    compilation_time_ms: float = 0.0
    has_validation_issues: bool = False
    validation_issues: List[Dict] = field(default_factory=list)
    
    # Execution trace
    execution_trace: Dict = field(default_factory=dict)
    
    # User feedback (optional)
    user_rating: Optional[int] = None  # 1-5 stars
    user_feedback: Optional[str] = None
    
    # Derived features
    feature_count: int = 0
    sketch_count: int = 0
    parameter_count: int = 0
    
    # Dataset metadata
    dataset_version: str = "1.0"
    sample_id: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        
        if not self.sample_id:
            self.sample_id = self._generate_id()
        
        # Extract derived features from feature graph
        self._extract_derived_features()
    
    def _generate_id(self) -> str:
        """Generate unique sample ID from content hash."""
        content = f"{self.prompt}{self.timestamp}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _extract_derived_features(self) -> None:
        """Extract counts and metrics from feature graph."""
        if not isinstance(self.feature_graph, dict):
            return
        
        self.feature_count = len(self.feature_graph.get("features", []))
        self.sketch_count = len(self.feature_graph.get("sketches", []))
        self.parameter_count = self._count_parameters()
    
    def _count_parameters(self) -> int:
        """Count total parameters in feature graph."""
        count = 0
        
        # Count in parameters table
        params = self.feature_graph.get("parameters", {})
        count += len(params)
        
        # Count in sketches
        for sketch in self.feature_graph.get("sketches", []):
            for prim in sketch.get("primitives", []):
                count += len(prim.get("params", {}))
        
        # Count in features
        for feature in self.feature_graph.get("features", []):
            count += len(feature.get("params", {}))
        
        return count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatasetSample":
        """Create from dictionary."""
        return cls(**data)


class DatasetManager:
    """
    Manages dataset collection, filtering, and versioning.
    
    Features:
    - Save individual samples with quality metrics
    - Load and filter samples by quality criteria
    - Create versioned datasets for fine-tuning (JSONL format)
    """
    
    def __init__(self, dataset_dir: Path = Path("./data/dataset")):
        """
        Initialize dataset manager.
        
        Args:
            dataset_dir: Base directory for dataset storage
        """
        self.dataset_dir = Path(dataset_dir)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        
        self.samples_dir = self.dataset_dir / "samples"
        self.samples_dir.mkdir(exist_ok=True)
        
        self.versions_dir = self.dataset_dir / "versions"
        self.versions_dir.mkdir(exist_ok=True)
        
        logger.info(f"DatasetManager initialized with dir={self.dataset_dir}")
    
    def save_sample(self, sample: DatasetSample) -> Path:
        """
        Save individual sample to disk.
        
        Args:
            sample: DatasetSample to save
            
        Returns:
            Path to saved file
        """
        # Generate filename with timestamp and ID
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{sample.sample_id}.json"
        filepath = self.samples_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(sample.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.debug(f"Saved sample: {filepath}")
        return filepath
    
    def load_sample(self, filepath: Path) -> Optional[DatasetSample]:
        """Load single sample from file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return DatasetSample.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load sample {filepath}: {e}")
            return None
    
    def load_all_samples(self) -> List[DatasetSample]:
        """
        Load all samples from samples directory.
        
        Returns:
            List of DatasetSample objects
        """
        samples = []
        
        for filepath in sorted(self.samples_dir.glob("*.json")):
            sample = self.load_sample(filepath)
            if sample:
                samples.append(sample)
        
        logger.info(f"Loaded {len(samples)} samples from {self.samples_dir}")
        return samples
    
    def filter_samples(
        self,
        samples: Optional[List[DatasetSample]] = None,
        min_complexity: float = 0.2,
        require_success: bool = True,
        max_validation_issues: int = 2
    ) -> List[DatasetSample]:
        """
        Filter samples by quality criteria.
        
        Args:
            samples: Samples to filter (loads from disk if None)
            min_complexity: Minimum complexity score (0.0-1.0)
            require_success: Only include successful generations
            max_validation_issues: Maximum allowed validation issues
            
        Returns:
            Filtered list of samples
        """
        if samples is None:
            samples = self.load_all_samples()
        
        filtered = []
        
        for sample in samples:
            # Success filter
            if require_success and not sample.success:
                continue
            
            # Complexity filter
            if sample.complexity_score < min_complexity:
                continue
            
            # Validation issues filter
            if len(sample.validation_issues) > max_validation_issues:
                continue
            
            filtered.append(sample)
        
        logger.info(f"Filtered {len(samples)} → {len(filtered)} samples")
        return filtered
    
    def create_dataset_version(
        self,
        version_name: str,
        samples: Optional[List[DatasetSample]] = None,
        metadata: Optional[Dict] = None
    ) -> Path:
        """
        Create versioned dataset for fine-tuning.
        
        Args:
            version_name: Version identifier (e.g., "v1.0")
            samples: Samples to include (filters from disk if None)
            metadata: Additional metadata
            
        Returns:
            Path to train.jsonl file
        """
        if samples is None:
            samples = self.filter_samples()
        
        version_dir = self.versions_dir / version_name
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Save in JSONL format (standard fine-tuning format)
        jsonl_path = version_dir / "train.jsonl"
        
        with open(jsonl_path, 'w', encoding='utf-8') as f:
            for sample in samples:
                record = {
                    "prompt": sample.prompt,
                    "completion": json.dumps(sample.feature_graph)
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        # Save metadata
        metadata_path = version_dir / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump({
                "version": version_name,
                "sample_count": len(samples),
                "created_at": datetime.now().isoformat(),
                "avg_complexity": sum(s.complexity_score for s in samples) / max(len(samples), 1),
                "metadata": metadata or {}
            }, f, indent=2)
        
        logger.info(f"Created dataset version {version_name} with {len(samples)} samples")
        return jsonl_path
    
    def calculate_complexity_score(self, feature_graph: Dict) -> float:
        """
        Calculate complexity score for feature graph.
        
        Scoring:
        - Feature count: +0.15 per feature
        - Sketch count: +0.1 per sketch
        - Feature type diversity: +0.15 per unique type
        - Topology references: +0.2 if present
        - Parameters: +0.05 per parameter
        
        Returns:
            Score capped at 1.0
        """
        score = 0.0
        
        # Feature complexity
        features = feature_graph.get("features", [])
        score += len(features) * 0.15
        
        # Sketch complexity
        sketches = feature_graph.get("sketches", [])
        score += len(sketches) * 0.1
        
        # Feature type diversity
        feature_types = set(f.get("type") for f in features if f.get("type"))
        score += len(feature_types) * 0.15
        
        # Advanced features (topology refs)
        for feature in features:
            if "topology_refs" in feature:
                score += 0.2
                break  # Only count once
        
        # Parameter count
        param_count = len(feature_graph.get("parameters", {}))
        score += param_count * 0.05
        
        return min(score, 1.0)  # Cap at 1.0
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get dataset statistics."""
        samples = self.load_all_samples()
        
        if not samples:
            return {"total_samples": 0}
        
        return {
            "total_samples": len(samples),
            "successful": sum(1 for s in samples if s.success),
            "avg_complexity": sum(s.complexity_score for s in samples) / len(samples),
            "avg_features": sum(s.feature_count for s in samples) / len(samples),
            "with_validation_issues": sum(1 for s in samples if s.has_validation_issues),
            "models_used": list(set(s.model_used for s in samples))
        }
