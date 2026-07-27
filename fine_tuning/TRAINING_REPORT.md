# Teaching a model to author CAD that proves itself

**A build log: fine-tuning Qwen3-32B on a formally-verified CAD corpus.**

*Started 2026-07-25. Closed 2026-07-27 when the GPU box was destroyed; see
"Where everything lives" at the end for what survived and how to rebuild it.*

---

## The goal

Most text-to-CAD systems produce a shape. We wanted a model that produces a
shape **and a proof that the shape is correct** — a parametric feature tree in
which every dimension is an expression over named variables, accompanied by a
closed-form prediction of the resulting volume, which a geometry kernel then
independently confirms.

The training data comes from OrionFlow's "forge": a blueprint-first CAD data
factory where every part is generated from expressions (never magic numbers),
built in FreeCAD, and checked against frozen assertions before it is allowed
into the corpus. 42,723 records, 25,000 clean verified parts across 3,126
verified topologies, 17,023 repair records.

---

## Part 1 — The trap in the frozen dataset

The corpus had already been packed into a training set: `rl_corpus_v3_scale.jsonl`,
85,342 rows, checksummed and backed up. It looked ready to train on.

It wasn't. A `reasoning_record` row contains:

```
['assertions', 'blueprint_hash', 'datums', 'design_plan',
 'feature_rationales', 'kind', 'prompt', 'recipe', 'verification']
```

Design plan, assertions, verification trace — and **no geometry**. No
`template`. A model trained on this would learn to derive volumes beautifully
and would be unable to emit a single part. Two days before a demo, that is the
kind of discovery you want to make on day one.

The geometry existed; it just hadn't been packed. In the corpus DB, every
record carries `blueprint.template` — the parametric feature program:

```json
"sketches": [{"id": "s0", "plane": "XY", "profile": {
  "builder": "poly_with_holes",
  "args": {"points": [["-span/2","0"], ["-w/2","0"], ["-w/2","-stem"], ...],
           "holes": [["-span/2 + w/2","w/2","end_r"], ...]}}}],
"features": [{"id": "tee", "type": "Pad",
              "parameters": {"Length": "t", "Type": "Length"}}]
```

Every coordinate is an **expression**, not a number.

**Lesson:** a dataset being frozen, checksummed and backed up says nothing about
whether it contains the thing you intend to learn. Inspect the actual rows.

---

## Part 2 — Choosing the output contract

The model's target is exactly `Blueprint.payload()` minus its version field:

```
{part_class, variables, datums, design_plan, assertions, template}
```

This one object is simultaneously the reasoning, the CAD, and the proof,
because the existing pipeline already knew how to consume it:

```
Blueprint.from_dict → freeze() → resolve() → reconstruct.py → FreeCAD
                    → measure → check_assertions
```

`freeze()` runs a static checker that **rejects literal numbers** in the
template, so a model that emits `"Length": 20.0` instead of `"Length": "t"` is
refused before anything is built. The output format enforces parametricity.

A deliberate choice worth spelling out: we train on the **expression** template,
not the resolved numeric FeatureGraph. The numeric graph is derived for free by
`resolve()`. Training on it instead would produce magic numbers, fail the static
check, and lose the ability to change one variable and rebuild.

**Validation:** 300 packed targets were parsed, frozen, and resolved. All 300
produced a `blueprint_hash` **bit-identical to the corpus hash** — proof the
packing is lossless and every target is genuinely buildable.

### What we deliberately excluded

The **measured** values. The model predicts `163853.6581 mm³` from closed-form
reasoning; FreeCAD independently measures `163853.6581`. If measurements were in
the target, the model would be grading its own homework and the verification
would prove nothing. That separation is the entire point.

---

## Part 3 — Two prompt views

The original prompt builder produced asks like:

> Design a parametric tee plate. Variables: end_r=4.25, span=128, stem=64,
> t=12.5, w=27.

Every variable is **handed to the model**. But nobody types that at a demo. They
type *"I need a T-bracket to hang a 27 mm rail off a wall, about 130 long."* A
model trained only on fully-specified prompts has never once had to choose a
dimension.

So each record is packed under one of two views (~50/50, deterministic by hash):

- **spec** — all variables given. Teaches the template grammar precisely.
- **design** — prose engineering ask naming the family and its attachments,
  with only 40–70% of dimensions given. The model must select the rest *and*
  still satisfy the assertions it authors.

```
I need a stepped block.
It carries alignment rib, bolt boss and lightening pocket.
Dimensions (mm unless noted): height 32, length 108, width 62, step height 19,
step width 24, first feature rib length 12, second feature hole radius 2.4.
Choose sensible values for anything I have not given.
```

A prose generator that maps `flange_t → "flange thickness"` has failure modes.
Ours labelled a bent lever's `a` dimension as *"angle 46"* when it is a 46 mm
arm length — an entry that could never fire correctly, since no variable in the
corpus ends in `_a`. Caught by reading samples, not by any test.

### Splitting

Splits hold out **whole topology signatures**, never rows. Parametric variations
of one shape are near-duplicates; a row-wise split puts them on both sides of
the boundary and reports memorisation as generalisation.

Final: **25,560 samples** — 23,532 train / 984 val / 1,044 test, 125 held-out
signatures per eval split, 50 families.

---

## Part 4 — An evaluation that builds things

Token-level loss says nothing about whether a part exists. The eval harness runs
generated output down the real path and reports a funnel:

```
parsed JSON → froze (no magic numbers) → built in FreeCAD → VERIFIED
```

`VERIFIED` means: the model authored a parametric part, predicted its volume in
closed form, and the kernel agreed within tolerance.

