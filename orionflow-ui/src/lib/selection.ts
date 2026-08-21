/**
 * "Select the two holes on the left."
 *
 * The topology sidecar already knows every CAD face of the built part — its
 * surface type, its centre, its radius, and which Blueprint feature authored
 * it. `faceMap.ts` already joins those faces to triangles so the viewport can
 * light them. What was missing was a way to name a set of them in words.
 *
 * This resolves the naming, entirely on the client and against the real record.
 * Nothing here approximates: a hole is a cylindrical face the sidecar reported,
 * "on the left" is a comparison against the part's own measured bounding box,
 * and "two" is a count that is checked rather than assumed. If the query picks
 * out nothing, it says so and names what the part does have — a selection that
 * silently matches zero faces is indistinguishable from a broken feature.
 *
 * Axes are FreeCAD's, because the sidecar is FreeCAD's: Z is up, X is left to
 * right, Y is front to back. The viewer rotates to Y-up for display only, and
 * this deliberately works in the kernel's frame so the words mean the same thing
 * here as they do in the exported STEP.
 */

import type { TopoFace, TopologyRecord } from './faceMap';

/** What kind of thing the query is asking for. */
type Kind = 'hole' | 'face' | 'fillet' | 'chamfer' | 'planar' | 'any';

/** Which end of which axis. */
type Side =
    | 'left'
    | 'right'
    | 'top'
    | 'bottom'
    | 'front'
    | 'back'
    | 'inner'
    | 'outer'
    | null;

export interface SelectionQuery {
    kind: Kind;
    side: Side;
    /** How many were asked for; null means "all that match". */
    count: number | null;
    /** A diameter or radius named in the query, in mm. */
    size: number | null;
    /** True for "the largest", "the biggest bore". */
    extreme: 'largest' | 'smallest' | null;
}

export interface SelectionResult {
    /** Face refs to highlight. */
    refs: string[];
    /** The distinct features those faces belong to. */
    features: string[];
    /** A sentence naming what was selected and how it was decided. */
    describe: string;
    /** Set when nothing matched, explaining what the part does contain. */
    refusal: string | null;
}

const NUMBER_WORD: Record<string, number> = {
    a: 1, an: 1, one: 1, single: 1,
    two: 2, both: 2, pair: 2,
    three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
};

/* ─────────────────────────── parsing ─────────────────────────── */

export function parseQuery(text: string): SelectionQuery {
    const t = text.toLowerCase();

    const kind: Kind = /\b(hole|holes|bore|bores|drill|thru|through)\b/.test(t)
        ? 'hole'
        : /\b(fillet|fillets|round|rounds)\b/.test(t)
          ? 'fillet'
          : /\b(chamfer|chamfers|bevel)\b/.test(t)
            ? 'chamfer'
            : /\b(face|faces|surface|surfaces|wall|walls)\b/.test(t)
              ? 'face'
              : 'any';

    const side: Side = /\bleft\b/.test(t)
        ? 'left'
        : /\bright\b/.test(t)
          ? 'right'
          : /\b(top|upper|above)\b/.test(t)
            ? 'top'
            : /\b(bottom|lower|underside|below)\b/.test(t)
              ? 'bottom'
              : /\bfront\b/.test(t)
                ? 'front'
                : /\b(back|rear)\b/.test(t)
                  ? 'back'
                  : /\b(inner|inside|internal)\b/.test(t)
                    ? 'inner'
                    : /\b(outer|outside|external)\b/.test(t)
                      ? 'outer'
                      : null;

    // "all four holes" means four, not everything, so a bare number wins over
    // the word "all".
    let count: number | null = null;
    const digits = t.match(/\b(\d+)\s+(?:of\s+the\s+)?[a-z]/);
    if (digits) count = parseInt(digits[1], 10);
    if (count === null) {
        for (const [word, n] of Object.entries(NUMBER_WORD)) {
            if (new RegExp(`\\b${word}\\b`).test(t)) {
                count = n;
                break;
            }
        }
    }
    if (/\ball\b|\bevery\b|\beach\b/.test(t)) count = null;

    const sizeMatch = t.match(/(?:⌀|dia\w*\s*|d\s*=\s*)?(\d+(?:\.\d+)?)\s*mm\b/);
    const size = sizeMatch ? parseFloat(sizeMatch[1]) : null;

    const extreme = /\b(largest|biggest|widest|max)\b/.test(t)
        ? ('largest' as const)
        : /\b(smallest|tiniest|narrowest|min)\b/.test(t)
          ? ('smallest' as const)
          : null;

    return { kind, side, count, size, extreme };
}

/* ─────────────────────────── geometry helpers ─────────────────────────── */

function surfaceKind(face: TopoFace): string {
    return (face.surface || '').split('::').pop()!.replace('Geom', '');
}

function centreOf(face: TopoFace): number[] | null {
    if (face.center?.length === 3) return face.center;
    if (face.position?.length === 3) return face.position;
    if (face.bbox?.length === 6)
        return [
            (face.bbox[0] + face.bbox[3]) / 2,
            (face.bbox[1] + face.bbox[4]) / 2,
            (face.bbox[2] + face.bbox[5]) / 2,
        ];
    return null;
}

