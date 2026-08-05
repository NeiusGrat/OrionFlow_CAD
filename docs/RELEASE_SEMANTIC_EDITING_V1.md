# Semantic Editing V1 — Release Baseline

Status: **RELEASED.** Backend and frontend both in production, tagged
`semantic-editing-v1` at commit `9f72473`.
Date: 2026-08-04.

Depth on any section below: `docs/SEMANTIC_CAD_ARCHITECTURE.md`.

---

## 1. Architecture

```
  prompt ──► Blueprint ──► freeze (sha256) ──► resolve ──► FreeCAD ──► measure
                 │                                            │           │
                 │                                            ▼           ▼
                 │                                    topology.json   assertions
                 │                                            │           │
                 └──────────── re-graded against ◄────────────┴───────────┘

  click ──► triangle ──► CAD face ──► Blueprint feature ──► parameter ──► edit
            (faceMap)   (element map)   (semantic_edit)      (plan)     (rebuild)
```

Three identities, deliberately not collapsed:

| Identity | Survives | Example |
|---|---|---|
| Blueprint feature id | a redesign | `bore` |
| Stable selector | a rebuild | `@bore.f0` |
| Artifact selector | nothing — one build | `#o1.s1.f11` |
| Geometry selector | a rebuild, by position | `near:30,20,10` |

The load-bearing property is that **the model never chooses a number**.
`orion/reasoning.py` decides dimensions deterministically; the Blueprint freezes
them; the assertions grade the result against what was frozen.

---

## 2. Implemented capabilities

**Provenance.** Every build writes `manifest.json` with per-file sha256, the
`blueprint_hash` it was authorised against, the builder SHA, and the FreeCAD
version reported by the container that compiled. Serving checks size always,
sha256 on `?verify=1`; a mismatch is 409.

**Topology.** `orion/topology_fc.py` attributes every face, edge and vertex to
the Blueprint feature that authored it, via FreeCAD's element map. The rule has
two halves: *inherited* (earliest level where the element is already a Face) and
*created* (resolves nowhere → the newest operation made it).

**Selection.** `lib/faceMap.ts` joins mesh triangles to CAD faces once at load
and reorders the index buffer into per-feature draw groups. Per-face highlight
is an overlay mesh — one extra draw call, not a group per face.

**Semantic editing (retune).** Click → feature → editable dimensions → preview
what else moves → rebuild → re-grade. Follows profile dependency edges, so a
bore's radius is reachable even though it lives in the sketch. Refuses computed
expressions rather than inverting them. **Contract preserved.**

**Direct editing (add).** Chamfer, Fillet (edge); Draft, Thickness (face). The
click becomes `near:<x>,<y>,<z>`, which survives a rebuild. Typed numbers become
declared variables, so a hand-added chamfer stays parametric. **Contract broken,
and reported as such.**

Catalogued but not implemented, each with its reason exposed via
`GET /studio/edit/operations`: Hole, Pocket, Boss, Rib, Pattern, Mirror.

---

## 3. Benchmark results

1192 ground-truth samples from per-face tessellation, six parts, real kernel.

| Part | Faces | Unattributed | Face rank-1 | **Feature rank-1** |
|---|---:|---:|---:|---:|
| multi_hole_plate | 47 | 0 | 100% | **100%** |
| flange | 18 | 0 | 100% | **100%** |
| l_bracket | 9 | 0 | 100% | **100%** |
| stepped_shaft | 7 | 0 | 100% | **100%** |
| bearing_housing | 17 | 0 | 100% | **100%** |
| shelled_enclosure | 27 | 0 | 100% | **100%** |

Latency: server pick p50 0.28 ms · `inspect` 30 ms · `plan` 6–8 ms local /
1.7–1.9 s production (cold-ish) · client face map 0.1–38 ms once per model ·
rebuild 3–8 s local, 8–20 s production, kernel-bound.

Tests: **1035 passing**, 1 skipped. Ruff, black, tsc, eslint all clean.

> A previous version of this table reported the enclosure at 54% / 77.1% and a
> "coplanar picking" limitation. **Retracted** — that part was built
> fillet-then-shell, giving an invalid 14-solid shape. See §5.

---

## 4. Production deployment status

| Component | Status | Evidence |
|---|---|---|
| `orionflow-builder` (Modal) | **deployed** | topology sidecar + `near:` selector live |
| `orionflow-api` (Modal) | **deployed** | `build: 6e048fa-dirty`, 57 routes, 9 new |
| Frontend (Vercel) | **deployed** | `app.orionflow.in`, all new capabilities verified in the served bundle |
| Database | healthy | `database_connected: true` |
| Redis | **not connected** | pre-existing; unrelated to this release |