Generation and verification are **decoupled** — completions are produced where
the GPU is, verified where FreeCAD is.

**Harness sanity check** (scoring reference targets, expect ~100%):

```
samples            24
parsed JSON        100.0%
froze (no magic #) 100.0%
built in FreeCAD   100.0%
VERIFIED           100.0%
volume rel_err     median=2.53e-16 max=6.08e-16
```

Machine precision. If gold doesn't verify, the metric is broken and every model
number is meaningless.

---

## Part 5 — The pre-training gate

Before spending GPU hours, we built parts from **every family** — 5 per family
across all 50, plus samples from val and test.

```
TOTAL 250/250 verified (100.0%) | fully broken families: 0 | partial: 1
val:  48/48 (100%)      test: 48/48 (100%)
```

The one flagged family, `manifold_runner`, exposed a real defect. It builds in
10.8 s alone (a Frenet `Sweep` verified by Tier-2 mesh convergence, which
re-tessellates the body at several densities) but failed 1/3 under six parallel
workers. A flat 90 s `BUILD_TIMEOUT_S` was starving it, and the harness reported
it as a bad part.

Two fixes:

1. `MESH_BUILD_TIMEOUT_S = 300`, selected when mesh verification is active.
   Result: 9/12 → **12/12** under identical load.
2. The eval harness was discarding the build log, so every build failure looked
   identical. It now keeps the kernel's stderr and distinguishes
   `timeout:` from `build: rc=…`.

**The second fix matters more.** An eval that cannot tell a starved worker from
a bad part will understate your model and send you debugging the wrong layer.

---

## Part 6 — Infrastructure archaeology

Hardware: 1× AMD MI300X (192 GB VRAM, 20 vCPU, 240 GB RAM), Atlanta, $1.99/hr.

A note on region: MI300X is only offered in ATL1. This is not a geography
restriction on the account — a droplet's region is where the *datacenter* is,
not where you are. The ×8 plan was simply out of stock.

We chose the **Unsloth Studio (ROCm 7.2.4)** image. What that image actually is,
which took some digging:

- Unsloth Studio is a **web app on port 80**, not a library install.
- `/usr/bin/python3` has **no torch at all**.
- The real stack is a uv-managed venv at
  `/root/.unsloth/studio/unsloth_studio/bin/python`.
- Leftover `~/.unsloth`, `~/.triton`, `~/unsloth_compiled_cache` directories are
  build-time artifacts, not an installation.
- **vLLM is not included** — so serving needed its own answer.

Once found, the venv is excellent: torch 2.11.0+rocm7.2, unsloth 2026.7.5,
transformers 4.57.6, trl 0.23.1, peft 0.18.1, MI300X visible with 192 GiB.

---

## Part 7 — Three silent failures in TRL 0.23

The trainer was originally written against an older TRL. Introspecting the
*installed* API instead of trusting the version we assumed found three changes
that all fail **silently** — no error, just a worse model:

| Change | Consequence if missed |
|---|---|
| `max_seq_length` → `SFTConfig.max_length` | old name ignored; defaults to **1024**, truncating every ~1800-token sample mid-JSON |
| `DataCollatorForCompletionOnlyLM` **removed** | completion-only masking silently becomes full-sequence loss |
| `SFTTrainer` wants `SFTConfig`, not `TrainingArguments` | config silently not applied |

The fix for masking: feed TRL a **prompt-completion** dataset and set
`completion_only_loss=True`, which keeps our hand-built ChatML frame intact.

Why hand-build ChatML at all? Qwen3 is a hybrid-thinking model whose packaged
chat template rewrites the assistant turn and injects its own empty
`<think></think>` pair — which would fight the real derivations in our targets.

**Verify masks, don't assume them.** The trainer prints proof before training:

```
mask check: 2412/2754 tokens supervised (88% — expect the assistant turn only)
first supervised tokens: '<think>\nA = (span*w + stem*w)   — T: top bar (span x w...'
```

Supervision begins exactly at `<think>`. The prompt is masked.

---

## Part 8 — The OOM, and why it wasn't random

First real attempt died at step 4:

```
torch.OutOfMemoryError: tried to allocate 27.18 GiB.
191.69 GiB capacity, 15.64 GiB free.
151.02 GiB allocated, 23.18 GiB reserved but unallocated.
```

Steps 1–3 succeeded. That pattern is the clue: `group_by_length` **deliberately
batches the longest samples together**, so the peak step is 4 × ~3000 tokens of
logits over a 152k vocab — roughly double the average step, not a random spike.

Fixes:

- batch 4 × accum 4 → **batch 2 × accum 8** (identical effective batch of 16,
  half the peak activation).
- `max_length` 4096 → **3072**. The longest real sample is 3026 tokens, so 4096
  was reserving headroom that could never be used.
- `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True` — 23 GB reserved-but-
  unallocated is fragmentation; expandable segments let the allocator grow a
  block instead of hunting for a contiguous one.

Smoke test after the fix: **25/25 steps, no OOM, loss 0.717 → 0.341**.

---

## Part 9 — Reading throughput honestly

Measured token statistics on the real tokenizer (not estimates):

```
tokens p50=1354  p90=2078  p99=2715  max=3026
over 4096: 0/600          32.8M tokens/epoch
eos='<|im_end|>'  pad='<|endoftext|>'   (distinct — no masking ambiguity)
```

Step time proved genuinely hard to read. Successive tqdm readings gave 23.6 s,
then 53.6 s, then 34.1 s. The cause is the same sampler behaviour as the OOM:
HuggingFace's length-grouped sampler sorts **within each megabatch**, so every
megabatch starts with its longest samples and accelerates through them. The
result is a sawtooth, and any single reading lands somewhere on it. The first
~40 steps are the slowest in the entire epoch because the sampler front-loads
the global longest batch (to fail fast on OOM).

