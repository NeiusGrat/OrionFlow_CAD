# Semantic Editing V1 — Release Baseline

Status: **backend shipped, frontend held pending visual QA. Not yet tagged.**
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
| Frontend (Vercel) | **held** | pending visual QA |
| Database | healthy | `database_connected: true` |
| Redis | **not connected** | pre-existing; unrelated to this release |

Production smoke test: **24 checks, 0 failed.** Login → build (`verdict:
verified`, `solids: 1`, `valid: true`) → topology → inspect → plan → commit
(volume matched the closed form to 0.1 mm³) → chamfer → all five artifacts
downloaded → manifest verified with builder SHA and kernel version.

**Kernel skew noted:** production FreeCAD is **1.1.0** (conda-forge), local is
**1.1.1**. Everything measured locally was on 1.1.1. The manifest records which
built each part — this is what that field is for.

Test account left in the production database:
`smoke+1785861469@orionflow-qa.com`.

---

## 5. Known limitations

**Solid validity gates nothing — highest priority.** `measured.valid` and
`measured.solids` are recorded and count towards no verdict. A part can be
invalid, or in fourteen disconnected pieces, and be VERIFIED. The mechanism
exists (`COUNT_SOLID_VALIDITY`, off) but enabling it redefines VERIFIED and
invalidates every published figure (live 88%, fine-tune 95.3% / 94.0%). Treat as
a milestone with a full benchmark re-run, not a config change. Interim: the
panel now displays `solids` and `kernel check`.

**`Thickness` after `Fillet` produces an invalid solid.** Bisected on 1.1.1.
Shell first, then fillet. The compiler does not warn about order.

**Frontend visually unverified.** The viewer overhaul, per-face highlighting and
panel rewrite have never been rendered in a browser. This is why the frontend is
not deployed.

**Not implemented:** delete / reorder features; Hole, Pocket, Boss, Rib,
Pattern, Mirror; assemblies (the `#o1` occurrence level exists and is unused);
editable `polyline` points, so revolved parts report zero editable dimensions.

**Vocabulary ceiling.** 16 feature types, ~13 profile builders. Nothing outside
that is buildable regardless of model quality.

---

## 6. Next roadmap

Ordered by impact, not difficulty. **No new CAD operations until these land.**

1. **Wire the engineering calculators into verification.** 17 calculators are
   currently unreachable. This converts VERIFIED from a geometric claim into an
   engineering one, which is the whole product promise — and is the cheapest
   item here because the calculators already exist.
2. **Decide what VERIFIED means.** Re-measure with `COUNT_SOLID_VALIDITY = True`,
   then enable it. Pairs naturally with item 1.
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
- [ ] **Visual QA** — blocked: Chrome extension not connected
- [ ] Frontend deployed — gated on visual QA
- [ ] Tagged `semantic-editing-v1` — gated on the above