Visual QA before the frontend shipped: **28 checks, 0 failed, 0 console errors**
— face highlighting, hover, selection persistence, materials, camera, panel, and
the Chamfer / Fillet / Draft / Thickness workflows each selecting, previewing,
committing and rebuilding with a volume change matching the operation.

Production smoke test: **24 checks, 0 failed.** Login → build (`verdict:
verified`, `solids: 1`, `valid: true`) → topology → inspect → plan → commit
(volume matched the closed form to 0.1 mm³) → chamfer → all five artifacts
downloaded → manifest verified with builder SHA and kernel version.

**Kernel skew — pinned 2026-08-05.** The container install was unversioned;
conda-forge resolved it to **1.1.0** at first build and now resolves to 1.1.3,
so any rebuild would have moved the kernel silently. Now pinned to `1.1.0` in
`deploy/modal_builder.py`, asserted by `verify_builder.py`. Local remains
**1.1.1**, which conda-forge does not ship at all — so the authoritative
benchmark runs against the container, not the laptop.

Test account left in the production database:
`smoke+1785861469@orionflow-qa.com`.

---

## 5. Known limitations

**~~Solid validity gates nothing~~ — FIXED 2026-08-05** (`b0772da`).
`solid:valid` and `solid:count` now run on every build and count towards the
verdict; re-measured at 200/200 on the pinned production kernel first, with no
sample reclassified. Note the flag was not the fix — the live path handed the
grader a dict without those keys, so enabling it alone was a no-op. See
`tests/test_solid_validity.py`.

**`Thickness` after `Fillet` produces an invalid solid.** Bisected on 1.1.1.
Shell first, then fillet. The compiler does not warn about order. Now *caught*
rather than silently passed, but still not prevented.

**Not implemented:** delete / reorder features; Hole, Pocket, Boss, Rib,
Pattern, Mirror; assemblies (the `#o1` occurrence level exists and is unused);
editable `polyline` points, so revolved parts report zero editable dimensions.

**Vocabulary ceiling.** 16 feature types, ~13 profile builders. Nothing outside
that is buildable regardless of model quality.

---

## 6. Next roadmap

Ordered by impact, not difficulty. **No new CAD operations until these land.**

1. **Wire the engineering calculators into verification.** `orion/calc.py`
   exposes ten behind a `run()` dispatcher and the graph audit found none
   reachable from the live build path. This converts VERIFIED from a geometric
   claim into an engineering one, which is the whole product promise — and is
   the cheapest item here because the calculators already exist.
2. ~~**Decide what VERIFIED means.**~~ Done 2026-08-05: solid soundness counts,
   re-measured at 200/200 on the production kernel first. VERIFIED is still a
   *geometric* claim — item 1 is what makes it an engineering one.
3. **Structural editing.** Delete and reorder, with dependency analysis and
   honest contract-impact reporting. Add is done; removing a feature that later
   ones depend on is the hard half.
4. **Semantic edit trajectory dataset.** Inverse edits (perturb a verified part,
   rebuild, synthesise the intent from the known delta) are free and exact.
   Include deliberate refusals — a corpus of only-valid edits teaches a model
   that nothing is ever refused.
5. **Benchmark and documentation.** Held-out set, external baselines, and parts
   outside the current vocabulary — without those it measures the generator
   rather than CAD editing.

---

## Release checklist

- [x] Backend validated — 1035 tests, real-kernel verification
- [x] Backend deployed — builder + API
- [x] Production health verified
- [x] Production smoke test — 24/24
- [x] Visual QA — 28/28, headless Chromium via Playwright
- [x] Frontend deployed — `app.orionflow.in`
- [x] Tagged `semantic-editing-v1` — commit `9f72473`
- [x] Commit pushed to `origin/main` — 2026-08-05, with the tag

### Post-release, 2026-08-05

- [x] Kernel pinned — `freecad=1.1.0`, container asserted to match
- [x] Solid soundness gates the verdict — `solid:valid` + `solid:count`
- [x] Re-measured on the production kernel — **200/200**, 0 unsound, 0 regressed
- [x] `/health` no longer reports a healthy database as down on a cold pool
- [x] Backend 1040 tests + OFL/pipeline 77; production smoke **26/26**