We revised the estimate twice before computing it properly:

```
cumulative      : 46.4 s/step
post-warmup     : 41.0 s/step
total epoch    -> 16.8 h
```

**Lesson:** for an oscillating workload, quote a running average, never a
smoothed instantaneous ETA.

At ~10% MFU there is headroom — Unsloth logs *"Will smartly offload gradients to
save VRAM"*, trading speed for memory that, at 78% VRAM, we don't need to save.
We chose **not** to restart: checkpoints every 200 steps mean the demo never
depends on the epoch finishing, so a mid-run gamble had poor expected value.

---

## Part 10 — Serving without vLLM

Because the image ships no vLLM, serving is split by purpose:

- **`generate_batch.py`** — batched offline generation for scoring. One-at-a-time
  HTTP would take hours per eval; batching takes minutes. (Left-padding matters:
  right padding puts pad tokens between the prompt and the first generated
  token, and the model continues from padding instead of the assistant header.)
- **`serve_openai.py`** — stdlib-only OpenAI-compatible endpoint with SSE
  streaming, for the live demo. One generation at a time, which is the right
  shape for a single user watching a derivation stream.

Both speak the same wire format the existing agent already uses, so swapping the
production model is three environment variables:

```bash
ORION_LLM_PROVIDER=vllm
ORION_LLM_MODEL=orionflow
ORION_LLM_BASE_URL=http://<host>:8000/v1
```

Unset them to fall back to the previous hosted model — the demo never depends on
the fine-tune landing.

**Integration check:** 8/8 resolved Blueprints pass the agent's own FeatureGraph
validator with zero errors, so the model's output drops into the existing
FreeCAD path unchanged.

### Validating the pipeline before the model exists

Code that has never run is a liability, and the worst time to discover a bug in
your generation script is the moment a 16-hour checkpoint finally lands. So the
whole chain was exercised against **Qwen3-0.6B** — ~3 GB against 44 GB of free
VRAM, no meaningful risk to the training job:

```
generate_batch.py → completions.jsonl → scp → eval_blueprint --completions
```

Everything worked, and it produced a useful artifact: **the baseline**.

```
samples 4 | parsed JSON 0.0% | VERIFIED 0.0% | failure modes: parse=4
```

Asked for a parametric pump housing, the untrained model opens with:

> *"Okay, let's tackle this problem. The user wants a parametric pump housing
> with a counterbore set lightening pocket. The variables provided are H, R,
> att0_cd, att0_cr..."*

Generic assistant prose, zero parseable geometry. That is the before-picture,
and the comparison to a trained model opening with `V = L*W*H - L*step_w*step_h`
is the clearest way to show what the fine-tune actually bought.

---

## Part 11 — First real numbers: checkpoint-200

Training was paused at step 202, checkpoint-200 scored at full precision on 96
held-out test samples, and then resumed from exact state. Total interruption:
~40 minutes.

```
samples            96        (held-out topologies, unseen in any parametrization)
parsed JSON        99.0%
froze (no magic #) 99.0%
built in FreeCAD   83.3%
VERIFIED           75.0%
volume rel_err     median=1.98e-16   max=2.07e-15
view=spec          86.0%  (n=57)
view=design        59.0%  (n=39)
failure modes:     build=12, assert=8, precondition=3, parse=1
```

Baseline (untrained Qwen3): **0%**. This is **13.6% of one epoch**.

### What the numbers say

**The format is solved.** 99% parse and 99% freeze. `freeze` is the static check
that *rejects literal dimensions*, so 99% means the model reliably writes
`"Length": "att1_bh + (H - step_h) + 2"` instead of `"Length": 20.0`. The
parametric objective landed.

**When it is right, it is exactly right.** Median volume error **1.98e-16** —
machine precision. The model is not approximating volumes; it derives them in
closed form and the kernel agrees to the last bit. There is no partial credit.

**The gap is engineering judgment, not CAD.** spec 86% vs design 59% is the
whole story. Handed every variable, the model builds correct parts. Made to
*choose* dimensions, it fails ~40% of the time — and the failure modes agree:
`build` (values OCC cannot build) and `precondition` (violating guards the model
itself wrote).

This vindicates packing two prompt views. With spec-only data we would be
reading 86% and believing the model was ready, while the live demo — a human
typing prose — is the 59% case.

### One family explained 50% of all failures

`tee_plate` failed **12/12**, half of the 24 total failures:

```
build: unknown profile builder 'tee_plate';
have ['annulus','arc_spine','bolt_circle','circle', ...]
```

The model invented a builder named after the part class:

```json
{"builder": "tee_plate",
 "args": {"span": "span", "stem": "stem", "w": "w", "end_r": "end_r"}}
```

That is a *reasonable* abstraction — it recognised the part is a tee plate
parameterised by those four variables and reached for a high-level primitive.
The correct output composes `poly_with_holes` from eight corner points written
as expressions, which is far harder. **The model took the shortcut it wished
existed.**

Not a data-coverage hole: `tee_plate` has 436 training samples, all using
`poly_with_holes`. At step 200 the model had seen roughly 59 of them. Expected
to resolve with more steps — and worth noting that fixing this one family alone
takes 75% → 87.5%.

There is also a cheap inference-time backstop: the builder vocabulary is a
closed set of 11 names, so an invalid builder is detectable before anything is
built, and is exactly the kind of error the repair loop is designed to fix.

### The reasoning failures point at the next dataset

