/**
 * The agent's decision layer, checked against the sentences it will actually
 * get.
 *
 * These three modules are the whole reason the studio no longer asks the user
 * to pick a mode, and all three are pure functions over data — which means the
 * one honest way to know they work is to run them on real phrasings rather than
 * to click through the UI and conclude "it looked right". A router that sends
 * "why is it 6 mm?" to the build path costs a part; a resolver that matches the
 * wrong variable rebuilds the wrong dimension. Neither failure is visible in a
 * screenshot.
 *
 * No test framework: the UI has no unit runner and adding one to check three
 * files would be a dependency for a dependency's sake. Run with
 *
 *     node scripts/run-agent-tests.mjs
 *
 * from `orionflow-ui/`, which transpiles this with the esbuild that Vite
 * already ships and executes it. Exits non-zero on the first failure.
 */

import { route } from './intent';
import { readEdit, rankVariables, readAmount, describeVariable } from './dimensions';
import { resolveSelection } from './selection';
import type { TopologyRecord } from './faceMap';

let failures = 0;
let checks = 0;

function ok(condition: boolean, what: string, detail = '') {
    checks++;
    if (condition) return;
    failures++;
    console.error(`  FAIL  ${what}${detail ? `\n        ${detail}` : ''}`);
}

function eq(actual: unknown, expected: unknown, what: string) {
    ok(actual === expected, what, `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

function section(name: string) {
    console.log(`\n${name}`);
}

/* ══════════════════════ 1. the router ══════════════════════ */

const OPEN = { hasPart: true, canSelect: true, hasVariables: true };
const EMPTY = { hasPart: false, canSelect: false, hasVariables: false };

section('router — the four examples from the brief');
eq(route('Create a bracket with four mounting holes', EMPTY).intent, 'build', 'create → build');
eq(route('Select the two holes on the left', OPEN).intent, 'select', 'select → select');
eq(
    route('Review this design for manufacturing problems', OPEN).intent,
    'review',
    'review → review',
);
eq(route('Increase the hole diameter to 12 mm', OPEN).intent, 'modify', 'increase → modify');
eq(route('Make the bracket 5 mm thicker', OPEN).intent, 'modify', 'comparative → modify');

section('router — the expensive mistake is never made');
// A question must never replace the part on screen, however it is phrased.
for (const q of [
    'why is the wall 6 mm?',
    'what is the volume?',
    'is the bore big enough for an M10?',
    'should the plate be thicker?',
    'how would you machine this?',
    'can it be 3D printed?',
]) {
    ok(route(q, OPEN).intent !== 'build', `"${q}" is not a build`);
    ok(route(q, OPEN).intent !== 'modify', `"${q}" is not an edit`);
}
// With a part open, a bare noun phrase must not silently replace it either.
eq(route('a 40 mm washer', OPEN).intent, 'ask', 'bare noun phrase with a part open is not a build');
eq(route('a 40 mm washer', EMPTY).intent, 'build', 'bare noun phrase with nothing open is a build');

section('router — lenses are inferred, not chosen');
eq(route('review this for 3D printing', OPEN).lens, 'dfm_3d_printing', '3D printing lens');
eq(route('any issues bending this from sheet metal?', OPEN).lens, 'dfm_sheet_metal', 'sheet metal lens');
eq(route('can this be machined on a 3-axis mill?', OPEN).lens, 'dfm_machining', 'machining lens');
eq(route('review this design', OPEN).lens, 'dfm', 'a bare review still gets a DFM lens');
eq(route('what is this part?', OPEN).lens, 'modeling', 'a plain question stays in modeling');

section('router — explicit overrides win');
const forced = route('/build a 20 mm cube', OPEN);
eq(forced.intent, 'build', 'slash prefix forces the route');
eq(forced.text, 'a 20 mm cube', 'slash prefix is stripped from the message');
ok(forced.forced, 'slash prefix is marked as forced');
eq(route('/ask make it thicker', OPEN).intent, 'ask', 'a forced ask beats an edit-shaped sentence');

section('router — capability gates');
eq(
    route('select the two holes on the left', { ...OPEN, canSelect: false }).intent,
    'ask',
    'no topology means selection is not offered',
);
eq(
    route('make it 5 mm thicker', { ...OPEN, hasVariables: false }).intent,
    'ask',
    'no variables means there is nothing to retune',
);

/* ══════════════════════ 2. dimension reading ══════════════════════ */

const VARS = {
    plate_t: 8,
    hole_d: 9.5,
    base_w: 48,
    base_l: 32,
    hole_pcd: 62,
    fillet_r: 3,
};

section('amounts — absolute, relative and scale');
eq(readAmount('increase the hole diameter to 12 mm')?.kind, 'absolute', '"to 12" is absolute');
eq(readAmount('increase the hole diameter to 12 mm')?.amount, 12, '"to 12" reads 12');
eq(readAmount('make it 5 mm thicker')?.kind, 'delta', '"5 mm thicker" is a delta');
eq(readAmount('make it 5 mm thicker')?.amount, 5, '"5 mm thicker" is +5');
eq(readAmount('make it 5 mm thinner')?.amount, -5, '"5 mm thinner" is -5');
eq(readAmount('reduce it by 2 mm')?.amount, -2, '"reduce by 2" is -2');
eq(readAmount('double the thickness')?.kind, 'scale', 'double is a scale');
eq(readAmount('double the thickness')?.amount, 2, 'double is ×2');
eq(readAmount('make it 20% bigger')?.amount, 1.2, '20% bigger is ×1.2');
eq(readAmount('set it to 2 cm')?.amount, 20, 'cm is converted to mm');
eq(readAmount('make it thicker'), null, 'no number means no amount — never invented');

section('variables — the right dimension, or none');
eq(describeVariable('plate_t'), 'plate thickness', 'plate_t reads as plate thickness');
eq(describeVariable('hole_d'), 'hole diameter', 'hole_d reads as hole diameter');
eq(rankVariables('make the plate 5 mm thicker', VARS)[0].variable, 'plate_t', 'thicker → plate_t');
eq(rankVariables('hole diameter to 12', VARS)[0].variable, 'hole_d', 'hole diameter → hole_d');
eq(rankVariables('set fillet_r to 5', VARS)[0].variable, 'fillet_r', 'an exact name wins outright');

section('edits — resolved, or refused with a reason');
const e1 = readEdit('make the plate 5 mm thicker', VARS);
ok(e1.ok, 'a clear edit resolves');
if (e1.ok) {
    eq(e1.edit.variable, 'plate_t', 'moves plate_t');
    eq(e1.edit.from, 8, 'from 8');
    eq(e1.edit.to, 13, 'to 13 — the number in the brief');
}

const e2 = readEdit('increase the hole diameter to 12 mm', VARS);
ok(e2.ok, 'an absolute edit resolves');
if (e2.ok) {
    eq(e2.edit.variable, 'hole_d', 'moves hole_d');
    eq(e2.edit.to, 12, 'to 12');
}

const e3 = readEdit('make it thicker', VARS);
ok(!e3.ok, 'no number is refused rather than guessed');
if (!e3.ok) eq(e3.reason, 'no-amount', 'and the reason is the missing amount');

const e4 = readEdit('change the flux capacitor to 12 mm', VARS);
ok(!e4.ok, 'an unknown dimension is refused');
if (!e4.ok) eq(e4.reason, 'no-match', 'and the reason is that nothing matched');

const e5 = readEdit('reduce the plate thickness by 20 mm', VARS);
ok(!e5.ok, 'an edit that would make a dimension negative is refused');
if (!e5.ok) eq(e5.reason, 'not-positive', 'and it says so before the kernel is asked');

// Floating point must not leak into a dimension.
const e6 = readEdit('make the plate 0.1 mm thicker', VARS);
if (e6.ok) eq(e6.edit.to, 8.1, '8 + 0.1 is 8.1, not 8.100000000000001');

/* ══════════════════════ 3. selection ══════════════════════ */

/** A plate with four ⌀9.5 holes at the corners and one ⌀20 bore in the middle,
 *  in FreeCAD's frame: X left→right, Y front→back, Z up. */
const RECORD: TopologyRecord = {
    counts: { faces: 7 },
    features: {
        pad_1: { type: 'Pad', faces: ['#o1.s1.f0', '#o1.s1.f1'] },
        holes_1: {
            type: 'Pocket',
            faces: ['@holes.f0', '@holes.f1', '@holes.f2', '@holes.f3'],
        },
        bore_1: { type: 'Pocket', faces: ['@bore.f0'] },
    },
    faces: [
        { ref: '#o1.s1.f0', index: 0, feature: 'pad_1', surface: 'Part::GeomPlane', normal: [0, 0, 1], center: [0, 0, 8], position: [0, 0, 8], area: 3000, bbox: [-30, -20, 8, 30, 20, 8] },
        { ref: '#o1.s1.f1', index: 1, feature: 'pad_1', surface: 'Part::GeomPlane', normal: [0, 0, -1], center: [0, 0, 0], position: [0, 0, 0], area: 3000, bbox: [-30, -20, 0, 30, 20, 0] },
        { ref: '@holes.f0', index: 2, feature: 'holes_1', surface: 'Part::GeomCylinder', radius: 4.75, axis: [0, 0, 1], center: [-24, -14, 4], position: [-24, -14, 4], bbox: [-28.75, -18.75, 0, -19.25, -9.25, 8] },
        { ref: '@holes.f1', index: 3, feature: 'holes_1', surface: 'Part::GeomCylinder', radius: 4.75, axis: [0, 0, 1], center: [-24, 14, 4], position: [-24, 14, 4], bbox: [-28.75, 9.25, 0, -19.25, 18.75, 8] },
        { ref: '@holes.f2', index: 4, feature: 'holes_1', surface: 'Part::GeomCylinder', radius: 4.75, axis: [0, 0, 1], center: [24, -14, 4], position: [24, -14, 4], bbox: [19.25, -18.75, 0, 28.75, -9.25, 8] },
        { ref: '@holes.f3', index: 5, feature: 'holes_1', surface: 'Part::GeomCylinder', radius: 4.75, axis: [0, 0, 1], center: [24, 14, 4], position: [24, 14, 4], bbox: [19.25, 9.25, 0, 28.75, 18.75, 8] },
        { ref: '@bore.f0', index: 6, feature: 'bore_1', surface: 'Part::GeomCylinder', radius: 10, axis: [0, 0, 1], center: [0, 0, 4], position: [0, 0, 4], bbox: [-10, -10, 0, 10, 10, 8] },
    ],
};

section('selection — the example from the brief');
const s1 = resolveSelection('Select the two holes on the left', RECORD);
eq(s1.refusal, null, 'the two holes on the left resolve');
eq(s1.refs.length, 2, 'exactly two faces');
ok(
    s1.refs.every((r) => ['@holes.f0', '@holes.f1'].includes(r)),
    'and they are the two with negative X',
    s1.refs.join(', '),
);

section('selection — counts, sides and sizes');
eq(resolveSelection('select all the holes', RECORD).refs.length, 5, 'all holes = 4 + the bore');
eq(resolveSelection('select the holes on the right', RECORD).refs.length, 2, 'two on the right');
eq(resolveSelection('select the top face', RECORD).refs.length, 1, 'one top face');
eq(resolveSelection('select the largest hole', RECORD).refs[0], '@bore.f0', 'largest is the ⌀20 bore');
eq(
    resolveSelection('select the 9.5 mm holes', RECORD).refs.length,
    4,
    'sized query picks the four corner holes',
);

section('selection — refusals name what the part has');
const s2 = resolveSelection('select the fillets', RECORD);
ok(s2.refusal !== null, 'a part with no fillets refuses');
ok(/planar and .* cylindrical/.test(s2.refusal ?? ''), 'and says what it does have', s2.refusal ?? '');
ok(resolveSelection('select the holes', null).refusal !== null, 'no topology refuses cleanly');

// A count that cannot be met is reported, not quietly rounded down.
const s3 = resolveSelection('select the six holes on the left', RECORD);
ok(/only 2 match/.test(s3.describe), 'a shortfall is stated', s3.describe);

/* ══════════════════════ report ══════════════════════ */

console.log(
    `\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} checks passed`,
);
if (failures > 0) process.exit(1);
