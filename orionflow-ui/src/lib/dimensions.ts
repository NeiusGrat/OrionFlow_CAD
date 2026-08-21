/**
 * Turning "make the bracket 5 mm thicker" into a variable and a number.
 *
 * The Blueprint names every dimension it drives — `plate_t`, `bore_d`,
 * `hole_pcd` — and `POST /studio/rebuild` will retune any of them and re-grade
 * the result against the same assertions. What was missing was the join between
 * the engineer's words and those names, and without it the only way to change a
 * dimension was to find its slider.
 *
 * This is deliberately arithmetic and a synonym table rather than a model call.
 * Three reasons, and they are the whole design:
 *
 *  - **A wrong edit is expensive.** It rebuilds the part. A rule that cannot
 *    resolve the target refuses and asks; a model asked to pick a variable will
 *    always pick one.
 *  - **It has to be explainable.** The agent announces the change before it
 *    makes it — "plate_t, 8 → 13 mm" — and that sentence has to be derived from
 *    the same thing that performs the edit, or it is a caption rather than a
 *    statement.
 *  - **It has to be free.** Reading the request costs nothing, so an ambiguous
 *    one can be handed back as a choice instead of a build.
 */

/** A dimension concept, independent of how the Blueprint spelled it. */
type Concept =
    | 'thickness'
    | 'diameter'
    | 'radius'
    | 'width'
    | 'length'
    | 'height'
    | 'depth'
    | 'gap'
    | 'pitch'
    | 'angle'
    | 'fillet'
    | 'chamfer'
    | 'count';

/** Every spelling of a concept we have seen come out of a Blueprint or a
 *  sentence. Abbreviations are listed because variable names are terse and
 *  engineers speak in them too. */
const SYNONYMS: Record<Concept, string[]> = {
    thickness: ['t', 'th', 'thk', 'thick', 'thickness', 'wall', 'walls', 'plate', 'gauge', 'thicker', 'thinner'],
    diameter: ['d', 'dia', 'diam', 'diameter', 'bore', 'hole', 'holes', 'od', 'id', 'shaft', 'pin'],
    radius: ['r', 'rad', 'radius', 'radii'],
    width: ['w', 'wid', 'width', 'wide', 'across', 'wider', 'narrower'],
    length: ['l', 'len', 'length', 'long', 'longer', 'span'],
    height: ['h', 'hgt', 'ht', 'height', 'tall', 'taller', 'high', 'rise'],
    depth: ['dp', 'depth', 'deep', 'deeper', 'sink', 'counterbore', 'cbore'],
    gap: ['gap', 'clearance', 'clr', 'slot', 'kerf', 'offset'],
    pitch: ['pitch', 'pcd', 'spacing', 'spaced', 'centres', 'centers', 'bolt circle', 'circle'],
    angle: ['ang', 'angle', 'deg', 'degrees', 'draft', 'taper'],
    fillet: ['fillet', 'fil', 'round', 'rounding'],
    chamfer: ['chamfer', 'cham', 'cha', 'bevel'],
    count: ['n', 'num', 'count', 'qty', 'quantity', 'number'],
};

/** Reverse index: one word → the concepts it can mean. */
const CONCEPT_OF = (() => {
    const m = new Map<string, Concept[]>();
    for (const [concept, words] of Object.entries(SYNONYMS) as [Concept, string[]][]) {
        for (const w of words) {
            const list = m.get(w) ?? [];
            list.push(concept);
            m.set(w, list);
        }
    }
    return m;
})();

/** Human words for a concept, used when explaining the edit. */
const CONCEPT_WORD: Record<Concept, string> = {
    thickness: 'thickness',
    diameter: 'diameter',
    radius: 'radius',
    width: 'width',
    length: 'length',
    height: 'height',
    depth: 'depth',
    gap: 'gap',
    pitch: 'pitch',
    angle: 'angle',
    fillet: 'fillet radius',
    chamfer: 'chamfer',
    count: 'count',
};

/** Split a variable name into its words: `plate_t` → [plate, t]. */
export function tokens(name: string): string[] {
    return name
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .split(/[^A-Za-z0-9]+/)
        .filter(Boolean)
        .map((s) => s.toLowerCase());
}

function conceptsOf(words: string[]): Set<Concept> {
    const out = new Set<Concept>();
    for (const w of words) for (const c of CONCEPT_OF.get(w) ?? []) out.add(c);
    return out;
}