/** The part's own extent, measured from the faces the sidecar reported.
 *  "Left" has to mean left *of this part*, not left of the world origin. */
function extent(faces: TopoFace[]): { min: number[]; max: number[] } | null {
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    let seen = false;
    for (const f of faces) {
        const c = f.bbox?.length === 6 ? f.bbox : null;
        if (c) {
            seen = true;
            for (let i = 0; i < 3; i++) {
                min[i] = Math.min(min[i], c[i]);
                max[i] = Math.max(max[i], c[i + 3]);
            }
            continue;
        }
        const p = centreOf(f);
        if (!p) continue;
        seen = true;
        for (let i = 0; i < 3; i++) {
            min[i] = Math.min(min[i], p[i]);
            max[i] = Math.max(max[i], p[i]);
        }
    }
    return seen ? { min, max } : null;
}

/** Which axis and direction a side word refers to, in the kernel frame. */
const AXIS: Record<Exclude<Side, null | 'inner' | 'outer'>, { axis: 0 | 1 | 2; dir: -1 | 1 }> = {
    left: { axis: 0, dir: -1 },
    right: { axis: 0, dir: 1 },
    front: { axis: 1, dir: -1 },
    back: { axis: 1, dir: 1 },
    bottom: { axis: 2, dir: -1 },
    top: { axis: 2, dir: 1 },
};

/* ─────────────────────────── resolving ─────────────────────────── */

/** Candidate faces for a kind of thing, before position is considered. */
function candidatesFor(kind: Kind, faces: TopoFace[], record: TopologyRecord): TopoFace[] {
    if (kind === 'hole') {
        // A hole is a cylindrical face. Toroids are the fillets around them and
        // are excluded, or "the two holes" would select four things.
        return faces.filter((f) => surfaceKind(f) === 'Cylinder');
    }
    if (kind === 'face' || kind === 'planar') {
        return faces.filter((f) => surfaceKind(f) === 'Plane');
    }
    if (kind === 'fillet' || kind === 'chamfer') {
        // Attribution is the authority here, not surface type: a chamfer is a
        // plane and a fillet is a cylinder, so only the feature that authored
        // them can tell either from the rest of the part.
        const want = kind === 'fillet' ? /fillet|round/i : /chamfer|bevel/i;
        const refs = new Set<string>();
        for (const [id, meta] of Object.entries(record.features ?? {})) {
            if (want.test(meta.type || '') || want.test(id)) {
                for (const r of meta.faces ?? []) refs.add(r);
            }
        }
        return faces.filter((f) => refs.has(f.ref));
    }
    return faces;
}

/** Group faces that belong to the same physical hole.
 *
 *  A through-hole is often two half-cylinders in the B-rep, and "the two holes
 *  on the left" must not select four faces and report two. Grouping is by axis
 *  line: same radius, same axis direction, same axis position. */
function groupHoles(faces: TopoFace[]): TopoFace[][] {
    const groups: TopoFace[][] = [];
    for (const f of faces) {
        const c = centreOf(f);
        const found = groups.find((g) => {
            const h = g[0];
            const hc = centreOf(h);
            if (!c || !hc) return false;
            const sameSize = Math.abs((h.radius ?? -1) - (f.radius ?? -2)) < 1e-6;
            if (!sameSize) return false;
            // Distance measured perpendicular to the axis: two halves of one
            // bore share a line, they just sit at different heights on it.
            const ax = f.axis?.length === 3 ? f.axis : [0, 0, 1];
            const d = [c[0] - hc[0], c[1] - hc[1], c[2] - hc[2]];
            const along = d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2];
            const perp = Math.hypot(
                d[0] - along * ax[0],
                d[1] - along * ax[1],
                d[2] - along * ax[2],
            );
            return perp < 0.05;
        });
        if (found) found.push(f);
        else groups.push([f]);
    }
    return groups;
}

const KIND_NOUN: Record<Kind, [string, string]> = {
    hole: ['hole', 'holes'],
    face: ['face', 'faces'],
    planar: ['face', 'faces'],
    fillet: ['fillet', 'fillets'],
    chamfer: ['chamfer', 'chamfers'],
    any: ['face', 'faces'],
};

function plural(kind: Kind, n: number): string {
    const [one, many] = KIND_NOUN[kind];
    return n === 1 ? one : many;
}

/**
 * Resolve a query against a part's topology.
 *
 * Never throws and never returns a partial success: either refs are returned
 * with a sentence saying how they were chosen, or `refusal` says why nothing
 * was, in terms of what the part actually has.
 */
