"""
Fine-Tuning Data Logger - Structured Pipeline Capture for LLM Training

==============================================================================
ARCHITECTURE: Complete Pipeline State Capture
==============================================================================

This module captures the COMPLETE state of every generation for fine-tuning:
1. User prompt (input)
2. ConstructionPlan (reasoning/planning)
3. FeatureGraphIR (execution output)
4. Compilation metrics (performance)
5. Validation results (quality)
6. User feedback (optional ground truth)

DATA FLOW:
    User Prompt
         |
         v
    FineTuningRecord.start()
         |
         v
    ConstructionPlan → record.set_plan()
         |
         v
    FeatureGraphIR → record.set_ir()
         |
         v
    Compilation → record.set_metrics()
         |
         v
    Validation → record.set_validation()
         |
         v
    record.finalize() → JSONL file

STRICT JSON REQUIREMENTS (LLM fine-tuning compatible):
- All records must be valid JSON
- No Python objects, only primitives/dicts/lists
- Deterministic serialization (sorted keys)
- ISO 8601 timestamps
- UTF-8 encoding

FINE-TUNING FORMATS:
- OpenAI: {"messages": [{"role": ..., "content": ...}]}
- Anthropic: {"prompt": ..., "completion": ...}
- Custom: Full pipeline state for advanced training

Version: 1.0
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from enum import Enum
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Record Status
# =============================================================================

class RecordStatus(str, Enum):
    """Status of a fine-tuning record."""
    STARTED = "started"
    PLAN_SET = "plan_set"
    IR_SET = "ir_set"
    COMPILED = "compiled"
    FINALIZED = "finalized"
    FAILED = "failed"


class GenerationOutcome(str, Enum):
    """Outcome of generation attempt."""
    SUCCESS = "success"
    PLAN_FAILED = "plan_failed"
    IR_FAILED = "ir_failed"
    COMPILATION_FAILED = "compilation_failed"
    VALIDATION_FAILED = "validation_failed"


# =============================================================================
# Fine-Tuning Record
# =============================================================================

@dataclass
class FineTuningRecord:
    """
    Complete record of a single generation for fine-tuning.

    Captures all pipeline stages in a format suitable for LLM training.
    """

    # Identity
    record_id: str = ""
    job_id: str = ""
    session_id: str = ""

    # Timestamps
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0

    # Status
    status: str = RecordStatus.STARTED.value
    outcome: str = ""

    # Input
    prompt: str = ""
    prompt_tokens: int = 0

    # Planning stage (Intelligence)
    plan: Optional[Dict[str, Any]] = None
    plan_generation_ms: float = 0.0
    plan_source: str = ""  # LLM, HEURISTIC, TEMPLATE

    # IR stage (Execution)
    ir: Optional[Dict[str, Any]] = None
    ir_generation_ms: float = 0.0
    ir_version: str = "1.0-IR"

    # Compilation stage
    compilation_success: bool = False
    compilation_ms: float = 0.0
    compiled_features: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    # Validation stage
    validation: Optional[Dict[str, Any]] = None
    validation_errors: int = 0
    validation_warnings: int = 0

    # Output
    output_files: List[str] = field(default_factory=list)
    output_format: str = ""  # STEP, STL, GLB

    # Quality metrics
    complexity_score: float = 0.0
    feature_count: int = 0
    sketch_count: int = 0
    parameter_count: int = 0

    # LLM metadata
    llm_model: str = ""
    llm_temperature: float = 0.0
    llm_tokens_used: int = 0
    llm_latency_ms: float = 0.0

    # User feedback (ground truth)
    user_rating: Optional[int] = None  # 1-5
    user_feedback: Optional[str] = None
    user_edited: bool = False

    # Error details
    error_message: str = ""
    error_stage: str = ""
    retry_count: int = 0

    def __post_init__(self):
        if not self.record_id:
            self.record_id = self._generate_id()
        if not self.started_at:
            self.started_at = datetime.utcnow().isoformat() + "Z"

    def _generate_id(self) -> str:
        """Generate unique record ID."""
        content = f"{self.prompt}{self.started_at}{self.job_id}"
        return "ftr_" + hashlib.sha256(content.encode()).hexdigest()[:16]

    def set_plan(
        self,
        plan_dict: Dict[str, Any],
        generation_ms: float = 0.0,
        source: str = "LLM"
    ) -> "FineTuningRecord":
        """Set the ConstructionPlan data."""
        self.plan = self._sanitize_dict(plan_dict)
        self.plan_generation_ms = generation_ms
        self.plan_source = source
        self.status = RecordStatus.PLAN_SET.value
        return self

    def set_ir(
        self,
        ir_dict: Dict[str, Any],
        generation_ms: float = 0.0
    ) -> "FineTuningRecord":
        """Set the FeatureGraphIR data."""
        self.ir = self._sanitize_dict(ir_dict)
        self.ir_generation_ms = generation_ms

        # Extract metrics from IR
        if self.ir:
            self.feature_count = len(self.ir.get("features", []))
            self.sketch_count = len(self.ir.get("sketches", []))
            self.parameter_count = len(self.ir.get("parameters", {}))
            self.ir_version = self.ir.get("version", "1.0-IR")

        self.status = RecordStatus.IR_SET.value
        return self

    def set_compilation_result(
        self,
        success: bool,
        compilation_ms: float,
        compiled_features: int = 0,
        cache_hits: int = 0,
        cache_misses: int = 0
    ) -> "FineTuningRecord":
        """Set compilation results."""
        self.compilation_success = success
        self.compilation_ms = compilation_ms
        self.compiled_features = compiled_features
        self.cache_hits = cache_hits
        self.cache_misses = cache_misses
        self.status = RecordStatus.COMPILED.value
        return self

    def set_validation(
        self,
        validation_result: Dict[str, Any]
    ) -> "FineTuningRecord":
        """Set validation results."""
        self.validation = self._sanitize_dict(validation_result)
        self.validation_errors = validation_result.get("errors", 0)
        self.validation_warnings = validation_result.get("warnings", 0)
        return self

    def set_llm_metadata(
        self,
        model: str,
        temperature: float = 0.0,
        tokens_used: int = 0,
        latency_ms: float = 0.0
    ) -> "FineTuningRecord":
        """Set LLM metadata."""
        self.llm_model = model
        self.llm_temperature = temperature
        self.llm_tokens_used = tokens_used
        self.llm_latency_ms = latency_ms
        return self

    def set_user_feedback(
        self,
        rating: Optional[int] = None,
        feedback: Optional[str] = None,
        edited: bool = False
    ) -> "FineTuningRecord":
        """Set user feedback (ground truth)."""
        self.user_rating = rating
        self.user_feedback = feedback
        self.user_edited = edited
        return self

    def set_error(
        self,
        message: str,
        stage: str,
        outcome: GenerationOutcome
    ) -> "FineTuningRecord":
        """Record an error."""
        self.error_message = message
        self.error_stage = stage
        self.outcome = outcome.value
        self.status = RecordStatus.FAILED.value
        return self

    def finalize(
        self,
        outcome: GenerationOutcome = GenerationOutcome.SUCCESS,
        output_files: Optional[List[str]] = None,
        output_format: str = ""
    ) -> "FineTuningRecord":
        """Finalize the record."""
        self.finished_at = datetime.utcnow().isoformat() + "Z"
        self.outcome = outcome.value
        self.output_files = output_files or []
        self.output_format = output_format
        self.status = RecordStatus.FINALIZED.value

        # Calculate duration
        try:
            start = datetime.fromisoformat(self.started_at.rstrip("Z"))
            end = datetime.fromisoformat(self.finished_at.rstrip("Z"))
            self.duration_ms = (end - start).total_seconds() * 1000
        except (ValueError, TypeError):
            pass

        # Calculate complexity score
        self.complexity_score = self._calculate_complexity()

        return self

    def _calculate_complexity(self) -> float:
        """Calculate complexity score from IR."""
        score = 0.0

        # Feature complexity
        score += self.feature_count * 0.15

        # Sketch complexity
        score += self.sketch_count * 0.1

        # Parameter complexity
        score += self.parameter_count * 0.05

        # Feature type diversity (if IR available)
        if self.ir:
            feature_types = set(
                f.get("type") for f in self.ir.get("features", [])
                if f.get("type")
            )
            score += len(feature_types) * 0.15

        return min(score, 1.0)

    def _sanitize_dict(self, d: Any) -> Dict[str, Any]:
        """Ensure dict is JSON-serializable."""
        if d is None:
            return {}
        if not isinstance(d, dict):
            try:
                return dict(d)
            except (TypeError, ValueError):
                return {"_raw": str(d)}

        # Recursively sanitize
        result = {}
        for key, value in d.items():
            if isinstance(value, dict):
                result[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self._sanitize_dict(v) if isinstance(v, dict) else v
                    for v in value
                ]
            elif isinstance(value, (str, int, float, bool, type(None))):
                result[key] = value
            elif hasattr(value, "value"):  # Enum
                result[key] = value.value
            else:
                result[key] = str(value)

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def to_openai_format(self) -> Dict[str, Any]:
        """
        Convert to OpenAI fine-tuning format.

        Format: {"messages": [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}]}
        """
        ir_json = json.dumps(self.ir, sort_keys=True) if self.ir else "{}"

        return {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a CAD generation assistant. Given a prompt describing a 3D model, generate the FeatureGraphIR JSON."
                },
                {
                    "role": "user",
                    "content": self.prompt
                },
                {
                    "role": "assistant",
                    "content": ir_json
                }
            ]
        }

    def to_anthropic_format(self) -> Dict[str, Any]:
        """
        Convert to Anthropic fine-tuning format.

        Format: {"prompt": "Human: ...", "completion": "Assistant: ..."}
        """
        ir_json = json.dumps(self.ir, sort_keys=True) if self.ir else "{}"

        return {
            "prompt": f"Human: Generate a FeatureGraphIR for: {self.prompt}\n\nAssistant:",
            "completion": f" {ir_json}"
        }

    def to_full_format(self) -> Dict[str, Any]:
        """
        Convert to full pipeline format for advanced training.

        Includes all stages: prompt → plan → IR → metrics
        """
        return {
            "record_id": self.record_id,
            "prompt": self.prompt,
            "plan": self.plan,
            "ir": self.ir,
            "validation": self.validation,
            "metrics": {
                "compilation_success": self.compilation_success,
                "compilation_ms": self.compilation_ms,
                "complexity_score": self.complexity_score,
                "feature_count": self.feature_count,
                "validation_errors": self.validation_errors,
                "validation_warnings": self.validation_warnings
            },
            "outcome": self.outcome,
            "user_feedback": {
                "rating": self.user_rating,
                "feedback": self.user_feedback,
                "edited": self.user_edited
            } if self.user_rating or self.user_feedback else None,
            "llm": {
                "model": self.llm_model,
                "tokens_used": self.llm_tokens_used,
                "latency_ms": self.llm_latency_ms
            }
        }


# =============================================================================
# Fine-Tuning Logger
# =============================================================================

class FineTuningLogger:
    """
    Logger for fine-tuning data collection.

    Writes records to JSONL files for training data collection.
    Supports multiple output formats (OpenAI, Anthropic, Full).
    """

    def __init__(
        self,
        output_dir: Path = Path("data/fine_tuning"),
        format: str = "full"  # openai, anthropic, full
    ):
        """
        Initialize logger.

        Args:
            output_dir: Directory for JSONL files
            format: Output format (openai, anthropic, full)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.format = format

        # Create subdirectories
        (self.output_dir / "success").mkdir(exist_ok=True)
        (self.output_dir / "failure").mkdir(exist_ok=True)

        self._records_written = 0

        logger.info(f"FineTuningLogger initialized: dir={output_dir}, format={format}")

    def log(self, record: FineTuningRecord) -> Path:
        """
        Log a fine-tuning record to JSONL file.

        Args:
            record: Finalized FineTuningRecord

        Returns:
            Path to the log file
        """
        # Determine success/failure directory
        subdir = "success" if record.outcome == GenerationOutcome.SUCCESS.value else "failure"

        # Generate filename with date
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"records_{date_str}.jsonl"
        filepath = self.output_dir / subdir / filename

        # Convert to appropriate format
        if self.format == "openai":
            json_record = record.to_openai_format()
        elif self.format == "anthropic":
            json_record = record.to_anthropic_format()
        else:
            json_record = record.to_full_format()

        # Append to JSONL file
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(json_record, ensure_ascii=False, sort_keys=True) + "\n")

        self._records_written += 1
        logger.debug(f"Logged fine-tuning record {record.record_id} to {filepath}")

        return filepath

    def log_raw(self, record: FineTuningRecord) -> Path:
        """
        Log raw record (all fields) for debugging.

        Args:
            record: FineTuningRecord

        Returns:
            Path to the raw log file
        """
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"raw_{date_str}.jsonl"
        filepath = self.output_dir / filename

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")

        return filepath

    def get_statistics(self) -> Dict[str, Any]:
        """Get logging statistics."""
        success_count = 0
        failure_count = 0

        for f in (self.output_dir / "success").glob("*.jsonl"):
            with open(f, "r") as file:
                success_count += sum(1 for _ in file)

        for f in (self.output_dir / "failure").glob("*.jsonl"):
            with open(f, "r") as file:
                failure_count += sum(1 for _ in file)

        return {
            "records_written_session": self._records_written,
            "total_success": success_count,
            "total_failure": failure_count,
            "output_dir": str(self.output_dir),
            "format": self.format
        }


