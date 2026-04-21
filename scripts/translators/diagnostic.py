"""Diagnostic script for translator output quality.

Answers one question: is this data teaching the model anything different
from what templates already taught it?

Three metrics, nothing more:
  1. Structural diversity — unique AST hashes after normalizing numbers
  2. Feature distribution — feature count, types, operations
  3. Prompt diversity — unique prompt patterns after normalizing numbers

Usage:
    python scripts/translators/diagnostic.py \
        data/translators/fusion360/deepcad_translated.jsonl \
        data/translators/text2cad/deepcad_translated.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path


def normalize_code(code: str) -> str:
    """Strip numeric values and variable names to get the structural skeleton.

    Keeps: import, with BuildPart/BuildSketch/Locations, shape primitives
    (Rectangle/Circle/Polygon/RectangleRounded/Box/Cylinder),
    extrude calls with mode, plane references.
    Replaces: all numbers with N, all variable names with V.
    """
    # Replace all floating point and integer numbers with N
    s = re.sub(r'-?\d+\.?\d*', 'N', code)
    # Replace variable-like names (depth_1, r_2_3, w_1_1, cx_1_1 etc.) with V
    s = re.sub(r'\b[a-z][a-z_]*_N(?:_N)*\b', 'V', s)
    # Collapse whitespace
    s = re.sub(r'[ \t]+', ' ', s)
    # Remove comment lines
    s = '\n'.join(line for line in s.split('\n')
                  if line.strip() and not line.strip().startswith('#'))
    return s.strip()


def extract_structure(code: str) -> str:
    """Extract only the structural skeleton: shape types + operations in order."""
    patterns = []

    # Find each BuildSketch block with its plane and shapes
    sketch_blocks = re.finditer(
        r'with BuildSketch\(([^)]+)\):', code
    )
    for m in sketch_blocks:
        plane = re.sub(r'-?\d+\.?\d*', 'N', m.group(1)).strip()
        patterns.append(f'SKETCH({plane})')

    # Find shape primitives
    for shape in re.findall(r'(Rectangle|Circle|Polygon|RectangleRounded|Box|Cylinder)\s*\(', code):
        patterns.append(shape)

    # Find extrude operations with their modes
    for m in re.finditer(r'extrude\(([^)]*)\)', code):
        args = m.group(1)
        if 'SUBTRACT' in args:
            patterns.append('EXTRUDE_CUT')
        elif 'INTERSECT' in args:
            patterns.append('EXTRUDE_INTERSECT')
        elif 'both=True' in args:
            patterns.append('EXTRUDE_SYMMETRIC')
        else:
            patterns.append('EXTRUDE_ADD')

    return '|'.join(patterns)


def normalize_prompt(prompt: str) -> str:
    """Normalize a user prompt by replacing numbers with N."""
    s = re.sub(r'-?\d+\.?\d*', 'N', prompt)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def load_samples(paths: list[Path]) -> list[dict]:
    """Load all JSONL samples from multiple files."""
    samples = []
    for p in paths:
        if not p.exists():
            print(f"  WARNING: {p} does not exist, skipping")
            continue
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return samples


def run_diagnostic(samples: list[dict]):
    """Run all three diagnostics and print summary table."""
    if not samples:
        print("No samples loaded!")
        return

    codes = []
    prompts = []
    sources = set()

    for s in samples:
        msgs = s.get('messages', [])
        code = ''
        prompt = ''
        for m in msgs:
            if m['role'] == 'assistant':
                code = m['content']
            elif m['role'] == 'user':
                prompt = m['content']
        codes.append(code)
        prompts.append(prompt)
        sources.add(s.get('source', ''))

    n = len(samples)

    # ---------------------------------------------------------------
    # 1. STRUCTURAL DIVERSITY
    # ---------------------------------------------------------------
    structures = [extract_structure(c) for c in codes]
    normalized_codes = [normalize_code(c) for c in codes]

    unique_structures = set(structures)
    unique_normalized = set(normalized_codes)

    struct_counter = Counter(structures)
    top_5_structures = struct_counter.most_common(5)

    # ---------------------------------------------------------------
    # 2. FEATURE DISTRIBUTION
    # ---------------------------------------------------------------
    feature_counts = []
    shape_types = Counter()
    op_types = Counter()
    has_cut = 0
    has_polygon = 0

    for code in codes:
        # Count features by counting extrude() calls
        extrudes = re.findall(r'extrude\(', code)
        n_feat = len(extrudes)
        feature_counts.append(n_feat)

        # Count shape types
        for shape in re.findall(r'(Rectangle|Circle|Polygon|RectangleRounded|Box|Cylinder)\s*\(', code):
            shape_types[shape] += 1

        # Count operations
        for m in re.finditer(r'extrude\(([^)]*)\)', code):
            args = m.group(1)
            if 'SUBTRACT' in args:
                op_types['CUT'] += 1
                has_cut += 1
            elif 'INTERSECT' in args:
                op_types['INTERSECT'] += 1
            else:
                op_types['ADD'] += 1

        if 'Polygon' in code:
            has_polygon += 1

    fc = Counter(feature_counts)

    # ---------------------------------------------------------------
    # 3. PROMPT DIVERSITY
    # ---------------------------------------------------------------
    normalized_prompts = [normalize_prompt(p) for p in prompts]
    unique_prompts = set(normalized_prompts)
    prompt_counter = Counter(normalized_prompts)
    top_5_prompts = prompt_counter.most_common(5)

    # Vocabulary diversity
    all_words = ' '.join(prompts).lower().split()
    unique_words = set(all_words)

    # Average prompt length
    avg_len = sum(len(p.split()) for p in prompts) / n if n else 0

    # ---------------------------------------------------------------
    # PRINT SUMMARY TABLE
    # ---------------------------------------------------------------
    print()
    print('=' * 64)
    print('  DATASET DIAGNOSTIC SUMMARY')
    print('=' * 64)
    print(f'  Total samples:         {n}')
    print(f'  Unique sources:        {len(sources)}')
    print()

    print('-' * 64)
    print('  1. STRUCTURAL DIVERSITY')
    print('-' * 64)
    print(f'  Unique AST structures: {len(unique_structures)} / {n}  '
          f'({len(unique_structures)/n*100:.1f}%)')
    print(f'  Unique normalized code:{len(unique_normalized)} / {n}  '
          f'({len(unique_normalized)/n*100:.1f}%)')
    print()
    print('  Top 5 most common structures:')
    for struct, count in top_5_structures:
        pct = count / n * 100
        print(f'    {count:4d} ({pct:5.1f}%)  {struct[:70]}')

    print()
    print('-' * 64)
    print('  2. FEATURE DISTRIBUTION')
    print('-' * 64)
    print('  Features per sample:')
    for nf in sorted(fc.keys()):
        count = fc[nf]
        bar = '#' * min(count // 2, 40)
        print(f'    {nf} feature(s): {count:4d} ({count/n*100:5.1f}%)  {bar}')

    print()
    print('  Shape types used:')
    for shape, count in shape_types.most_common():
        print(f'    {shape:20s}: {count:4d}')

    print()
    print('  Operation types:')
    for op, count in op_types.most_common():
        print(f'    {op:20s}: {count:4d} ({count/sum(op_types.values())*100:.1f}%)')

    print(f'\n  Samples with cuts:     {has_cut} / {n} ({has_cut/n*100:.1f}%)')
    print(f'  Samples with polygons: {has_polygon} / {n} ({has_polygon/n*100:.1f}%)')

    print()
    print('-' * 64)
    print('  3. PROMPT DIVERSITY')
    print('-' * 64)
    print(f'  Unique prompts (after normalizing numbers): '
          f'{len(unique_prompts)} / {n}  ({len(unique_prompts)/n*100:.1f}%)')
    print(f'  Unique vocabulary:     {len(unique_words)} words')
    print(f'  Avg prompt length:     {avg_len:.1f} words')
    print()
    print('  Top 5 most common prompt patterns:')
    for prompt, count in top_5_prompts:
        pct = count / n * 100
        truncated = prompt[:72] + ('...' if len(prompt) > 72 else '')
        print(f'    {count:4d} ({pct:5.1f}%)  "{truncated}"')

    print()
    print('=' * 64)
    print('  VERDICT')
    print('=' * 64)

    # Automated verdict
    struct_ratio = len(unique_structures) / n
    prompt_ratio = len(unique_prompts) / n
    cut_ratio = has_cut / n if n else 0
    multi_feat = sum(1 for fc_val in feature_counts if fc_val >= 3) / n if n else 0

    issues = []
    if struct_ratio < 0.3:
        issues.append(f'LOW structural diversity ({struct_ratio:.1%} unique)')
    if prompt_ratio < 0.1:
        issues.append(f'VERY LOW prompt diversity ({prompt_ratio:.1%} unique)')
    if cut_ratio < 0.1:
        issues.append(f'Cuts underrepresented ({cut_ratio:.1%})')
    if multi_feat < 0.1:
        issues.append(f'Complex parts (3+ features) underrepresented ({multi_feat:.1%})')

    if not issues:
        print('  Data looks healthy for this sample size.')
    else:
        print('  Issues found:')
        for issue in issues:
            print(f'    - {issue}')

    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnostic.py <file1.jsonl> [file2.jsonl ...]")
        sys.exit(1)

    paths = [Path(p) for p in sys.argv[1:]]
    print(f"Loading samples from {len(paths)} file(s)...")
    samples = load_samples(paths)
    print(f"Loaded {len(samples)} total samples")
    run_diagnostic(samples)


if __name__ == '__main__':
    main()
