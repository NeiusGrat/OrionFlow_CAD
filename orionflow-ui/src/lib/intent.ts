/**
 * What did the engineer just ask for?
 *
 * The studio used to make the user answer this themselves: a Refine/Build
 * switch, a Selection tab, a Reviewed-build tab. Four doors into one system,
 * and picking the wrong one either wasted a build or answered a design request
 * with prose. This decides instead, from the sentence and from what is open.
 *
 * Three properties it has to have, in this order:
 *
 *  - **It never silently destroys work.** The expensive mistake is treating a
 *    question as a design request and replacing the part on screen. So the
 *    conversational routes win ties, exactly as the server's own heuristic
 *    does, and `build` has to be positively earned.
 *  - **It says what it decided.** The verdict travels with the turn and the UI
 *    shows it, because an agent that quietly guesses wrong is worse than one
 *    that guesses wrong out loud.
 *  - **It can be overridden.** A leading `/build`, `/ask`, `/review`, `/select`
 *    or `/edit` forces the route. Cheap to implement, and it means a user who
 *    disagrees with the router is never stuck arguing with it.
 *
 * Deliberately rules rather than a model call. Routing is the one decision in
 * the loop that must be instant, free and reproducible — a classifier round
 * trip before every turn would add latency to every message and make the same
 * sentence route differently on different days.
 */

import type { Lens } from '../services/studioApi';

export type AgentIntent =
    /** Create geometry that does not exist yet. The only metered route. */
    | 'build'
    /** Change a dimension of the part already open. */
    | 'modify'
    /** Point at features. Resolved locally; costs nothing. */
    | 'select'
    /** Critique the open part — manufacturability, and what would go wrong. */
    | 'review'
    /** Anything else: questions, measurements, explanations. */
    | 'ask';

export interface Routed {
    intent: AgentIntent;
    /** Which lens the answer should be written under. */
    lens: Lens;
    /** Why this route was chosen, in words a user can read. */
    because: string;
    /** True when the user forced it with a slash prefix. */
    forced: boolean;
    /** The message with any slash prefix stripped. */
    text: string;
}

/* ─────────────────────────── vocabulary ─────────────────────────── */

/** Verbs that ask for geometry to exist. */
const CREATE = /\b(create|build|make me|design|generate|model|draw|give me|i need|i want)\b/;

/** Verbs that change something that is already there. */
const CHANGE =
    /\b(increase|decrease|reduce|enlarge|shrink|widen|narrow|thicken|deepen|lengthen|shorten|raise|lower|resize|rescale|change|set|adjust|tweak|retune|tune|bump|scale)\b/;

/** Comparatives that imply a change without naming a verb: "5 mm thicker". */
const COMPARATIVE =
    /\b(thicker|thinner|taller|shorter|wider|narrower|bigger|larger|smaller|deeper|longer|stronger|lighter|heavier)\b/;

/** Verbs that point at something. */
const POINT = /\b(select|highlight|pick|isolate|show me the|find the|which face|where is)\b/;

