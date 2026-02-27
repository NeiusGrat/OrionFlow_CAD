"""Orchestrator: build final training JSONL from all sources."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .deepcad_converter import DeepCADConverter
from .synthetic_generator import SyntheticGenerator
from .text_annotator import TextAnnotator
from .validator import OFLValidator


# ---- top-level worker (must be module-level for pickle) -----------------
def _convert_one_model(
    file_path: str,
    scale: float,
    text_annotation: str | None,
) -> dict:
    """Process a single DeepCAD JSON file -> result dict.

    Returns:
        dict with keys: model_id, ok, code (optional), texts (optional).
    """
    fp = Path(file_path)
    model_id = fp.stem
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {"model_id": model_id, "ok": False}

    converter = DeepCADConverter(scale=scale)
    code = converter.convert(data, model_id=model_id)
    if code is None:
        return {"model_id": model_id, "ok": False}

    if text_annotation is not None:
        texts = [text_annotation]
    else:
        annotator = TextAnnotator()
        texts = annotator.annotate_from_code(code)

    return {"model_id": model_id, "ok": True, "code": code, "texts": texts}


class DatasetBuilder:
    """Builds the final training_pairs.jsonl from all sources."""

    def __init__(self, output_dir: str = "data/training"):
        self.converter = DeepCADConverter()
        self.generator = SyntheticGenerator()
        self.annotator = TextAnnotator()
        self.validator = OFLValidator()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # DeepCAD source
    # ------------------------------------------------------------------
    def build_from_deepcad(
        self,
        deepcad_dir: str,
        text_annotations: dict | None = None,
        limit: int = 0,
        offset: int = 0,
        log_every: int = 100,
        workers: int = 1,
    ) -> str:
        """Convert DeepCAD models -> OFL, pair with text, save JSONL.

        Streams pairs directly to disk (no in-memory accumulation).
        Writes a checkpoint file after each model for crash recovery.
        Logs progress every ``log_every`` models.

        Args:
            deepcad_dir: Directory containing DeepCAD JSON files.
            text_annotations: Optional dict mapping model_id -> text.
            limit: Max number of files to process (0 = all remaining).
            offset: Index to start processing from (for chunked runs).
            log_every: Print progress every N models processed.
            workers: Number of parallel workers (1 = sequential).
        """
        json_files = sorted(Path(deepcad_dir).glob("*.json"))

        total_files = len(json_files)

        if offset < 0:
            raise ValueError("offset must be >= 0")

        if offset >= total_files:
            print("Offset beyond dataset size. Nothing to process.")
            return ""

        if limit > 0:
            json_files = json_files[offset : offset + limit]
        else:
            json_files = json_files[offset:]

        chunk_name = f"deepcad_pairs_offset{offset}_limit{limit or 'all'}.jsonl"
        out_path = os.path.join(self.output_dir, chunk_name)
        checkpoint_path = out_path + ".checkpoint"

        # ---- crash-resume: skip already-processed models ----------------
        completed: set[str] = set()
        resume_mode = False
        if os.path.exists(checkpoint_path):
            with open(checkpoint_path, "r", encoding="utf-8") as cp:
                for line in cp:
                    completed.add(line.strip())
            resume_mode = True
            print(f"Resuming: {len(completed)} models already processed.")

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        converted = 0
        skipped = 0
        pairs_written = 0
        chunk_size = len(json_files)

        # filter out already-checkpointed files
        pending_files = [
            jf for jf in json_files if jf.stem not in completed
        ]

        if workers > 1:
            pairs_written, converted, skipped = self._run_parallel(
                pending_files, text_annotations, out_path,
                checkpoint_path, resume_mode, log_every, workers,
            )
        else:
            pairs_written, converted, skipped = self._run_sequential(
                pending_files, text_annotations, out_path,
                checkpoint_path, resume_mode, log_every,
            )

        # final report
        report = {
            "chunk_name": chunk_name,
            "total_in_chunk": chunk_size,
            "converted": converted,
            "skipped": skipped,
            "pairs_written": pairs_written,
            "offset": offset,
            "limit": limit,
            "workers": workers,
            "resumed": resume_mode,
        }
        report_path = out_path.replace(".jsonl", "_report.json")
        Path(report_path).write_text(json.dumps(report, indent=2))
        print(
            f"DeepCAD: {converted} converted, {skipped} skipped, "
            f"{pairs_written} pairs -> {out_path}"
        )

        # clean up checkpoint on successful completion
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

        return out_path

    # ------------------------------------------------------------------
    # Sequential path (workers=1)
    # ------------------------------------------------------------------
    def _run_sequential(
        self,
        pending_files: list[Path],
        text_annotations: dict | None,
        out_path: str,
        checkpoint_path: str,
        resume_mode: bool,
        log_every: int,
    ) -> tuple[int, int, int]:
        """Process models one-by-one, streaming to disk."""
        converted = 0
        skipped = 0
        pairs_written = 0
        chunk_size = len(pending_files)

        write_mode = "a" if resume_mode else "w"
        with open(out_path, write_mode, encoding="utf-8") as out_f, \
             open(checkpoint_path, "a", encoding="utf-8") as cp_f:

            for jf in pending_files:
                model_id = jf.stem

                try:
                    data = json.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    skipped += 1
                    cp_f.write(model_id + "\n")
                    cp_f.flush()
                    continue

                code = self.converter.convert(data, model_id=model_id)
                if code is None:
                    skipped += 1
                    cp_f.write(model_id + "\n")
                    cp_f.flush()
                    continue

                converted += 1

                if text_annotations and model_id in text_annotations:
                    texts = [text_annotations[model_id]]
                else:
                    texts = self.annotator.annotate_from_code(code)

                for text in texts:
                    pair = {
                        "text": text,
                        "code": code,
                        "source": "deepcad",
                        "complexity": self._estimate_complexity(code),
                    }
                    out_f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    pairs_written += 1

                out_f.flush()
                cp_f.write(model_id + "\n")
                cp_f.flush()

                processed = converted + skipped
                if log_every > 0 and processed % log_every == 0:
                    print(
                        f"[progress] {processed}/{chunk_size} "
                        f"({converted} ok, {skipped} skip, "
                        f"{pairs_written} pairs written)"
                    )

        return pairs_written, converted, skipped

    # ------------------------------------------------------------------
    # Parallel path (workers>1)
    # ------------------------------------------------------------------
    def _run_parallel(
        self,
        pending_files: list[Path],
        text_annotations: dict | None,
        out_path: str,
        checkpoint_path: str,
        resume_mode: bool,
        log_every: int,
        workers: int,
    ) -> tuple[int, int, int]:
        """Process models in parallel via ProcessPoolExecutor.

        Uses executor.map() for deterministic (submission-order) output.
        Main process handles all I/O - no file-handle contention.
        """
        converted = 0
        skipped = 0
        pairs_written = 0
        chunk_size = len(pending_files)

        # build args for each worker call
        scale = self.converter.scale
        worker_args = [
            (
                str(jf),
                scale,
                (text_annotations or {}).get(jf.stem),
            )
            for jf in pending_files
        ]

        write_mode = "a" if resume_mode else "w"
        with open(out_path, write_mode, encoding="utf-8") as out_f, \
             open(checkpoint_path, "a", encoding="utf-8") as cp_f:

            if chunk_size == 0:
                return pairs_written, converted, skipped

            print(f"[parallel] Starting {workers} workers for {chunk_size} models")

            def _write_result(result: dict) -> tuple[int, int]:
                model_id = result["model_id"]

                if not result["ok"]:
                    cp_f.write(model_id + "\n")
                    cp_f.flush()
                    return 0, 1

                code = result["code"]
                written = 0
                for text in result["texts"]:
                    pair = {
                        "text": text,
                        "code": code,
                        "source": "deepcad",
                        "complexity": self._estimate_complexity(code),
                    }
                    out_f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    written += 1

                out_f.flush()
                cp_f.write(model_id + "\n")
                cp_f.flush()
                return written, 0

            try:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    results = executor.map(
                        _convert_one_model,
                        *zip(*worker_args),
                    )

                    for result in results:
                        wrote, did_skip = _write_result(result)
                        pairs_written += wrote
                        if did_skip:
                            skipped += 1
                        else:
                            converted += 1

                        processed = converted + skipped
                        if log_every > 0 and processed % log_every == 0:
                            print(
                                f"[progress] {processed}/{chunk_size} "
                                f"({converted} ok, {skipped} skip, "
                                f"{pairs_written} pairs written)"
                            )
            except (PermissionError, OSError) as exc:
                print(f"[parallel] unavailable ({exc}); falling back to sequential")
                for jf in pending_files:
                    result = _convert_one_model(
                        str(jf),
                        scale,
                        (text_annotations or {}).get(jf.stem),
                    )
                    wrote, did_skip = _write_result(result)
                    pairs_written += wrote
                    if did_skip:
                        skipped += 1
                    else:
                        converted += 1

                    processed = converted + skipped
                    if log_every > 0 and processed % log_every == 0:
                        print(
                            f"[progress] {processed}/{chunk_size} "
                            f"({converted} ok, {skipped} skip, "
                            f"{pairs_written} pairs written)"
                        )
        return pairs_written, converted, skipped

    # ------------------------------------------------------------------
    # Synthetic source
    # ------------------------------------------------------------------
    def build_synthetic(self, num_samples: int = 5000) -> str:
        """Generate synthetic training pairs, save JSONL."""
        pairs = self.generator.generate_batch(num_samples)
        out_path = os.path.join(self.output_dir, "synthetic_pairs.jsonl")
        self._write_jsonl(pairs, out_path)

        report = {
            "total_generated": len(pairs),
            "template_counts": {},
        }
        for p in pairs:
            t = p.get("template", "unknown")
            report["template_counts"][t] = report["template_counts"].get(t, 0) + 1
        report_path = os.path.join(self.output_dir, "generation_report.json")
        Path(report_path).write_text(json.dumps(report, indent=2))
        print(f"Synthetic: {len(pairs)} pairs generated")
        return out_path

    # ------------------------------------------------------------------
    # Examples source
    # ------------------------------------------------------------------
    def build_from_examples(self, examples_dir: str = "orionflow_ofl/examples/") -> str:
        """Convert hand-written examples into training pairs (5 texts each)."""
        examples_path = Path(examples_dir)
        py_files = sorted(examples_path.glob("*.py"))
        pairs: list[dict] = []

        for pf in py_files:
            code_raw = pf.read_text(encoding="utf-8")
            # strip sys.path and print lines for training data
            code = self._clean_example_code(code_raw)
            if "export(" not in code:
                continue
            texts = self.annotator.annotate_from_code(code)
            for text in texts:
                pairs.append({
                    "text": text,
                    "code": code,
                    "source": "example",
                    "complexity": self._estimate_complexity(code),
                })

        out_path = os.path.join(self.output_dir, "example_pairs.jsonl")
        self._write_jsonl(pairs, out_path)
        print(f"Examples: {len(py_files)} scripts -> {len(pairs)} pairs")
        return out_path

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    def merge_and_deduplicate(self, jsonl_files: list[str], output: str) -> dict:
        """Merge multiple JSONL files, deduplicate by code hash, shuffle."""
        seen_hashes: set[str] = set()
        all_pairs: list[dict] = []

        for fpath in jsonl_files:
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    pair = json.loads(line)
                    h = hashlib.md5((pair["text"] + pair["code"]).encode()).hexdigest()
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        all_pairs.append(pair)

        random.shuffle(all_pairs)
        self._write_jsonl(all_pairs, output)

        source_counts: dict[str, int] = {}
        for p in all_pairs:
            s = p.get("source", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1

        stats = {
            "total_pairs": len(all_pairs),
            "deduplicated": True,
            "source_breakdown": source_counts,
        }
        stats_path = output.replace(".jsonl", "_stats.json")
        Path(stats_path).write_text(json.dumps(stats, indent=2))
        print(f"Merged: {len(all_pairs)} unique pairs")
        return stats

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _write_jsonl(self, pairs: list[dict], path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    def _clean_example_code(self, code: str) -> str:
        """Remove sys.path hacks, docstrings, and print statements."""
        lines = []
        in_docstring = False
        for line in code.splitlines():
            stripped = line.strip()
            # skip sys.path, import sys, pathlib import
            if stripped.startswith("sys.path"):
                continue
            if stripped == "import sys":
                continue
            if stripped.startswith("from pathlib"):
                continue
            if stripped.startswith("print("):
                continue
            # skip docstrings
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if in_docstring:
                    in_docstring = False
                    continue
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = True
                    continue
                # single-line docstring
                continue
            if in_docstring:
                continue
            lines.append(line)

        # strip leading blank lines
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines)

    def _estimate_complexity(self, code: str) -> int:
        score = 1
        if "Hole(" in code:
            score += 1
        if ".at_circular(" in code:
            score += 1
        hole_count = code.count("part -=")
        if hole_count >= 2:
            score += 1
        if hole_count >= 3:
            score += 1
        return min(score, 5)