The 8 `assert` failures — parts that **built cleanly but whose predicted volume
disagreed with the measured one** — are the most interesting category, because
no conventional CAD benchmark can detect them. A shape-similarity score would
pass these parts.

All 8 are `design` view. **Zero** are spec view.

The derivations themselves are not naive:

```
V = ht/6*( A(0) + 4*A(ht/2) + A(ht) )          # prismatoid rule, bilinear taper
V += pi*att0_pr**2*att0_ph                     # locating pin
V += -(att1_sl*2*att1_sr + pi*att1_sr**2)*ht   # vent slot, full height
```

That is Simpson's rule correctly applied to a drafted casting. The error is the
last term: it subtracts the slot through the **full height**, but on a drafted
body the cross-section narrows with height, so the slot does not intersect the
full prism and the subtraction overcounts.

The model has learned the *formulas* but not the *feasible envelope* — the range
of dimension choices over which its own closed form remains valid. That is
precisely the skill the spec view never exercises, because there the dimensions
are given and always valid.

**This diagnoses the next dataset.** Every record in the training corpus is a
*verified* one, so the model has never seen an example of "chose dimensions that
broke my own derivation, here is how that was diagnosed and corrected". The
17,023 repair records are exactly that, and this failure mode is the principled
argument for folding them into run #2 — not merely that self-repair demos well.

## Current status

| | |
|---|---|
| Model | Qwen3-32B, LoRA r=64 α=128, bf16 |
| Hardware | 1× MI300X 192 GB (ROCm 7.2.4, torch 2.11) |
| Data | 23,532 train / 984 val / 1,044 test |
| Batch | 2 × 8 accum = 16 effective, max_length 3072 |
| Schedule | 1 epoch, cosine, lr 1e-4, warmup 3% |
| Steps | 1,471 |
| Rate | ~41 s/step averaged → ~16.8 h |
| Checkpoints | every 200 steps |

**Why one epoch:** the cosine schedule anneals to zero at the end of the run you
configure. Setting 2 epochs and stopping early — which a deadline would force —
leaves a checkpoint whose learning rate never annealed, measurably worse than a
clean 1-epoch model.

### Progress log

- **step 85/1471** — GPU 100%, VRAM 78%, healthy. Awaiting checkpoint-200.
- **step 135/1471** — generation pipeline validated end-to-end against
  Qwen3-0.6B; baseline recorded at 0% verified. Training unaffected
  (44.3 GiB free before and after).
- **step 200** — paused, scored (**75.0% VERIFIED**), resumed from exact state
  (optimizer + scheduler + RNG). ~40 min interruption.
- **step 204** — resumed run healthy, ~15 h remaining.
- **step 400** — eval loss flat (0.0634 → 0.0647), train still falling
  (0.0220). Deliberately not paused; see Part 12. LR schedule verified
  continuous across the resume.
- **step 432** — two checkpoints saved, GPU 100%, ~12 h remaining. Survived two
  SSH drops and a killed local launcher without losing a step.
- **step 600** — eval loss flat for 400 steps (0.0634 / 0.0647 / 0.0647) while
  train creeps down (0.0293 → 0.0220 → 0.0203). On the loss metric this model
  converged around step 200–400. Course unchanged; see below.
- **step 652** — healthy, ~10.5 h remaining.
- **step 1471 — COMPLETE.** 14 h 42 m, train_loss 0.0178, LR annealed to
  4.85e-10. Survived two SSH drops, a killed local launcher, and a deliberate
  pause/resume without losing a step.

### Run complete

```
train_runtime  52,905 s  (14 h 42 m)      epoch 1.0, 1471 steps
train_loss     0.0178                     0.445 samples/s
lr final       4.85e-10                   cosine fully annealed

eval  200:0.0634  400:0.0647  600:0.0647  800:0.0664
      1000:0.0685  1200:0.0689  1400:0.0691
```

**Eval loss rose monotonically from step 200 onward** while train loss fell to
0.020. On the loss metric, checkpoint-200 is the best checkpoint of the run and
everything after it is overfitting.

Whether that is *true* of the metric we care about is a separate question —
loss is dominated by JSON scaffolding, while `VERIFIED %` turns on a few
decisive tokens (see Part 12). This is precisely why checkpoint-200 was
preserved before `save_total_limit` could delete it, and why final model
selection is a head-to-head on built geometry rather than a loss comparison.

### The rejected alternative, recorded honestly

With eval loss flat and ~10 h of GPU left before the deadline, the tempting move
was to stop and spend those hours on a repair-augmented second run, making
self-repair *learned* rather than harness-driven. The timing fit (~2 h data
work + 8 h training + 2 h scoring against ~30 h of runway).

We rejected it for a specific reason rather than general caution: **the demo
looks identical either way.** A viewer sees a part fail, a diagnosis in
engineering language, a correction, and a green re-verification. Whether the
diagnosis originates in the verifier or in the model's own learned behaviour is
an implementation detail — disclosed honestly, but invisible on screen. Paying
real risk to the one working model for an invisible gain is a bad trade.

The remaining steps buy a properly annealed model at near-zero risk. The metric
that would change the decision is `VERIFIED %`, not loss — and that is measured
at completion on the full 1,044-sample test split.

### Why checkpoints are not scored mid-run

Only **44.3 GiB of VRAM is free** while training. A second 32B model needs
~64 GB in bf16, or ~26 GB in 4-bit plus KV cache. The 4-bit route fits on paper,
but the training job's own peak varies with batch sequence length — the same
sawtooth — and if a long batch arrives while generation holds that memory, the
*training run* is what dies. Trading a 16-hour run for a number that would not
change the decision is a bad bet.

