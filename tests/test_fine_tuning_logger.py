"""
Tests for Fine-Tuning Logger (STEP 6).

Tests structured pipeline capture for LLM fine-tuning:
1. Record creation and lifecycle
2. Pipeline stage capture (prompt → plan → IR → metrics)
3. Multiple output formats (OpenAI, Anthropic, Full)
4. JSONL file writing
5. Statistics and filtering
6. Context manager usage
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

from app.logging.fine_tuning_logger import (
    FineTuningRecord,
    FineTuningLogger,
    FineTuningContext,
    RecordStatus,
    GenerationOutcome,
    create_fine_tuning_record,
    export_for_fine_tuning
)


# =============================================================================
# Test FineTuningRecord
# =============================================================================

class TestFineTuningRecord:
    """Tests for FineTuningRecord."""

    def test_record_initialization(self):
        """Record should initialize with defaults."""
        record = FineTuningRecord(prompt="Create a box")
        assert record.prompt == "Create a box"
        assert record.record_id.startswith("ftr_")
        assert record.status == RecordStatus.STARTED.value
        assert record.started_at != ""

    def test_set_plan(self):
        """Should capture ConstructionPlan."""
        record = FineTuningRecord(prompt="test")
        plan_dict = {
            "id": "plan_123",
            "construction_sequence": [
                {"order": 1, "description": "Create sketch"}
            ],
            "parameters": {"width": 50.0}
        }

        record.set_plan(plan_dict, generation_ms=120.0, source="LLM")

        assert record.plan is not None
        assert record.plan_generation_ms == 120.0
        assert record.plan_source == "LLM"
        assert record.status == RecordStatus.PLAN_SET.value

    def test_set_ir(self):
        """Should capture FeatureGraphIR."""
        record = FineTuningRecord(prompt="test")
        ir_dict = {
            "version": "1.0-IR",
            "features": [
                {"id": "f1", "type": "extrude", "params": {"depth": 10.0}}
            ],
            "sketches": [
                {"id": "s1", "primitives": []}
            ],
            "parameters": {"depth": 10.0}
        }

        record.set_ir(ir_dict, generation_ms=50.0)

        assert record.ir is not None
        assert record.feature_count == 1
        assert record.sketch_count == 1
        assert record.parameter_count == 1
        assert record.ir_version == "1.0-IR"
        assert record.status == RecordStatus.IR_SET.value

    def test_set_compilation_result(self):
        """Should capture compilation metrics."""
        record = FineTuningRecord(prompt="test")
        record.set_compilation_result(
            success=True,
            compilation_ms=230.5,
            compiled_features=3,
            cache_hits=2,
            cache_misses=1
        )

        assert record.compilation_success is True
        assert record.compilation_ms == 230.5
        assert record.compiled_features == 3
        assert record.cache_hits == 2
        assert record.cache_misses == 1
        assert record.status == RecordStatus.COMPILED.value

    def test_set_validation(self):
        """Should capture validation results."""
        record = FineTuningRecord(prompt="test")
        validation_result = {
            "is_valid": True,
            "errors": 0,
            "warnings": 2,
            "issues": [
                {"severity": "WARNING", "message": "Small fillet radius"}
            ]
        }

        record.set_validation(validation_result)

        assert record.validation is not None
        assert record.validation_errors == 0
        assert record.validation_warnings == 2

    def test_set_llm_metadata(self):
        """Should capture LLM metadata."""
        record = FineTuningRecord(prompt="test")
        record.set_llm_metadata(
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            tokens_used=1500,
            latency_ms=850.0
        )

        assert record.llm_model == "llama-3.3-70b-versatile"
        assert record.llm_temperature == 0.7
        assert record.llm_tokens_used == 1500
        assert record.llm_latency_ms == 850.0

    def test_set_user_feedback(self):
        """Should capture user feedback."""
        record = FineTuningRecord(prompt="test")
        record.set_user_feedback(
            rating=5,
            feedback="Perfect result!",
            edited=False
        )

        assert record.user_rating == 5
        assert record.user_feedback == "Perfect result!"
        assert record.user_edited is False

    def test_set_error(self):
        """Should capture error details."""
        record = FineTuningRecord(prompt="test")
        record.set_error(
            message="Compilation failed: negative depth",
            stage="compilation",
            outcome=GenerationOutcome.COMPILATION_FAILED
        )

        assert record.error_message == "Compilation failed: negative depth"
        assert record.error_stage == "compilation"
        assert record.outcome == GenerationOutcome.COMPILATION_FAILED.value
        assert record.status == RecordStatus.FAILED.value

    def test_finalize(self):
        """Should finalize record with outcome."""
        record = FineTuningRecord(prompt="test")
        record.finalize(
            outcome=GenerationOutcome.SUCCESS,
            output_files=["output.step", "output.glb"],
            output_format="STEP"
        )

        assert record.finished_at != ""
        assert record.outcome == GenerationOutcome.SUCCESS.value
        assert record.output_files == ["output.step", "output.glb"]
        assert record.output_format == "STEP"
        assert record.status == RecordStatus.FINALIZED.value
        assert record.duration_ms >= 0

    def test_complexity_calculation(self):
        """Should calculate complexity score."""
        record = FineTuningRecord(prompt="test")
        record.set_ir({
            "version": "1.0-IR",
            "features": [
                {"id": "f1", "type": "extrude"},
                {"id": "f2", "type": "fillet"}
            ],
            "sketches": [{"id": "s1"}],
            "parameters": {"width": 10, "height": 20}
        })
        record.finalize()

        # 2 features * 0.15 + 1 sketch * 0.1 + 2 params * 0.05 + 2 types * 0.15
        expected = min(2*0.15 + 1*0.1 + 2*0.05 + 2*0.15, 1.0)
        assert abs(record.complexity_score - expected) < 0.01


# =============================================================================
# Test Output Formats
# =============================================================================

class TestOutputFormats:
    """Tests for different output formats."""

    @pytest.fixture
    def complete_record(self):
        """Create a complete record."""
        record = FineTuningRecord(prompt="Create a 50mm cube")
        record.set_plan({
            "construction_sequence": [{"order": 1, "description": "Extrude"}]
        })
        record.set_ir({
            "version": "1.0-IR",
            "features": [{"id": "f1", "type": "extrude", "params": {"depth": 50.0}}],
            "sketches": [],
            "parameters": {}
        })
        record.finalize(outcome=GenerationOutcome.SUCCESS)
        return record

    def test_to_dict(self, complete_record):
        """Should convert to dict."""
        d = complete_record.to_dict()
        assert isinstance(d, dict)
        assert d["prompt"] == "Create a 50mm cube"
        assert d["record_id"].startswith("ftr_")

    def test_to_json(self, complete_record):
        """Should convert to JSON string."""
        json_str = complete_record.to_json()
        assert isinstance(json_str, str)

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["prompt"] == "Create a 50mm cube"

    def test_to_openai_format(self, complete_record):
        """Should convert to OpenAI format."""
        openai_format = complete_record.to_openai_format()

        assert "messages" in openai_format
        assert len(openai_format["messages"]) == 3

        assert openai_format["messages"][0]["role"] == "system"
        assert openai_format["messages"][1]["role"] == "user"
        assert openai_format["messages"][1]["content"] == "Create a 50mm cube"
        assert openai_format["messages"][2]["role"] == "assistant"

    def test_to_anthropic_format(self, complete_record):
        """Should convert to Anthropic format."""
        anthropic_format = complete_record.to_anthropic_format()

        assert "prompt" in anthropic_format
        assert "completion" in anthropic_format
        assert "Create a 50mm cube" in anthropic_format["prompt"]
        assert "Human:" in anthropic_format["prompt"]
        assert "Assistant:" in anthropic_format["prompt"]

    def test_to_full_format(self, complete_record):
        """Should convert to full format."""
        full_format = complete_record.to_full_format()

        assert "record_id" in full_format
        assert "prompt" in full_format
        assert "plan" in full_format
        assert "ir" in full_format
        assert "metrics" in full_format
        assert "outcome" in full_format

        metrics = full_format["metrics"]
        assert "compilation_success" in metrics
        assert "complexity_score" in metrics


# =============================================================================
# Test FineTuningLogger
# =============================================================================

class TestFineTuningLogger:
    """Tests for FineTuningLogger."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for logging."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def logger_openai(self, temp_dir):
        """Create logger with OpenAI format."""
        return FineTuningLogger(output_dir=temp_dir, format="openai")

    @pytest.fixture
    def logger_full(self, temp_dir):
        """Create logger with full format."""
        return FineTuningLogger(output_dir=temp_dir, format="full")

    def test_logger_initialization(self, temp_dir):
        """Logger should initialize with directories."""
        logger = FineTuningLogger(output_dir=temp_dir)

        assert (temp_dir / "success").exists()
        assert (temp_dir / "failure").exists()

    def test_log_success_record(self, logger_openai):
        """Should log successful generation."""
        record = FineTuningRecord(prompt="Create a cylinder")
        record.set_ir({"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}})
        record.finalize(outcome=GenerationOutcome.SUCCESS)

        filepath = logger_openai.log(record)

        assert filepath.exists()
        assert "success" in str(filepath)

        # Verify content
        with open(filepath, "r") as f:
            line = f.readline()
            data = json.loads(line)
            assert "messages" in data  # OpenAI format

    def test_log_failure_record(self, logger_full):
        """Should log failed generation."""
        record = FineTuningRecord(prompt="Invalid prompt")
        record.set_error(
            message="Compilation failed",
            stage="compilation",
            outcome=GenerationOutcome.COMPILATION_FAILED
        )
        record.finalize(outcome=GenerationOutcome.COMPILATION_FAILED)

        filepath = logger_full.log(record)

        assert filepath.exists()
        assert "failure" in str(filepath)

    def test_log_raw_record(self, logger_full):
        """Should log raw record with all fields."""
        record = FineTuningRecord(prompt="Test")
        record.finalize()

        filepath = logger_full.log_raw(record)

        assert filepath.exists()
        assert "raw" in str(filepath)

        # Verify all fields are present
        with open(filepath, "r") as f:
            line = f.readline()
            data = json.loads(line)
            assert "record_id" in data
            assert "started_at" in data
            assert "finished_at" in data

    def test_multiple_logs_append(self, logger_openai):
        """Multiple logs should append to same file."""
        record1 = FineTuningRecord(prompt="Test 1")
        record1.finalize(outcome=GenerationOutcome.SUCCESS)

        record2 = FineTuningRecord(prompt="Test 2")
        record2.finalize(outcome=GenerationOutcome.SUCCESS)

        filepath1 = logger_openai.log(record1)
        filepath2 = logger_openai.log(record2)

        # Should be same file (same date)
        assert filepath1 == filepath2

        # Should have 2 lines
        with open(filepath1, "r") as f:
            lines = f.readlines()
            assert len(lines) == 2

    def test_get_statistics(self, logger_full):
        """Should return logging statistics."""
        # Log some records
        for i in range(3):
            record = FineTuningRecord(prompt=f"Test {i}")
            record.finalize(outcome=GenerationOutcome.SUCCESS)
            logger_full.log(record)

        for i in range(2):
            record = FineTuningRecord(prompt=f"Fail {i}")
            record.finalize(outcome=GenerationOutcome.COMPILATION_FAILED)
            logger_full.log(record)

        stats = logger_full.get_statistics()

        assert stats["total_success"] == 3
        assert stats["total_failure"] == 2
        assert stats["format"] == "full"


# =============================================================================
# Test Context Manager
# =============================================================================

class TestFineTuningContext:
    """Tests for FineTuningContext."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_context_manager_basic_usage(self, temp_dir):
        """Should capture record in context."""
        logger = FineTuningLogger(output_dir=temp_dir)
        FineTuningContext.set_default_logger(logger)

        with FineTuningContext("Create a box", job_id="job_123") as record:
            assert record.prompt == "Create a box"
            assert record.job_id == "job_123"
            record.set_ir({"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}})

        # Should be logged automatically
        stats = logger.get_statistics()
        assert stats["records_written_session"] == 1

    def test_context_manager_with_exception(self, temp_dir):
        """Should capture errors in context."""
        logger = FineTuningLogger(output_dir=temp_dir)

        try:
            with FineTuningContext("Test", logger_instance=logger) as record:
                record.set_ir({"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}})
                raise ValueError("Test error")
        except ValueError:
            pass

        # Should still be logged with error
        stats = logger.get_statistics()
        assert stats["total_failure"] == 1

    def test_context_manager_auto_finalize(self, temp_dir):
        """Should auto-finalize on exit."""
        logger = FineTuningLogger(output_dir=temp_dir)

        with FineTuningContext("Test", logger_instance=logger) as record:
            record.set_ir({"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}})
            # Don't manually finalize

        # Should be finalized automatically
        assert record.status == RecordStatus.FINALIZED.value


# =============================================================================
# Test Utility Functions
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_create_fine_tuning_record(self):
        """Should create complete record in one call."""
        record = create_fine_tuning_record(
            prompt="Create a box",
            plan_dict={"construction_sequence": []},
            ir_dict={"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}},
            compilation_success=True,
            compilation_ms=150.0,
            validation_result={"is_valid": True, "errors": 0, "warnings": 0},
            outcome=GenerationOutcome.SUCCESS
        )

        assert record.prompt == "Create a box"
        assert record.plan is not None
        assert record.ir is not None
        assert record.compilation_success is True
        assert record.status == RecordStatus.FINALIZED.value

    def test_export_for_fine_tuning(self, tmp_path):
        """Should export records to training dataset."""
        # Create some raw records
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()

        records = []
        for i in range(5):
            record = {
                "prompt": f"Prompt {i}",
                "ir": {"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}},
                "outcome": "success",
                "metrics": {"complexity_score": 0.5 + i * 0.1}
            }
            records.append(record)

        # Write raw JSONL
        raw_file = raw_dir / "records.jsonl"
        with open(raw_file, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        # Export
        output_path = tmp_path / "train.jsonl"
        count = export_for_fine_tuning(
            input_dir=raw_dir,
            output_path=output_path,
            format="openai",
            min_complexity=0.6,
            require_success=True
        )

        # Should filter to 4 records (complexity >= 0.6)
        assert count == 4

        # Verify format
        with open(output_path, "r") as f:
            lines = f.readlines()
            assert len(lines) == 4

            first = json.loads(lines[0])
            assert "messages" in first


# =============================================================================
# Test JSON Serialization
# =============================================================================

class TestJSONSerialization:
    """Tests for JSON serialization requirements."""

    def test_record_is_json_serializable(self):
        """Record should be fully JSON-serializable."""
        record = FineTuningRecord(prompt="Test")
        record.set_plan({"test": "value"})
        record.set_ir({"version": "1.0-IR", "features": [], "sketches": [], "parameters": {}})
        record.finalize()

        # Should serialize without errors
        json_str = json.dumps(record.to_dict(), sort_keys=True)
        assert isinstance(json_str, str)

        # Should deserialize
        parsed = json.loads(json_str)
        assert parsed["prompt"] == "Test"

    def test_enum_values_serialized_as_strings(self):
        """Enums should serialize as string values."""
        record = FineTuningRecord(prompt="Test")
        record.finalize(outcome=GenerationOutcome.SUCCESS)

        d = record.to_dict()
        assert isinstance(d["status"], str)
        assert isinstance(d["outcome"], str)

    def test_nested_dicts_sanitized(self):
        """Nested dicts should be sanitized."""
        record = FineTuningRecord(prompt="Test")
        record.set_plan({
            "nested": {
                "deeply": {
                    "nested": "value"
                }
            }
        })

        d = record.to_dict()
        assert d["plan"]["nested"]["deeply"]["nested"] == "value"


# =============================================================================
# Test Pipeline Integration
# =============================================================================

class TestPipelineIntegration:
    """Tests for full pipeline integration."""

    def test_full_pipeline_capture(self, tmp_path):
        """Should capture entire pipeline flow."""
        logger = FineTuningLogger(output_dir=tmp_path, format="full")

        with FineTuningContext("Create a 50mm cube", job_id="job_xyz", logger_instance=logger) as record:
            # Stage 1: Planning
            plan = {
                "construction_sequence": [
                    {"order": 1, "description": "Create base sketch"},
                    {"order": 2, "description": "Extrude to depth"}
                ],
                "parameters": {"size": 50.0}
            }
            record.set_plan(plan, generation_ms=120.0, source="LLM")

            # Stage 2: IR Generation
            ir = {
                "version": "1.0-IR",
                "units": "mm",
                "parameters": {"size": 50.0},
                "sketches": [{"id": "s1", "primitives": []}],
                "features": [{"id": "f1", "type": "extrude", "params": {"depth": 50.0}}]
            }
            record.set_ir(ir, generation_ms=50.0)

            # Stage 3: Compilation
            record.set_compilation_result(
                success=True,
                compilation_ms=200.0,
                compiled_features=1
            )

            # Stage 4: Validation
            record.set_validation({
                "is_valid": True,
                "errors": 0,
                "warnings": 0
            })

            # Stage 5: Metadata
            record.set_llm_metadata(
                model="llama-3.3-70b",
                temperature=0.7,
                tokens_used=1200,
                latency_ms=300.0
            )

        # Verify logged
        log_file = tmp_path / "success" / f"records_{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl"
        assert log_file.exists()

        with open(log_file, "r") as f:
            data = json.loads(f.readline())
            assert data["prompt"] == "Create a 50mm cube"
            assert data["plan"] is not None
            assert data["ir"] is not None
            assert data["metrics"]["compilation_success"] is True