/**
 * A readable name for a Blueprint variable.
 *
 * `plate_t` → "plate thickness". Used in the sentence the agent says before it
 * edits, so the user can tell whether the right dimension was understood before
 * the geometry moves rather than after.
 */
export function describeVariable(name: string): string {
    const ws = tokens(name);
    const out: string[] = [];
    for (const w of ws) {
        const cs = CONCEPT_OF.get(w) ?? [];
        // A word that is only an abbreviation gets expanded; a word that is a
        // real noun ("plate", "bore") is left as the engineer wrote it.
        if (cs.length && w.length <= 3) out.push(CONCEPT_WORD[cs[0]]);
        else out.push(w);
    }
    const phrase = out.join(' ').trim();
    return phrase || name;
}

/* ─────────────────────── matching a variable ─────────────────────── */

export interface Candidate {
    variable: string;
    value: number;
    score: number;
    /** Readable form, for offering the choice back to the user. */
    label: string;
}

/**
 * Rank the part's variables against the words of a request.
 *
 * Scoring is blunt on purpose — an exact name beats everything, a shared
 * concept beats a shared noun, and a bare concept match is worth having only
 * when nothing else competes with it.
 */
export function rankVariables(
    request: string,
    variables: Record<string, number>,
): Candidate[] {
    const q = request.toLowerCase();
    const qWords = q.split(/[^a-z0-9]+/).filter(Boolean);
    const qConcepts = conceptsOf(qWords);

    const out: Candidate[] = [];
    for (const [variable, value] of Object.entries(variables)) {
        const vWords = tokens(variable);
        const vConcepts = conceptsOf(vWords);
        let score = 0;

        // The user typed the variable itself. Nothing else comes close.
        if (q.includes(variable.toLowerCase())) score += 100;

        // A shared concept: "thicker" ↔ `plate_t`.
        for (const c of vConcepts) if (qConcepts.has(c)) score += 10;

        // A shared noun that is not just an abbreviation: "hole" ↔ `hole_d`.
        // Worth more than a concept because it narrows *which* one.
        for (const w of vWords) {
            if (w.length >= 3 && qWords.includes(w)) score += 8;
            // "holes" in the request, `hole` in the name.
            else if (w.length >= 4 && qWords.some((x) => x.startsWith(w) || w.startsWith(x)))
                score += 4;
        }

        // The measurement, weighted above everything but an exact name.
        //
        // CAD variables are written qualifier-first and measure-last —
        // `hole_d`, `hole_pcd`, `plate_t` — so the final token says *what is
        // being measured* and the ones before it say *of what*. Without this,
        // "the hole diameter" scored `hole_d` and `hole_pcd` identically: both
        // share the word "hole" and both carry the diameter concept through it,
        // so a perfectly unambiguous request came back as a choice between two
        // options. Matching the measure token settles it, and settles it the
        // way an engineer reads the name.
        const measure = vWords[vWords.length - 1];
        const measureConcepts = CONCEPT_OF.get(measure) ?? [];
        if (measureConcepts.some((c) => qConcepts.has(c))) score += 14;

        if (score > 0) out.push({ variable, value, score, label: describeVariable(variable) });
    }

    return out.sort((a, b) => b.score - a.score || a.variable.localeCompare(b.variable));
}

/* ─────────────────────── reading the number ─────────────────────── */

const UP = /\b(increase|raise|enlarge|widen|thicken|deepen|lengthen|bump|grow|extend|bigger|larger|thicker|taller|wider|deeper|longer|more)\b/;
const DOWN = /\b(decrease|reduce|shrink|narrow|shorten|lower|trim|thinner|shorter|narrower|smaller|less|tighter)\b/;

export interface Amount {
    /** How the new value is derived from the old one. */
    kind: 'absolute' | 'delta' | 'scale';
    /** mm for absolute and delta; a multiplier for scale. */
    amount: number;
    /** The unit the user wrote, if any — echoed back so we speak their units. */
    unit: string;
}

/**
 * What number the sentence is asking for, and how it relates to the old value.
 *
 * `to 12 mm` is absolute. `by 5` and `5 mm thicker` are deltas whose sign comes
 * from the verb. `20% bigger`, `double` and `halve` are scales. Anything with no
 * number at all reads as null rather than as a guess — "make it thicker" does
 * not say how much, and inventing a number would be the system deciding an
 * engineering value on its own.
 */