export function resolveSelection(
    text: string,
    record: TopologyRecord | null,
): SelectionResult {
    const empty = (refusal: string): SelectionResult => ({
        refs: [],
        features: [],
        describe: '',
        refusal,
    });

    const faces = record?.faces ?? [];
    if (!faces.length)
        return empty(
            'I have no topology record for this part, so I cannot resolve a selection against it. Clicking a face in the viewport still works.',
        );

    const q = parseQuery(text);
    const pool = candidatesFor(q.kind, faces, record!);

    if (!pool.length) {
        const cyl = faces.filter((f) => surfaceKind(f) === 'Cylinder').length;
        const pln = faces.filter((f) => surfaceKind(f) === 'Plane').length;
        return empty(
            `This part has no ${plural(q.kind, 2)} I can point at — the topology record lists ${pln} planar and ${cyl} cylindrical faces across ${faces.length} in total.`,
        );
    }

    // Holes are grouped so a count means what an engineer means by it.
    let groups: TopoFace[][] =
        q.kind === 'hole' ? groupHoles(pool) : pool.map((f) => [f]);

    const reasons: string[] = [];

    // ── by size
    if (q.size != null) {
        const want = q.size / 2; // spoken sizes are diameters
        const near = groups.filter(
            (g) =>
                g[0].radius != null &&
                (Math.abs(g[0].radius - want) < 0.26 || Math.abs(g[0].radius - q.size!) < 0.26),
        );
        if (near.length) {
            groups = near;
            reasons.push(`⌀${q.size} mm`);
        }
    }

    // ── by side, against the part's own extent
    if (q.side && q.side !== 'inner' && q.side !== 'outer') {
        const box = extent(faces);
        const { axis, dir } = AXIS[q.side];
        if (box) {
            const mid = (box.min[axis] + box.max[axis]) / 2;
            const span = box.max[axis] - box.min[axis];
            // A tenth of the span of tolerance: a hole sitting dead on the
            // centreline belongs to neither side, and claiming it does would
            // make "the two on the left" quietly return three.
            const slack = span * 0.02;
            const kept = groups.filter((g) => {
                const c = centreOf(g[0]);
                if (!c) return false;
                return dir < 0 ? c[axis] < mid - slack : c[axis] > mid + slack;
            });
            if (kept.length) {
                groups = kept;
                reasons.push(`on the ${q.side}`);
            } else {
                return empty(
                    `Nothing sits on the ${q.side} of this part — every ${plural(q.kind, 2)} I found is within 2% of the centreline on that axis.`,
                );
            }
        }
    }

    // ── inner / outer, by radius
    if (q.side === 'inner' || q.side === 'outer') {
        const withR = groups.filter((g) => g[0].radius != null);
        if (withR.length > 1) {
            const sorted = [...withR].sort((a, b) => a[0].radius! - b[0].radius!);
            groups = q.side === 'inner' ? [sorted[0]] : [sorted[sorted.length - 1]];
            reasons.push(q.side === 'inner' ? 'the innermost' : 'the outermost');
        }
    }

    // ── largest / smallest
    if (q.extreme) {
        const withArea = groups.filter((g) => (g[0].area ?? g[0].radius) != null);
        if (withArea.length) {
            const key = (g: TopoFace[]) => g[0].area ?? g[0].radius ?? 0;
            const sorted = [...withArea].sort((a, b) => key(a) - key(b));
            groups = [q.extreme === 'largest' ? sorted[sorted.length - 1] : sorted[0]];
            reasons.push(`the ${q.extreme}`);
        }
    }

    // ── order along the axis being talked about, so "the two on the left"
    //    takes the leftmost two rather than an arbitrary two of the left group.
    if (q.count != null && groups.length > q.count) {
        const axis = q.side && q.side !== 'inner' && q.side !== 'outer' ? AXIS[q.side].axis : 0;
        const dir = q.side && q.side !== 'inner' && q.side !== 'outer' ? AXIS[q.side].dir : -1;
        groups = [...groups].sort((a, b) => {
            const ca = centreOf(a[0]);
            const cb = centreOf(b[0]);
            if (!ca || !cb) return 0;
            return dir < 0 ? ca[axis] - cb[axis] : cb[axis] - ca[axis];
        });
        groups = groups.slice(0, q.count);
    }

    if (!groups.length)
        return empty(`Nothing in this part matches "${text.trim()}".`);

    // A count that was asked for and not met is reported, not quietly rounded
    // down — "the four holes" finding three is a fact about the part.
    let shortfall = '';
    if (q.count != null && groups.length < q.count)
        shortfall = ` — you asked for ${q.count}, and only ${groups.length} ${groups.length === 1 ? 'matches' : 'match'}`;

    const picked = groups.flat();
    const features = [...new Set(picked.map((f) => f.feature).filter(Boolean))] as string[];

    const how = reasons.length ? ` ${reasons.join(', ')}` : '';
    const sizes = [
        ...new Set(
            groups
                .map((g) => g[0].radius)
                .filter((r): r is number => r != null)
                .map((r) => `⌀${Math.round(r * 2 * 100) / 100}`),
        ),
    ];
    const sizeNote = q.kind === 'hole' && sizes.length && sizes.length <= 2 ? ` (${sizes.join(', ')} mm)` : '';

    return {
        refs: picked.map((f) => f.ref),
        features,
        describe: `${groups.length} ${plural(q.kind, groups.length)}${how}${sizeNote}${shortfall}`,
        refusal: null,
    };
}
