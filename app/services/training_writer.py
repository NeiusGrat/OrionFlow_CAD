"""
Training Data Writer - Persist training samples for LLM fine-tuning.

==============================================================================
OUTPUT STRUCTURE
==============================================================================

data/training/
├── v1/
│   ├── success/
│   │   └── 2026-01-20.jsonl
│   └── failure/
│       └── 2026-01-20.jsonl
└── stats.json

Each JSONL line is a complete TrainingSample for fine-tuning.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

from app.domain.training_sample import TrainingSample
from app.config import settings

logger = logging.getLogger(__name__)

# Default training data root
TRAINING_ROOT = Path("data/training")
CURRENT_VERSION = "v1"


class TrainingDataWriter:
    """
    Write training samples to organized JSONL files.
    
    Features:
    - Organized by version/success/date
    - JSONL format for streaming fine-tuning
    - Stats tracking for dataset analysis
    """
    
    def __init__(
        self,
        root_dir: Path = TRAINING_ROOT,
        version: str = CURRENT_VERSION
    ):
        self.root_dir = root_dir
        self.version = version
        self.version_dir = root_dir / version
        
        # Create directory structure
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Create directory structure if needed."""
        (self.version_dir / "success").mkdir(parents=True, exist_ok=True)
        (self.version_dir / "failure").mkdir(parents=True, exist_ok=True)
    
    def write_sample(self, sample: TrainingSample) -> Path:
        """
        Write a training sample to JSONL file.
        
        Args:
            sample: TrainingSample to persist
            
        Returns:
            Path to the JSONL file
        """
        # Determine target directory based on compile success
        status_dir = "success" if sample.compile_success else "failure"
        target_dir = self.version_dir / status_dir
        
        # Daily file for organization
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"{date_str}.jsonl"
        filepath = target_dir / filename
        
        try:
            # Update quality score before writing
            sample.quality_score = sample.calculate_quality_score()
            
            # Append to JSONL
            with open(filepath, "a", encoding="utf-8") as f:
                json_line = sample.model_dump_json()
                f.write(json_line + "\n")
            
            logger.debug(f"Wrote training sample {sample.sample_id} to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Failed to write training sample: {e}")
            raise
    
    def write_training_pair(self, sample: TrainingSample) -> Path:
        """
        Write sample in prompt/completion format for fine-tuning.
        
        This creates a separate file optimized for direct fine-tuning:
        {"prompt": "...", "completion": {"feature_graph": ...}}
        
        Args:
            sample: TrainingSample to convert
            
        Returns:
            Path to the training pairs file
        """
        if not sample.compile_success:
            # Don't write failed samples to training pairs
            return Path("")
        
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"training_pairs_{date_str}.jsonl"
        filepath = self.version_dir / filename
        
        try:
            training_dict = sample.to_training_dict()
            
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(training_dict) + "\n")
            
            return filepath
            
        except Exception as e:
            logger.error(f"Failed to write training pair: {e}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the training dataset.
        
        Returns:
            Dict with counts and quality metrics
        """
        stats = {
            "version": self.version,
            "success_count": 0,
            "failure_count": 0,
            "total_count": 0,
            "success_rate": 0.0,
            "avg_quality_score": 0.0,
            "files": []
        }
        
        # Count success samples
        success_dir = self.version_dir / "success"
        if success_dir.exists():
            for jsonl_file in success_dir.glob("*.jsonl"):
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    stats["success_count"] += len(lines)
                    stats["files"].append(str(jsonl_file))
        
        # Count failure samples
        failure_dir = self.version_dir / "failure"
        if failure_dir.exists():
            for jsonl_file in failure_dir.glob("*.jsonl"):
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    stats["failure_count"] += len(lines)
                    stats["files"].append(str(jsonl_file))
        
        stats["total_count"] = stats["success_count"] + stats["failure_count"]
        
        if stats["total_count"] > 0:
            stats["success_rate"] = stats["success_count"] / stats["total_count"]
        
        return stats
    
    def load_samples(
        self,
        success_only: bool = False,
        limit: Optional[int] = None
    ) -> List[TrainingSample]:
        """
        Load samples from the dataset.
        
        Args:
            success_only: Only load successful samples
            limit: Maximum number of samples to load
            
        Returns:
            List of TrainingSample objects
        """
        samples = []
        
        dirs_to_scan = [self.version_dir / "success"]
        if not success_only:
            dirs_to_scan.append(self.version_dir / "failure")
        
        for dir_path in dirs_to_scan:
            if not dir_path.exists():
                continue
                
            for jsonl_file in sorted(dir_path.glob("*.jsonl")):
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if limit and len(samples) >= limit:
                            return samples
                        
                        try:
                            data = json.loads(line.strip())
                            sample = TrainingSample(**data)
                            samples.append(sample)
                        except Exception as e:
                            logger.warning(f"Failed to parse sample: {e}")
        
        return samples


# Singleton instance for convenience
_writer_instance: Optional[TrainingDataWriter] = None


def get_training_writer() -> TrainingDataWriter:
    """Get singleton TrainingDataWriter instance."""
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = TrainingDataWriter()
    return _writer_instance


def write_training_sample(sample: TrainingSample) -> Path:
    """
    Convenience function to write a training sample.
    
    Args:
        sample: TrainingSample to persist
        
    Returns:
        Path to the JSONL file
    """
    writer = get_training_writer()
    path = writer.write_sample(sample)
    
    # Also write training pair if successful
    if sample.compile_success:
        writer.write_training_pair(sample)
    
    return path