# =============================================================================
# Context Manager for Easy Use
# =============================================================================

class FineTuningContext:
    """
    Context manager for fine-tuning data capture.

    Usage:
        with FineTuningContext(prompt, job_id) as record:
            plan = generate_plan(prompt)
            record.set_plan(plan.to_dict())

            ir = generate_ir(plan)
            record.set_ir(ir.model_dump())

            result = compile(ir)
            record.set_compilation_result(...)

        # Record is automatically logged on exit
    """

    _logger: Optional[FineTuningLogger] = None

    def __init__(
        self,
        prompt: str,
        job_id: str = "",
        session_id: str = "",
        logger_instance: Optional[FineTuningLogger] = None
    ):
        """
        Initialize context.

        Args:
            prompt: User prompt
            job_id: Generation job ID
            session_id: User session ID
            logger_instance: Optional logger instance
        """
        self.record = FineTuningRecord(
            prompt=prompt,
            job_id=job_id,
            session_id=session_id
        )
        self._logger_instance = logger_instance

    def __enter__(self) -> FineTuningRecord:
        return self.record

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Finalize with appropriate outcome
        if exc_type is not None:
            self.record.set_error(
                message=str(exc_val),
                stage="exception",
                outcome=GenerationOutcome.COMPILATION_FAILED
            )
        elif self.record.status != RecordStatus.FINALIZED.value:
            self.record.finalize()

        # Log the record
        log_instance = self._logger_instance or FineTuningContext._logger
        if log_instance:
            log_instance.log(self.record)
            log_instance.log_raw(self.record)

        return False  # Don't suppress exceptions

    @classmethod
    def set_default_logger(cls, log: FineTuningLogger) -> None:
        """Set default logger for all contexts."""
        cls._logger = log