/** Asking for a judgement rather than a fact. */
const CRITIQUE =
    /\b(review|critique|audit|assess|evaluate|sanity[- ]check|check (?:this|it|the)|any (?:problems|issues|concerns)|what(?:'s| is) wrong|problems?|issues?|risks?|weak|fail)\b/;

const MANUFACTURING =
    /\b(manufactur\w*|machin\w*|mill\w*|lathe|turn\w*|cnc|3d[- ]print\w*|print\w*|additive|overhang|support|sheet[- ]metal|bend|brake|flat pattern|dfm|tooling|mould|mold|cast\w*|injection|draft angle|undercut|tolerance|fit|finish)\b/;

/** Openers that mean a question even without a question mark. */
const ASK_OPENER =
    /^(why|what|what's|whats|how|explain|describe|tell me|is it|is the|are the|are there|does it|does the|do the|can it|can the|could|should|which|who|when|where|would|will|did|has|have|list|summari[sz]e|compare)\b/;

/** Units and bare numbers — evidence that a dimension is being talked about. */
const HAS_NUMBER = /(?:^|[\s(])[-+]?\d+(?:\.\d+)?\s*(mm|cm|m\b|in\b|"|deg|degrees?|°|%)?/;

/** Words naming a dimension of a part. */
const DIMENSION_WORD =
    /\b(thick\w*|thin\w*|width|wide|height|tall|length|long|depth|deep|diameter|dia\b|radius|rad\b|bore|hole|gap|clearance|pitch|spacing|offset|angle|chamfer|fillet|wall|rib|boss|flange|size|dimension)\b/;

/** Nouns that name a thing an engineer would ask us to select. */
const FEATURE_WORD =
    /\b(hole|holes|bore|bores|face|faces|edge|edges|fillet|fillets|chamfer|chamfers|pocket|pockets|slot|slots|boss|bosses|rib|ribs|wall|walls|feature|features|surface|surfaces|corner|corners|top|bottom|side|sides|left|right|front|back|inner|outer)\b/;

/* ─────────────────────────── lens ─────────────────────────── */

/** Which manufacturing lens a sentence is asking to be read under.
 *
 *  Only ever narrows a review. The design path is left exactly as the model was
 *  fine-tuned and graded, because 94% VERIFIED was measured on that prompt
 *  distribution and prepending a process brief moves the model off it. */
export function inferLens(text: string): Lens {
    const t = text.toLowerCase();
    if (/\b(3d[- ]print\w*|printab\w*|additive|fdm|sla|overhang|layer|support material)\b/.test(t))
        return 'dfm_3d_printing';
    if (/\b(sheet[- ]metal|bend|brake|flat pattern|k[- ]factor|relief cut|gauge)\b/.test(t))
        return 'dfm_sheet_metal';
    if (/\b(machin\w*|mill\w*|lathe|turn\w*|cnc|tool access|end ?mill|setup|fixtur\w*|internal radi)\b/.test(t))
        return 'dfm_machining';
    if (MANUFACTURING.test(t)) return 'dfm';
    return 'modeling';
}

/* ─────────────────────────── routing ─────────────────────────── */

const FORCED: Record<string, AgentIntent> = {
    build: 'build',
    make: 'build',
    ask: 'ask',
    explain: 'ask',
    review: 'review',
    dfm: 'review',
    select: 'select',
    edit: 'modify',
    modify: 'modify',
    set: 'modify',
};

export interface RouteContext {
    /** A part is open and has a Blueprint behind it, so it can be edited. */
    hasPart: boolean;
    /** The topology sidecar loaded, so selection can actually be resolved. */
    canSelect: boolean;
    /** The part declares named variables, so a retune has something to move. */
    hasVariables: boolean;
}

/**
 * Decide what to do with one message.
 *
 * Reads top to bottom; the first rule that fires wins. The order encodes the
 * cost of being wrong, not the likelihood of being right.
 */
export function route(message: string, ctx: RouteContext): Routed {
    const raw = message.trim();

    // An explicit slash prefix is an instruction, not a hint. Honoured before
    // anything else and never second-guessed.
    const slash = raw.match(/^\/([a-z]+)\s+([\s\S]+)$/i);
    if (slash) {
        const forcedIntent = FORCED[slash[1].toLowerCase()];
        if (forcedIntent) {
            const text = slash[2].trim();
            return {
                intent: forcedIntent,
                lens: forcedIntent === 'review' ? inferLens(text) || 'dfm' : inferLens(text),
                because: `you asked for /${slash[1].toLowerCase()}`,
                forced: true,
                text,
            };
        }
    }

    const t = raw.toLowerCase();
    const question = t.endsWith('?') || ASK_OPENER.test(t);

    // Nothing is open, so there is nothing to point at, edit or review. Every
    // route but two collapses into "make something".
    if (!ctx.hasPart) {
        if (question && !CREATE.test(t)) {
            return {
                intent: 'ask',
                lens: inferLens(t),
                because: 'a question, and no part is open yet',
                forced: false,
                text: raw,
            };
        }
        return {
            intent: 'build',
            lens: 'modeling',
            because: 'nothing is open yet, so this describes a part to build',
            forced: false,
            text: raw,
        };
    }

    // ── Pointing. Cheapest to be wrong about: a bad selection changes no
    //    geometry and is undone by clicking elsewhere.
    if (ctx.canSelect && POINT.test(t) && FEATURE_WORD.test(t) && !CREATE.test(t)) {
        return {
            intent: 'select',
            lens: 'modeling',
            because: 'you asked to point at part of the model',
            forced: false,
            text: raw,
        };
    }

    // ── Judgement. Checked before modification, because "check the wall
    //    thickness" names a dimension but is asking to be told, not to be
    //    changed.
    if (CRITIQUE.test(t) || (MANUFACTURING.test(t) && question)) {
        return {
            intent: 'review',
            lens: inferLens(t) === 'modeling' ? 'dfm' : inferLens(t),
            because: 'you asked for a judgement on the open part',
            forced: false,
            text: raw,
        };
    }

    // ── Change. Has to name a change and carry a number, or use a comparative
    //    that implies one. A question is never a change, however it is phrased:
    //    "should the plate be thicker?" asks, it does not instruct.
    if (
        ctx.hasVariables &&
        !question &&
        (CHANGE.test(t) || COMPARATIVE.test(t)) &&
        (HAS_NUMBER.test(t) || COMPARATIVE.test(t)) &&
        (DIMENSION_WORD.test(t) || HAS_NUMBER.test(t))
    ) {
        return {
            intent: 'modify',
            lens: 'modeling',
            because: 'you asked to change a dimension of the open part',
            forced: false,
            text: raw,
        };
    }

    // ── A new part. Only when a create verb is present: with a model already
    //    on screen, replacing it is the one action that throws work away, so it
    //    is never inferred from a bare noun phrase.
    if (CREATE.test(t) && !question) {
        return {
            intent: 'build',
            lens: 'modeling',
            because: 'you asked for a new part to be built',
            forced: false,
            text: raw,
        };
    }

    // ── Everything else is conversation, which is free and reversible.
    return {
        intent: 'ask',
        lens: inferLens(t),
        because: question
            ? 'a question about the open part'
            : 'nothing here asks to change or replace the part',
        forced: false,
        text: raw,
    };
}

/** What the agent says it is about to do, before it does it. */
export const INTENT_VERB: Record<AgentIntent, string> = {
    build: 'Building',
    modify: 'Editing',
    select: 'Selecting',
    review: 'Reviewing',
    ask: 'Thinking',
};

/** Past tense, for the record left behind afterwards. */
export const INTENT_LABEL: Record<AgentIntent, string> = {
    build: 'Built',
    modify: 'Edited',
    select: 'Selected',
    review: 'Reviewed',
    ask: 'Answered',
};