The safe signal is `trainer_state.json`, written into every checkpoint. It
carries the full `log_history` (train and eval loss at every logging step), it
costs no VRAM, and being a file it sidesteps the stdout-buffering problem
entirely.

### Gotcha worth recording

Python **block-buffers stdout when redirected to a file**. tqdm writes to stderr
(unbuffered) so progress appears, but the loss dicts sit in the buffer until it
fills, making a healthy run look like it has stopped logging. Use
`PYTHONUNBUFFERED=1`.

---

## Part 14 — The result, and the metric that would have thrown it away

Final model, 300 held-out test samples, full precision:

```
                    step 200      FINAL (1471)
parsed JSON           99.0%   →      99.3%
froze (no magic #)    99.0%   →      99.3%
built in FreeCAD      83.3%   →      98.3%
VERIFIED              75.0%   →      95.3%
  view=spec           86.0%   →      98.8%
  view=design         59.0%   →      91.2%
volume rel_err                       median 1.94e-16   max 1.88e-15
```

Untrained baseline: **0%**.

`tee_plate` — 12/12 failed at step 200 — finished **39/40 verified**. Not one
build failure remains in the sample; the invented-builder class is gone.

### Eval loss got worse for the entire time correctness got better

```
eval loss   0.0634 → 0.0691      rose monotonically from step 200
VERIFIED      75%  →  95.3%      over the same steps
```

Standard practice — early-stop on validation loss — would have stopped at step
200 and shipped a **75%** model. Following the loss curve would have cost twenty
points of real-world correctness, and it would have looked like the responsible
choice at the time.

The mechanism is the one described in Part 12: cross-entropy averages over
~1,400 tokens of largely predictable JSON scaffolding, while verification turns
on a handful of decisive ones. Learning to compose `poly_with_holes` from eight
expression-valued corner points instead of inventing a `tee_plate` primitive is
a small change in average token probability and the entire difference between a
part that exists and one that does not.

**If you can afford to run your real metric, run your real metric.** A proxy
that is cheap to compute is not thereby safe to optimise, and in this case it
pointed in the opposite direction from the truth for 1,271 consecutive steps.

### It reasons symbolically and computes numerically badly

Two independent measurements found the same weakness.

**It states volumes it never computed.** Across 229 verified samples, the prose
`Predicted volume:` line matched the sample's own formal assertion **0 times**,
with errors up to 134%. The training data was 323/323 consistent, so this is
learned behaviour, not a data defect: the model learned that a number belongs
there and never learned to evaluate it.

This matters less than it sounds and more than it looks. The model's *real*
prediction is the expression — `V = L*w*h + L*b*t` — and that is exact, which is
why measured volume agrees to 1e-16. The prose figure is decoration. But
displaying it beside a passing assertion for a different number invites the
obvious and damning question, so the demo now evaluates the model's own
expression and shows that instead.

**Self-repair inherits the same limit.** Given a maximally precise diagnosis —
`bore_wall: T/2 - bore_r - 3 evaluated to -10.5 — it must be greater than 0`,
plus every variable and its value — the model correctly restated the problem in
words ("the central bore is too large for the plate thickness") and then chose
T=20.0, which yields −5.5. Still negative. It also picked the wrong repair: the
guard should reference `W` (80), not `T`, and inflating T violated the
dimension the user had specified.

Measured across all 14 failures:

```
VERIFIED             95.3%
VERIFIED @1 repair   96.3%     repaired 3/14

parse (truncated JSON)   2 -> 0     2/2 fixed
precondition             3 -> 2     1/3 fixed
assert (wrong volume)    9 -> 9     0/9 fixed
```

Repair reliably fixes **formatting**, occasionally fixes **value selection**,
and **never** fixes a wrong derivation. A wrong derivation is precisely the
failure that needs arithmetic.

**Consequence for the demo.** We had planned the fourth beat around the model
fixing its own work. The evidence says not to: the reliable half is
deterministic — the verifier refusing to build a part that violates a guard it
authored, and naming the guard and its value. That never fails. The model's
correction is best-effort.

### What is left

14 failures in 300, of which 12 are `design` view:

* **9 × `assert: body`** — the part builds, but the predicted volume disagrees
  with the measured one. The dimension-selection weakness from step 200: much
  rarer, not eliminated.
* **3 × precondition** — the model chose values violating guards it authored.
* **2 × parse** — truncated JSON.

Every one of these is the failure class the 17,023 repair records were built
for, which remains the strongest argument for run #2.

## Part 15 — Deployment

**Artifacts.** The LoRA adapter is 2.1 GB; merging it into Qwen3-32B produces a
62 GB standalone model in about 15 minutes on CPU. Only the adapter is worth
storing — the merged model is reproducible from it and the public base.

**Backup.** Everything lived on a single rented GPU box for the first several
hours after training, which was the largest unmanaged risk in the project: one
destroyed droplet or lapsed credit and fifteen hours of training would be gone.
The adapter now lives in a private HF model repo
(`sahilmaniyar888/orionflow-cad-qwen3-32b-lora`, 2.06 GB with tokenizer and
model card).

**Serving.** The AMD Unsloth image ships no vLLM, so two paths exist:

* `fine_tuning/serve_openai.py` — stdlib-only OpenAI-compatible endpoint with
  SSE streaming, one generation at a time. Right for a live demo, wrong for
  throughput. ~28 s for a simple part, ~105 s for an attachment-heavy one.
* `rocm/vllm` (40 GB docker image) — the production path: continuous batching,
  concurrency, and several times the single-stream speed.