# =============================================================================
# Utility Functions
# =============================================================================

def create_fine_tuning_record(
    prompt: str,
    plan_dict: Optional[Dict] = None,
    ir_dict: Optional[Dict] = None,
    compilation_success: bool = False,
    compilation_ms: float = 0.0,
    validation_result: Optional[Dict] = None,
    outcome: GenerationOutcome = GenerationOutcome.SUCCESS
) -> FineTuningRecord:
    """
    Create a complete fine-tuning record in one call.

    Convenience function for simple use cases.
    """
    record = FineTuningRecord(prompt=prompt)

    if plan_dict:
        record.set_plan(plan_dict)

    if ir_dict:
        record.set_ir(ir_dict)

    record.set_compilation_result(
        success=compilation_success,
        compilation_ms=compilation_ms
    )

    if validation_result:
        record.set_validation(validation_result)

    record.finalize(outcome=outcome)

    return record


def export_for_fine_tuning(
    input_dir: Path,
    output_path: Path,
    format: str = "openai",
    min_complexity: float = 0.2,
    require_success: bool = True
) -> int:
    """
    Export collected records to fine-tuning dataset.

    Args:
        input_dir: Directory with raw JSONL records
        output_path: Output file path
        format: Target format (openai, anthropic)
        min_complexity: Minimum complexity score
        require_success: Only include successful generations

    Returns:
        Number of records exported
    """
    records = []

    # Load all raw records
    for jsonl_file in Path(input_dir).glob("**/*.jsonl"):
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    records.append(data)
                except json.JSONDecodeError:
                    continue

    # Filter records
    filtered = []
    for r in records:
        if require_success and r.get("outcome") != "success":
            continue

        complexity = r.get("metrics", {}).get("complexity_score", 0)
        if complexity < min_complexity:
            continue

        filtered.append(r)

    # Write in target format
    with open(output_path, "w", encoding="utf-8") as f:
        for r in filtered:
            if format == "openai":
                ir_json = json.dumps(r.get("ir", {}), sort_keys=True)
                record = {
                    "messages": [
                        {"role": "system", "content": "Generate FeatureGraphIR from prompt."},
                        {"role": "user", "content": r.get("prompt", "")},
                        {"role": "assistant", "content": ir_json}
                    ]
                }
            else:  # anthropic
                ir_json = json.dumps(r.get("ir", {}), sort_keys=True)
                record = {
                    "prompt": f"Human: {r.get('prompt', '')}\n\nAssistant:",
                    "completion": f" {ir_json}"
                }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"Exported {len(filtered)} records to {output_path}")
    return len(filtered)
