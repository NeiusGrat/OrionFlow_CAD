# Semantic CAD: Architecture & Validation

How OrionFlow answers *"what is this face, and what happens if I change it?"* —
and exactly how far that answer can currently be trusted.

Status: validated 2026-08-04 against FreeCAD 1.1.1 on six parts.
Backend suite 993 passing. Two defects found and fixed during validation, one
found and **not** fixed — see [Known limitations](#known-limitations).

---

## 1. The pipeline

```
  user clicks a pixel
        │
        ▼
  three.js raycast  ──────────────►  triangle index
        │                                  │
        │                        lib/faceMap.ts (client, once at model load)
        │                                  ▼
        │                            CAD face  #o1.s1.f11
        ▼                                  │
  POST /studio/edit/inspect ───────────────┤
        │                                  ▼
        │                    orion/topology_fc.py wrote, at build time:
        │                       face → Blueprint feature   "bore"
        ▼
  app/services/semantic_edit.py
        │   feature → editable parameters (following profile edges)
        ▼
  POST /studio/edit/plan      what moves, what else moves, what checks follow
        │
        ▼
  POST /studio/edit/commit    retune → Blueprint → FreeCAD → re-graded verdict
```

Everything left of `commit` is free: no kernel, no meter. Only `commit` runs
FreeCAD, and it is metered exactly like `/studio/rebuild`, because it is one.

---

## 2. Identity model

Three levels, deliberately not collapsed into one. Each survives a different
class of change, and conflating them is how a saved selection silently comes to
mean different geometry.

| Identity | Example | Survives | Owner |
|---|---|---|---|
| Blueprint feature id | `bore` | a redesign | `orion/blueprint.py` |
| Stable selector | `@bore.f0` | a rebuild that doesn't change that feature | `topology_fc.py` |
| Artifact selector | `#o1.s1.f11` | nothing — addresses one built artifact | `topology_fc.py` |

`@bore.f0` numbers a feature's own faces by a deterministic geometric sort, not
by OCC index, so moving an unrelated hole cannot renumber it. `#o1.s1.f11` is an
OCC index and is invalidated by any rebuild that shifts one.

**A selector that resolves to nothing is a 404, not a 400.** A stale `#f7` held
across a rebuild is well-formed and simply names nothing any more; reporting it
as malformed sends the caller hunting a bug in their own selector code.

### Selector grammar

```
#o1                occurrence
#o1.s1             shape within it
#o1.s1.f7          face      (e edge, v vertex)
#f7                shorthand — the sole occurrence/shape of a single-body part
@bore.f0           feature-anchored, rebuild-stable
```

---

## 3. Provenance model

### Artifact provenance

Every build writes `manifest.json` beside its artifacts and publishes it with
them. It carries per-file `sha256` and byte count, the `blueprint_hash` the
build was authorised against, the builder stamp (`ORIONFLOW_BUILD`, the same
string `GET /health` reports), and the FreeCAD version reported by the container
that compiled.

**Digests are taken after the Modal round trip, not in the kernel worker.** On
that path artifacts cross a container boundary as bytes and are rewritten
locally; a hash taken earlier would attest to a different file and would agree
with itself through a truncated transfer.

Serving checks size unconditionally (a `stat`) and `sha256` only on
`?verify=1` — the viewer reloads a GLB far more often than anyone swaps a file
for a different one of exactly equal length. A mismatch is **409**: the server
is healthy, the stored artifact disagrees with the record, and the caller can
rebuild. Builds predating the manifest serve unchecked so old links keep working.

### Geometry provenance — the authorship rule

FreeCAD 1.1 exposes `body.Shape.ElementReverseMap` and
`body.getElementHistory(mappedName)`, which returns an element's full ancestry.
Both obvious readings of it are wrong:

- the **last** entry is the sketch the feature was drawn from;
- the **first** is whichever feature most recently touched the shape — for a
  fillet, that is the fillet even on flats it merely passed through.

The rule is in two halves:

1. **Inherited.** The creator is the *earliest* feature in the chain at which
   the element already resolves to a `Face` in that feature's own element map.
   Before that point its ancestor was an edge, which is to say the face did not
   exist yet.
2. **Created.** A face a feature *created* has no entry in that feature's own
   element map — the map records what an operation inherited, not what it
   minted. An element resolving nowhere in its ancestry was made by the most
   recent operation in it.

Half 2 was missing in the first implementation, which left 40 of 121 faces on a
shelled enclosure unattributed. Both halves are pinned by tests in
`tests/test_topology_extract.py`.

`isPartner`/`isSame`/`isEqual` all return **False** between a feature's shape and
the body shape, so TopoDS handle identity is not an option and none is used.

**Feature ids come for free.** `freecad/reconstruct.py` creates every object with
`addObject(kind, feature_id)`, so a FreeCAD object's `Name` *is* the Blueprint
feature id. There is no matching layer.

---

## 4. Selection pipeline

`lib/faceMap.ts` assigns every mesh triangle to a CAD face once at load, then
**reorders the index buffer** so each feature's triangles are contiguous and adds
one `geometry.addGroup` per feature. Highlighting is a material swap on a real
draw group, which keeps the machined-metal PBR look instead of tinting.

`e.faceIndex` from three's raycaster is `floor(j / 3)` over the index buffer, so
after the reorder it indexes the join array directly — hover costs nothing.

The alternative was a GLB with one primitive per face. That means changing how
every model is exported and rendered; this needs neither, and the sidecar it
reads is already served.

**Coordinates match exactly.** `stl_to_glb` (trimesh) writes an *identity* node
transform, so the GLB carries FreeCAD's raw Z-up coordinates and a three.js
world-space raycast maps 1:1 to topology coordinates. Side effect: because three
treats +Y as up, a part's FreeCAD Z runs along three's Z, so parts render
standing rather than lying flat. Left unchanged — rotating alters every existing
thumbnail and is a product decision. If it is ever rotated, picking must switch
to `mesh.worldToLocal(point)`.

---

## 5. Semantic editing

A click resolves to a *feature*; `blueprint_edit.retune` takes *variables*.
Nothing stored connects them — the connection is read out of the template, where
a parameter is an expression over the variables block.

**A dimension often lives in the sketch.** A bore's depth is `Pocket.Length`; its
*radius* is the `r` argument of the profile sketch, reachable only through the
`profile` dependency edge. `editable()` follows that edge and exposes it as
`profile.r`. Without it, clicking a bore wall and asking for "radius" finds
nothing.

**Expressions are refused, never inverted.** `t * 2` cannot be "set to 14"
without inventing a value for `t`. The refusal names the variable. Solving
numerically would build a part from a number the user never typed and would move
everything else `t` drives as a side effect.

**Shared variables are disclosed, not blocked.** Changing a pad thickness reports
`also_moves: [bore.Length 10→14]`. That linkage *is* the design working; a
direct-modelling tool would break it silently. Moved *assertion targets* are
reported in a separate list from moved geometry — a target that moves is not a
weakened contract, since the check is an expression over the same variables.

**Intent preservation is structural, not checked.** A retune cannot reach the
template, so the assertions still describe the part and `contract_broken` is
always false on this path. Adding or removing a feature is a different act and
lives in `/studio/rebuild`, where it is honestly flagged.

---

## 6. Benchmark methodology

Six parts, built by the real kernel (FreeCAD 1.1.1, local builder). Nothing
stubbed. Harness: `stress.py`, `face_samples.py`, `pickcheck.py`.

**Ground truth comes from per-face tessellation.** `face_samples.py` runs under
FreeCAD, tessellates each face and emits triangle centroids — points that belong
to a face by construction.

> Do **not** sample face centroids. A full cylinder's centroid sits on its axis
> in empty space, so picking there correctly returns the innermost bore and looks
> like a miss. The first run scored 16/18 on a flange purely from this sampling
> error.

Three numbers are reported, and they are not interchangeable:

- **face rank-1** — the pick's first candidate is the exact face
- **face top-3** — the correct face is among three returned candidates
- **feature rank-1** — the first candidate's *feature* is right; this is what the
  UI shows, and the only one a user can perceive

---

## 7. Benchmark results (regression baseline, 2026-08-04)

1192 ground-truth samples.

| Part | Faces | Features | Unattributed | Face rank-1 | Face top-3 | **Feature rank-1** |
|---|---:|---:|---:|---:|---:|---:|
| multi_hole_plate | 47 | 2 | 0 | 100% | 100% | **100%** |
| flange | 18 | 4 | 0 | 100% | 100% | **100%** |
| l_bracket | 9 | 2 | 0 | 100% | 100% | **100%** |
| stepped_shaft | 7 | 1 | 0 | 100% | 100% | **100%** |
| bearing_housing | 17 | 6 | 0 | 100% | 100% | **100%** |
| shelled_enclosure | 27 | 3 | 0 | 100% | 100% | **100%** |
| **all** | | | **0** | | **100%** | **100%** |

> **Correction, 2026-08-04.** An earlier run of this table reported the shelled
> enclosure at 54.0% / 77.1% and this document recorded a limitation called
> "coplanar faces defeat point-picking". **That was wrong and is retracted.**
>
> The enclosure used in that run was built fillet-then-shell, which produces an
> *invalid* solid; the subsequent through-cut shattered it into **14 disjoint
> solids** with one face reporting a negative area. The benchmark was measuring
> attribution against a broken shape. Nothing flagged it, because solid validity
> and solid count count towards no verdict — see
> [Known limitations](#known-limitations).
>
> Rebuilt in the correct order (shell, then features), the same part class
> scores 100% on every metric. The picking maths was never the problem.

### Latency

| Stage | Cost |
|---|---|
| server pick | p50 0.28 ms · p99 1.26 ms |
| `POST /edit/inspect` (real HTTP) | 30 ms |
| `POST /edit/plan` (real HTTP) | 6–8 ms |
| `buildFaceMap` (client, once per model) | 0.1 ms @ 9 faces · 17 ms @ 47 · 35 ms @ 121 |
| hover / click after load | O(1) array lookup |
| full rebuild (commit) | 3–8 s, kernel-bound |

Face count is not the driver of attribution quality — **operation mix is**. A
200-face prismatic part is fine; a 60-face shelled one is not.

---

## 8. Known limitations

### Solid validity and solid count gate nothing (open — highest priority)

`measured` records `valid` (OCC's `isValid()`) and `solids`. Neither counts
towards the verdict. The mechanism to change that exists —
`orion_physical_ai/verify.py::solid_validity_checks`, behind
`COUNT_SOLID_VALIDITY = False` — and is deliberately off, because turning it on
changes what VERIFIED means and every published number (the live 88%, the
fine-tune's 95.3% and 94.0%) was measured under the current definition.

**This is not theoretical and it has now cost real time.** A benchmark enclosure
built fillet-then-shell came back `solids: 14, valid: false`, with no recompute
errors, and was used as a legitimate result — producing a documented "limitation"
that did not exist. The panel now *displays* solids and kernel validity so the
failure is visible, but nothing refuses on it.

Deciding this needs a re-measurement of the published figures, not a flag flip.

### `Thickness` on a filleted solid produces an invalid shape

Bisected on FreeCAD 1.1.1:

| case | solids | valid |
|---|---:|---|
| plain box | 1 | ✅ |
| box + shell | 1 | ✅ |
| rounded box | 1 | ✅ |
| rounded + fillet | 1 | ✅ |
| **rounded + fillet + shell** | 1 | ❌ |
| rounded + shell (no fillet) | 1 | ✅ |

Shell first, then fillet — which is standard practice anyway, since the shell
should follow the rounded wall. The compiler does not enforce or warn about the
order.

### A failed operation used to report success (fixed 2026-08-04)

`bundle["success"]` means "a solid was produced with a measurable volume". It
says nothing about whether the *requested* feature is in that solid. A dressup
that fails to recompute leaves the previous geometry standing, so the volume is
unchanged, the assertions still pass, and the user is told it worked.

Observed on `/studio/edit/add/commit`: a Draft returned `invalid after
recompute` and a Thickness `missing thickness base`, and both responses were
`success: true, verdict: verified`. Now checked by
`direct_edit.build_failure()`, which reads the kernel's own report and returns
`not_applied` with its reason.

### A dressup whose faces are all later re-cut owns nothing

On `filleted_enclosure`, `hollow` (Thickness) reports 0 faces: the subsequent
ThroughAll pocket re-created every face it touched, and by the "created here"
rule those faces belong to the pocket. Defensible — a wall with twelve holes in
it *is* a different face — but it means a shell can vanish from the feature-face
map. Attribution is "the most recent operation that produced this face", not
"the operation a person would name".

### Not covered

- **Assemblies.** The extractor reads `doc`'s first `PartDesign::Body`. The
  selector grammar has an occurrence level (`#o1`) but only ever emits one.
- **Structural editing.** Add / delete / reorder is not implemented. Only
  retuning is reachable from a click.
- **Revolved profiles are not editable.** A stepped shaft's diameters live in a
  `polyline` `points` list, which `sites()` skips because it is not a string
  expression — `stepped_shaft` reports 0 editable parameters.
- **Topology caps.** 4000 faces / 12000 edges / 12000 vertices, then the record
  is marked `truncated`.

---

## 9. Design decisions

**Extraction runs inside the existing FreeCAD process.** The element map exists
only in the live document's feature tree; a STEP is a finished solid with no
tree, so a post-hoc extractor — `cadpy` or anything else — could never recover
authorship. A separate Python 3.12 topology worker was evaluated and rejected
for this reason; the API container stays 3.11 with no kernel.

**Attribution is reported as absent rather than guessed.** When the element map
is unavailable the record says `attribution: "unavailable"` and every feature is
null. A wrong feature id is worse than an absent one, because the UI presents
both with the same confidence.

**Picking returns ranked candidates, not a verdict.** A hit on a tangent seam is
genuinely ambiguous at mesh resolution. A caller holding the runners-up can
disambiguate; one given a single answer must pretend an inference was a
measurement.

**`artifacts` stays a flat kind→URL map.** The UI renders one download per key
and `build_completed` emits `sorted(rev.artifacts)`, so digests travel beside it
in `artifact_digests`, never nested inside.

**`editStore` is separate from `studioStore`.** Hover and draft values must never
enter the history the user steps back through. A commit crosses over via
`adopt`, because it produces a real built part.

---

## 10. Future work

Ordered by what unblocks the most:

1. **Decide what VERIFIED means.** Re-measure the published figures with
   `COUNT_SOLID_VALIDITY = True`, then turn it on. Until then a part can be
   invalid, or in fourteen pieces, and still be VERIFIED.
2. **Delete / reorder features.** Add is done; removing a feature that later
   ones depend on is the hard half and is not started.
3. **Editable profile geometry.** Expose `polyline` points so revolved and
   swept parts have editable dimensions.
4. **Assembly-level topology.** The `#o1` occurrence level exists in the grammar
   and is unused.

---

## Appendix: authoring traps

Hit while writing the benchmark parts. All are checker or builder rules working
as designed, not bugs.

- `hole_grid` and `rect_with_holes` already include the outer rectangle — they
  are **Pad** profiles. Pocketing `hole_grid` leaves posts, not holes.
- `n`, `nx`, `ny`, `start_deg` are skipped by the checker, so a variable used
  only there reads as unused. Pass a literal.
- Every other sketch argument must reference a variable. Only
  `0, ±1, 2, 90, 180, 270, 360` are structural constants.
- `Revolution` needs `_ReferenceAxis`.
- `_Edges: "vertical"` matches hole walls too — use `largest:<n>` for a corner
  break.
- Assertions need both `tier` (1|2|3) and `tol_rel`, and a `kind` from
  `orion/forge.py::check_assertions`.