**Access.** The droplet firewall is active and the model server binds to
localhost, so access is via SSH tunnel rather than an exposed port — an
unauthenticated model endpoint on the public internet is not something to create
casually. The India→Atlanta link dropped four times during this work, so the
tunnel runs under an auto-reconnect loop; long-running jobs are all `setsid`
detached and survived every drop without losing a step.

**Swapping the production model** is three environment variables, because the
agent was written against a provider-agnostic interface:

```bash
ORION_LLM_PROVIDER=vllm
ORION_LLM_MODEL=orionflow
ORION_LLM_BASE_URL=http://localhost:8000/v1
```

Unset them and the previous hosted model takes over again. The demo never
depended on the fine-tune landing.

## Part 16 — v2: buying robustness with a point of accuracy

v1's headline hid a hole. It scored 95.3% on held-out topologies and **50% on
free-form engineering prose** — the same parts, the same numbers, only the
wording changed. Every training prompt shared one skeleton
(`I need a {family}. Dimensions: ...`), so the model had learned that skeleton
rather than the language.

v2 changed **only the prompts**. Same 25,560 verified targets, same geometry,
same recipe — 75% of samples re-rendered through ~20 real-world phrasings
(`120 OD`, `Ø40`, `R12.5`, `thk 8`, `3 mm wall`), including the
diameter-for-radius conversions that caused the original failures.

```
                          v1        v2
VERIFIED (300 held-out)   95.3%  ->  94.0%      -1.3 pts (within noise, +/-2.7)
free-form prose (24)      50%    ->  58%        +8 pts
volume rel_err (median)   1.94e-16   2.05e-16   unchanged
```

### The crossover is the real evidence

```
              v1        v2
view=spec    98.8%  ->  91.1%
view=design  91.2%  ->  94.4%
```

The two views **swapped**. v1 was far better at rigid spec prompts than at
prose; v2 is now better at prose than at spec. That is exactly what
re-weighting the corpus from 50% spec to 15% spec should produce, and it is
stronger evidence than the headline that the intervention did what it was
designed to do rather than moving by chance.

### The failures changed character

18 failures in 300: `assert` 12, `precondition` 4, `parse` 2. v1's failures at
the same stage included invented builders and malformed JSON — *language*
problems. v2's are almost entirely **engineering judgment**: volumes derived
wrongly, and guards the model authored and then violated.

That is the wall SFT cannot break. Every record in the corpus is a *verified*
one, so the model has never once seen a bad choice being corrected. It is the
RL-shaped gap, and it is why `orion/reward.py` exists.

### Two process notes

**Eval loss lied again, in the same direction.** v2's eval loss bottomed at
step 400 (0.0700) and rose monotonically to 0.0776 — exactly v1's shape.
Early-stopping on validation loss would again have shipped a worse model.

**The first prose sweep was invalid and nearly reported as 33%.** Eleven of 24
prompts died on a dropped SSH tunnel and were scored as model failures. The
server was healthy throughout. This is the same class of mistake as the
mesh-timeout: infrastructure failure wearing a model failure's clothes, and the
reason the eval harness now keeps the kernel's own stderr.

## Every problem hit, and what fixed it

A running ledger. Most of these are silent failures — they produce a worse
result rather than an error, which is what makes them worth writing down.

| # | Problem | How it showed up | Fix applied |
|---|---|---|---|
| 1 | Frozen 85k-row training set contained **no geometry** | `reasoning_record` rows had no `template` key | Repacked from the corpus DB (`orion/pack_sft.py`); verified by hash-identical round-trip |
| 2 | Prompts handed the model every dimension | Every prompt was `Variables: span=128, stem=64…` | Added a second **design view** with 40–70% of dims and prose phrasing |
| 3 | Prose generator mislabelled a dimension | `a 46` rendered as *"angle 46"* on a lever where `a` is an arm length | Removed the `a→angle` mapping (no corpus variable ends in `_a`); bare single letters now quoted verbatim |
| 4 | Row-wise splits would leak | Parametric variants of one shape are near-duplicates | Split holds out whole `topology_signature` groups |
| 5 | Tier-2 families failed under parallel eval | `manifold_runner` 9/12, reported as bad parts | `MESH_BUILD_TIMEOUT_S = 300` when mesh verification is active → 12/12 |
| 6 | Eval could not distinguish infra from model failure | Every build failure looked identical | `score_one` keeps kernel stderr; separates `timeout:` from `build: rc=` |
| 7 | TRL renamed `max_seq_length` → `max_length` | **Silent**: would default to 1024 and truncate every sample mid-JSON | Bound against the installed `SFTConfig`, verified by introspection |
| 8 | `DataCollatorForCompletionOnlyLM` removed | **Silent**: loss would cover the prompt too | Prompt-completion dataset + `completion_only_loss=True`; mask asserted at startup |
| 9 | Qwen3 chat template rewrites assistant turns | Would strip or double our real `<think>` blocks | ChatML frame built by hand |
| 10 | OOM at step 4 (27 GiB alloc) | Steps 1–3 passed, step 4 died | `group_by_length` batches longest samples together → batch 2×accum 8, `max_length` 3072, `expandable_segments:True` |
| 11 | Step time unreadable (23s→53s→34s) | Two wrong ETA estimates published | Sawtooth from within-megabatch length sorting; quote running averages only |
| 12 | Loss lines vanished from the log | Looked like training had stalled | Python block-buffers stdout when redirected; read `trainer_state.json` instead, use `PYTHONUNBUFFERED=1` |
| 13 | `pgrep -f` killed its own shell | ssh exited 255 mid-command | The pattern matched the ssh command line; kill by explicit PID |
| 14 | CPU-side work slowed training | Step time 43s → 62s during a CPU-only merge | Unsloth stages gradients through CPU RAM, so CPU/PCIe is on the critical path — run nothing else during training |
| 15 | Model invents non-existent builders | `tee_plate` failed 12/12 | Under-trained at step 200 (~59 of 436 examples seen); expected to resolve with steps, with a closed-vocabulary check as backstop |
| 16 | Model has no recovery behaviour | Corpus contains only *verified* records, so failure→fix was never demonstrated | `orion/repair_loop.py` — verifier-derived diagnosis fed back as a repair turn; adds `VERIFIED @1 repair` |
| 17 | Completions lacked their originating prompt | A repair turn needs to show the model its own attempt in context | `generate_batch.py` now stores the system+user turns beside each completion |
| 18 | Long-lived SSH monitor died on a network blip | Monitor exit 255 twice; training was fine but we were blind | Poll loop moved client-side, fresh connection per cycle, warn after 3 consecutive unreachable polls |
| 19 | `save_total_limit=4` would delete the only *scored* checkpoint | checkpoint-200 (75% VERIFIED) drops out once checkpoint-1000 is written — and flat eval loss means a mid-run checkpoint may beat the annealed one | Copied its adapter + tokenizer (2.1 GB, no optimizer state) to `keep/ckpt-200-scored75/`; final selection is a head-to-head on the same split |