export function readAmount(request: string): Amount | null {
    const t = request.toLowerCase();

    if (/\bdoubl(e|ed|ing)\b/.test(t)) return { kind: 'scale', amount: 2, unit: '' };
    if (/\b(halve|half)\b/.test(t)) return { kind: 'scale', amount: 0.5, unit: '' };

    const pct = t.match(/([-+]?\d+(?:\.\d+)?)\s*%/);
    if (pct) {
        const p = parseFloat(pct[1]) / 100;
        // "by 20%" is a change of a fifth; "to 120%" would be odd phrasing and
        // is not supported, so every percentage is read as a relative change.
        return { kind: 'scale', amount: DOWN.test(t) ? 1 - p : 1 + p, unit: '%' };
    }

    const num = t.match(/([-+]?\d+(?:\.\d+)?)\s*(mm|cm|millimet\w*|centimet\w*|deg\w*|°)?/);
    if (!num) return null;

    let amount = parseFloat(num[1]);
    let unit = (num[2] || '').replace(/millimet\w*/, 'mm').replace(/centimet\w*/, 'cm');
    // Everything downstream is millimetres, because the Blueprint is.
    if (unit === 'cm') {
        amount *= 10;
        unit = 'mm';
    }
    if (/^(deg|°)/.test(unit)) unit = '°';

    const relative = /\bby\b/.test(t) || (!/\bto\b/.test(t) && (UP.test(t) || DOWN.test(t)));
    if (relative) {
        const sign = DOWN.test(t) ? -1 : 1;
        return { kind: 'delta', amount: Math.abs(amount) * sign, unit: unit || 'mm' };
    }
    return { kind: 'absolute', amount, unit: unit || 'mm' };
}

/* ─────────────────────── the whole reading ─────────────────────── */

export interface ResolvedEdit {
    variable: string;
    label: string;
    from: number;
    to: number;
    unit: string;
    /** Everything else that scored, in case the top pick is wrong. */
    alternatives: Candidate[];
}

export type EditReading =
    | { ok: true; edit: ResolvedEdit }
    /** Understood the dimension but not the number. */
    | { ok: false; reason: 'no-amount'; candidates: Candidate[] }
    /** Understood the number but not which dimension, and more than one fits. */
    | { ok: false; reason: 'ambiguous'; candidates: Candidate[]; amount: Amount }
    /** Nothing in the part matches what was named. */
    | { ok: false; reason: 'no-match'; candidates: Candidate[]; amount: Amount | null }
    /** The arithmetic produced a value no part can have. */
    | { ok: false; reason: 'not-positive'; candidates: Candidate[]; amount: Amount };

/** How clearly the best candidate has to beat the next one to act unasked. */
const DECISIVE = 1.4;

/**
 * Read a modification request against the open part.
 *
 * Returns a refusal rather than a guess whenever the sentence does not pin down
 * both halves of the edit. The refusals carry their candidates, so the panel can
 * turn "which of these did you mean?" into two buttons instead of a dead end.
 */
export function readEdit(
    request: string,
    variables: Record<string, number>,
): EditReading {
    const ranked = rankVariables(request, variables);
    const amount = readAmount(request);

    if (!ranked.length) return { ok: false, reason: 'no-match', candidates: [], amount };

    const [best, second] = ranked;
    const decisive = !second || best.score >= second.score * DECISIVE;

    if (!amount) {
        return { ok: false, reason: 'no-amount', candidates: ranked.slice(0, 4) };
    }
    if (!decisive) {
        return { ok: false, reason: 'ambiguous', candidates: ranked.slice(0, 4), amount };
    }

    const from = best.value;
    const to =
        amount.kind === 'absolute'
            ? amount.amount
            : amount.kind === 'delta'
              ? from + amount.amount
              : from * amount.amount;

    // A dimension of zero or less is not a dimension. Caught here rather than
    // by the kernel, so the user is told what the arithmetic came to instead of
    // watching a build fail.
    if (!(to > 0) || !Number.isFinite(to)) {
        return { ok: false, reason: 'not-positive', candidates: ranked.slice(0, 4), amount };
    }

    return {
        ok: true,
        edit: {
            variable: best.variable,
            label: best.label,
            from,
            // Guards against 8 + 5 = 13.000000000000002 reaching a dimension.
            to: Math.round(to * 1e6) / 1e6,
            unit: amount.unit || 'mm',
            alternatives: ranked.slice(1, 4),
        },
    };
}

/** Sensible decimals for a dimension of this magnitude. */
export function tidy(n: number): string {
    const abs = Math.abs(n);
    if (abs >= 100) return n.toFixed(1).replace(/\.0$/, '');
    if (abs >= 10) return String(Math.round(n * 100) / 100);
    return String(Math.round(n * 1000) / 1000);
}