**On remote resilience.** The India→Atlanta link is usable but not reliable
enough for hours-long SSH sessions. Everything consequential on that box is
launched with `setsid` and detached from the session, which is why two dropped
connections cost only monitoring visibility and never a single training step. A
job you cannot afford to lose should not be a child of your SSH session.

## Part 12 — When eval loss goes flat and it does not mean what it looks like

Checkpoint-400, read from `trainer_state.json` without pausing training:

```
train  200:0.0397   mean(300-400):0.0220     still falling
eval   200:0.0634   400:0.0647               flat, marginally up
lr      40:8.67e-05  200:9.72e-05  400:8.56e-05
```

Train loss falling while eval loss stalls is the textbook early-overfitting
signature, and the reflex is to stop. We did not, for two reasons.

**Loss is a poor proxy for the metric we care about.** Eval loss averages over
~1,400 tokens per sample, nearly all of which is easily-predicted JSON
scaffolding. The `tee_plate` failure — half of all failures — is one wrong
builder name in place of the eight coordinate expressions that should have been
there. That is a small share of the token budget and **100% of that family's
verification outcome**. `VERIFIED %` can move a great deal while eval loss does
not move at all. This is the entire reason for owning a harness that builds
geometry rather than trusting a loss curve.

**The reading would not have changed the action.** The test for pausing is
whether different answers lead to different work. Score 88% → continue. Score
76% → still continue, because a fully-annealed model at step 1471 beats step
400 either way, and no alternative use of the GPU fits the deadline (a
repair-augmented run is ~16 h of training plus hours of data work, and starting
it would risk the one working model we have). A 40-minute pause for a number
that changes nothing is not worth taking.

**A resume artefact worth naming.** A first read of the checkpoint reported
`lr: 0`, which would have meant the schedule annealed to zero and everything
since was wasted. It was an artefact of reading the last `log_history` entry —
an *eval* record, which carries no `learning_rate` field. The real schedule is
smooth straight across the resume boundary (9.715e-5 at 200 → 9.550e-5 at 240),
confirming the scheduler restored rather than restarted. Verify the alarming
reading before acting on it.

## Part 13 — Closing the loop the verifier already knows how to close

Every failure the harness reports is *already diagnosed*. It knows an invented
builder is out of a closed 11-name vocabulary; it knows which named assertion
disagreed and by how much; it knows which precondition the model violated. That
information was being printed and thrown away.

`orion/repair_loop.py` turns it into an instruction and hands it back:

```
build: unknown profile builder 'tee_plate'
  -> There is no sketch profile builder called 'tee_plate'. The available
     builders are: annulus, arc_spine, bolt_circle, circle, hole_grid,
     poly_with_holes, polyline, rect, rect_with_holes, regular_polygon,
     rounded_rect, slot. Compose the outline from one of those — a
     non-rectangular plate outline is built with 'poly_with_holes', passing
     the corner points explicitly as expressions.

assert: height_extent,body,one_solid
  -> The part built, but the measured geometry disagrees with the prediction
     for: height_extent, body, one_solid. The feature tree is valid, so the
     derivation is what is wrong — check whether a subtracted feature actually
     intersects the full extent you assumed (on a drafted or tapered body the
     section narrows with height, so a cut does not remove a full prism).
```

The repair turn is a genuine multi-turn exchange — original ask, the model's own
failed attempt, then the diagnosis — because that is the shape the corpus repair
records use, so a model later trained on them meets a familiar prompt.

This gives a second metric, `VERIFIED @1 repair`, which is what the system
actually does in front of a user rather than what a single greedy sample does.
It is also demo beat four: a part fails, the machine explains why in engineering
terms, the model corrects it, and the correction re-verifies — live.

Worth being precise about what this is and isn't: it is a **harness-level**
capability, not a learned one. The model is not yet trained to repair; it is
being told what is wrong by a verifier that knows. Training on the 17,023 repair
records is what would make the behaviour intrinsic.

## Caveats — what we are *not* claiming

Stated plainly, because a technical audience will find these anyway.

**"VERIFIED" is self-consistency, not similarity to a reference part.** The model
authors its own assertions and is then checked against them. It cannot fake the
volume check — that compares its closed-form prediction against what OCC
actually measures, and the two agree to 1e-16 or they do not. But a model could
in principle author *fewer* or *weaker* assertions than the corpus would. We
have not yet measured assertion strength as a separate metric, and we should.

**300 samples is a partial evaluation.** The final numbers are measured on 300
of the 1,044 held-out test topologies, not all of them. At 95.3% the 95%
confidence interval is roughly ±2.7 points, so v1-vs-v2 (95.3% vs 94.0%) is
inside the noise and must not be read as a regression. The earlier
checkpoint-200 figure of 75% came from only 96 samples — ±9 points, a
directional read.

**The honest demo number is the prose number, not the headline.** The spec view
(all variables given) is the easier half, and free-form engineering prose is
harder still than the packed `design` view. Measured: v1 scored 91.2% on the
design view but **50%** on free-form prose; v2 scored 94.4% and **58%**. Quote
the prose figure when describing what a person typing at a keyboard will see.

**Breadth is 50 families, concentrated in plate / bracket / flange-type parts.**
There are no assemblies, no threads, no surfacing, no sheet metal. The model
should be demoed inside that distribution and described as such.

**One epoch, one configuration, no hyperparameter search.** We have not shown
this is the best achievable result — only that it works. Throughput sat at
roughly 10% MFU, so the run is also not efficient.

**The eval harness shares code with the data generator.** Both use
`Blueprint.resolve()` and the same FreeCAD compiler. A bug in that shared path
would flatter the model. The independent check is that FreeCAD measures geometry
the Blueprint never sees.

## Open items, in the order the evidence supports

**1. Arithmetic is the ceiling.** Both remaining weaknesses — unevaluated volume
statements and unrepairable guard violations — are the same failure. The model
composes exact symbolic expressions and cannot evaluate them. More SFT will not
fix this; neither will DPO, which shifts preferences rather than teaching
multiplication. The real options are (a) let it call a calculator, evaluating
expressions in-loop the way the harness already does, or (b) stop asking it for
numbers at all and treat the expression as the sole prediction. (b) is nearly
free and is what the demo already does.

**2. Repair training** on the 17,023 repair records. Justified by measurement
rather than intuition: every training record is a *verified* one, so the model
has never seen "chose values that broke my own derivation, here is the
correction". That is exactly the class it now fails.

**3. DPO** on the preference pairs — but note the frozen `dpo_pair` rows carry a
`template` only on the `chosen` side; the rejected side has variables and fault
metadata and would need repacking from the corpus DB, the same gap that made
the original RL pack untrainable.

**4. Topology breadth.** 50 families, concentrated in plate/bracket/flange
parts. No assemblies, threads, surfacing, or sheet metal. Let measured failures
choose what to add rather than guessing.

**5. Throughput.** ~10% MFU. Unsloth stages gradients through CPU RAM, which put
PCIe on the critical path; at 78% VRAM that trade was not needed. A tuned rerun
would likely halve the 14.7 h.

### Not worth doing before a demo

Squeezing 95.3% → 96–97% is invisible when the audience watches individual
parts succeed, and any training run monopolises the GPU that serving and
rehearsal need. Speed and reliability are the visible variables at that point,
not accuracy.

---

## Where everything lives

The MI300X was destroyed on 2026-07-27 once the AMD grant work was finished —
an idle GPU droplet bills at the same rate as a busy one, and DigitalOcean
charges a powered-off droplet too, so *destroy* is the only action that stops
the meter. Before that, every file on the box was either verified present here
or deliberately abandoned.

**Weights — private HF repo `sahilmaniyar888/orionflow-cad-qwen3-32b-lora`:**

| | path in repo | sha256 (adapter) | test VERIFIED |
|---|---|---|---|
| v1 | repo root | `26f4fc9f…a35597` | 95.3% (prose 50%) |
| v2 | `v2/` | `29b94db6…9ce6a1` | 94.0% (prose 58%) |

Both were confirmed byte-identical to `checkpoint-1471` of their runs before
teardown. Each is 2.1 GB; merging either into Qwen3-32B reproduces the 62 GB
standalone model in ~15 minutes on CPU, which is why the merged copy was not
kept.

**Everything else is in this repo,** under `fine_tuning/run_logs/`:

- `logs/` — every run log, including `train.log` + `train_resume.log` (v1,
  across the pause/resume) and `train_v2.log`.
- `v1/`, `v2/`, `ckpt200/` — `trainer_state.json` (the full loss history at
  every logging step), `adapter_config.json`, `training_args.bin`, and the
  `pack_stats.json` of the dataset each was trained on.
- `evals/` — the scored verdicts (`eval_final.json`, `eval_v2.json`,
  `eval_ckpt200.json`, `eval_final_repair.json`) and the raw model generations
  behind them. Every number quoted in this report is recomputable from these
  files with `python -m orion.eval_blueprint --completions …`.

The training sets themselves (`data/forge/sft_v1`, `sft_v2`, ~150 MB each) are
untracked but present locally, and are regenerable from the corpus DB with
`orion/pack_sft.py` — the packing is deterministic and was proved lossless by
the hash round-trip in Part 2.

**Deliberately abandoned with the box:** the `checkpoint-200` adapter (75%
VERIFIED — strictly worse than the final, and its evidence is the numbers in
`evals/`, not the weights), intermediate checkpoints 1000/1200/1400 with their
optimizer state, and the merged model. Nothing in that list is needed to
reproduce or serve the result.

**To serve it again** on a fresh box: `fine_tuning/setup_droplet.sh` documents
the image and the environment traps, `serve_openai.py` is the stdlib
single-stream server used for the demo, and pointing the agent at it is three
environment variables (Part 15).
