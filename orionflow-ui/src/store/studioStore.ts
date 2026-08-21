import { create } from 'zustand';
import {
    streamStudioChat,
    rebuildPart,
    fullUrl,
    type StudioDesignResult,
    type StudioExplainResult,
    type StudioFiles,
    type StudioStats,
    type Lens,
    type RebuildRequest,
} from '../services/studioApi';
import type {
    StudioStep,
    DesignNarrative,
    FeatureTree,
} from '../services/studioApi';
import type { VerificationReport } from './../services/agentApi';
import { useDesignStore } from './designStore';
import { useOFLStore } from './oflStore';
import { useEditStore } from './editStore';
import { route, type AgentIntent } from '../lib/intent';
import { resolveSelection } from '../lib/selection';
import { readEdit, describeVariable, tidy, type Candidate } from '../lib/dimensions';

/** What a design turn produced, once it has finished. */
export interface DesignOutcome {
    partClass: string;
    variables: Record<string, number>;
    blueprint: Record<string, unknown> | null;
    files: StudioFiles;
    stats: StudioStats | null;
    verification: VerificationReport | null;
    generationTimeMs: number;
    requestId: string;
    /** How the part was built, feature by feature. Null when the server could
     *  not assemble one — the part is still valid, its history just is not
     *  known. */
    featureTree: FeatureTree | null;
    /** True once a hand edit changed the template, so the model's assertions
     *  no longer describe this geometry. The UI must stop presenting the
     *  verdict as a grade of this part. */
    contractBroken?: boolean;
}

/** One thing the assistant went and checked before it answered. */
export interface ToolCheck {
    name: string;
    ok: boolean;
    /** What it was asked — a face name, a bearing designation. */
    arguments?: Record<string, unknown>;
}

/**
 * Something the agent did to the CAD state, as opposed to something it said.
 *
 * Rendered as a chip in the transcript. The distinction is the whole point of
 * the unified agent: prose is a claim, an action is a change, and a user
 * scrolling back has to be able to tell at a glance which turns moved geometry.
 */
export interface AgentAction {
    /** SELECTED, EDITED, REBUILT, BUILT, REFUSED — one word, past tense. */
    verb: string;
    /** What it acted on, in the user's terms. */
    what: string;
    /** A number or verdict worth carrying beside it. */
    note?: string;
    tone: 'ok' | 'fail' | 'info';
}

/**
 * A question the agent needs settled before it can act.
 *
 * Exists so an ambiguous request becomes two buttons rather than a wrong
 * rebuild. Data only — the panel renders it and calls `resolveChoice`, so
 * nothing in the store holds a closure over a component.
 */
export interface AgentChoice {
    kind: 'variable';
    question: string;
    options: { id: string; label: string; hint: string }[];
    /** The reading that was blocked, replayed once an option is picked. */
    request: string;
    /** Set once answered, so the buttons resolve into a record of the answer. */
    chosen: string | null;
}

export interface StudioMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    /** Stages that actually happened, in order, as they happened. */
    steps: StudioStep[];
    /** Tool calls this turn actually made. Empty means the answer is unaided. */
    checks: ToolCheck[];
    /** Changes this turn made to the model. Empty means it only spoke. */
    actions: AgentAction[];
    /** The engineering account of the design, derived from the Blueprint. */
    narrative: DesignNarrative | null;
    /** The model's raw derivation. Working notes — kept for inspection, never
     *  presented as the explanation. */
    thinking: string;
    /** Which model answered. "orionflow" is ours; anything else is a fallback
     *  and the UI must say so. */
    model: string;
    phase: 'reasoning' | 'building' | null;
    streaming: boolean;
    design: DesignOutcome | null;
    error: string | null;
    /** What to try instead, when the turn could not do what was asked. */
    suggestion: string | null;
    choice: AgentChoice | null;
    /** True when this turn opened a design session, so the transcript renders
     *  the live plan-and-approval view inline instead of a built part. */
    showsSession: boolean;
    timestamp: number;
    /** What the router decided this turn was, and why. */
    intent: AgentIntent;
    routedBecause: string;
    /** The lens the turn was answered under, so a DFM review stays labelled
     *  as one afterwards. */
    lens: Lens;
}

function blank(
    role: 'user' | 'assistant',
    content = '',
    intent: AgentIntent = 'ask',
    lens: Lens = 'modeling',
    routedBecause = '',
): StudioMessage {
    return {
        id: crypto.randomUUID(),
        role,
        content,
        steps: [],
        checks: [],
        actions: [],
        narrative: null,
        thinking: '',
        model: '',
        phase: null,
        streaming: false,
        design: null,
        error: null,
        suggestion: null,
        choice: null,
        showsSession: false,
        timestamp: Date.now(),
        intent,
        routedBecause,
        lens,
    };
}

interface StudioState {
    messages: StudioMessage[];
    busy: boolean;
    /** A deterministic rebuild is in flight — sliders and tools are locked,
     *  but the conversation is not, because they are different systems. */
    rebuilding: boolean;
    /** The most recent successful design — context for follow-up questions. */
    part: DesignOutcome | null;
    partPrompt: string;

    /**
     * Stop a build at a plan and wait to be read.
     *
     *  The reviewed route used to be a tab of its own, which made it a
     *  different product rather than a different care level. It is a switch on
     *  the composer now: the same sentence either builds, or produces a plan
     *  that nothing gets made from until it is approved. Off by default,
     *  because most requests do not want the ceremony — but the approval gate
     *  is enforced server-side either way, so this only chooses which door the
     *  request goes through.
     */
    planFirst: boolean;
    setPlanFirst: (v: boolean) => void;

    /** Every state of the part, oldest first, and where in it we are. */
    history: { outcome: DesignOutcome; prompt: string; label: string }[];
    cursor: number;
    undo: () => void;
    redo: () => void;

    /** The one entry point. Reads the request, decides what it is, does it. */
    send: (message: string) => Promise<void>;
    /** Answer a question the agent asked, and carry on where it stopped. */
    resolveChoice: (messageId: string, optionId: string) => Promise<void>;
    /** Promote a specified brief into a build without retyping it. */
    buildThis: (brief: string) => Promise<void>;
    rebuild: (edit: Omit<RebuildRequest, 'blueprint'>, label: string) => Promise<void>;
    adopt: (outcome: DesignOutcome, prompt: string, label: string) => void;
    reset: () => void;
}

export const useStudioStore = create<StudioState>((set, get) => ({
    messages: [],
    busy: false,
    rebuilding: false,
    part: null,
    partPrompt: '',
    planFirst: false,
    history: [],
    cursor: -1,

    setPlanFirst: (planFirst) => set({ planFirst }),

    reset: () => {
        set({
            messages: [],
            part: null,
            partPrompt: '',
            busy: false,
            rebuilding: false,
            history: [],
            cursor: -1,
        });
        // The viewer holds its own copy of the geometry, so clearing the studio
        // without clearing that leaves the previous part on screen next to an
        // empty tree — which reads as a bug rather than as a new project.
        useDesignStore.setState({ creations: [], current: null });
        useOFLStore.setState({ glbUrl: '', stepUrl: '', stlUrl: '', error: null });
        useEditStore.getState().clear();
    },

    /** Take a newly built part as the current one and push it on the stack. */
    adopt: (outcome, prompt, label) => {
        const { history, cursor } = get();
        const kept = history.slice(0, cursor + 1);
        kept.push({ outcome, prompt, label });
        set({ part: outcome, partPrompt: prompt, history: kept, cursor: kept.length - 1 });
        showInViewer(prompt, outcome.files, outcome.stats);
    },

    undo: () => {
        const { cursor, history } = get();
        if (cursor <= 0) return;
        const entry = history[cursor - 1];
        set({ cursor: cursor - 1, part: entry.outcome, partPrompt: entry.prompt });
        showInViewer(entry.prompt, entry.outcome.files, entry.outcome.stats);
    },

    redo: () => {
        const { cursor, history } = get();
        if (cursor >= history.length - 1) return;
        const entry = history[cursor + 1];
        set({ cursor: cursor + 1, part: entry.outcome, partPrompt: entry.prompt });
        showInViewer(entry.prompt, entry.outcome.files, entry.outcome.stats);
    },

    buildThis: async (brief: string) => {
        await runTurn(set, get, brief, {
            intent: 'build',
            lens: 'modeling',
            because: 'you asked to build what this conversation specified',
            forced: true,
            text: brief,
        });
    },

    /** Rebuild the open part from its Blueprint — no model, no drift. */
    rebuild: async (edit, label) => {
        const part = get().part;
        if (!part?.blueprint || get().rebuilding) return;

        set({ rebuilding: true });
        try {
            const r = await rebuildPart({ blueprint: part.blueprint, ...edit });
            if (!r.success) {
                const note = blank('assistant');
                note.error = r.error || 'the edited part could not be built';
                note.suggestion =
                    'Try a smaller change, or undo to the last state that built.';
                set((s) => ({ messages: [...s.messages, note] }));
                return;
            }
            get().adopt(outcomeOf(r), get().partPrompt, label);
        } catch (err: any) {
            const note = blank('assistant');
            note.error = err?.message || 'the rebuild could not be reached';
            set((s) => ({ messages: [...s.messages, note] }));
        } finally {
            set({ rebuilding: false });
        }
    },

    /**
     * One conversation, every operation.
     *
     * The user says what they want; this decides whether that is a build, an
     * edit, a selection, a review or a question, and runs the matching path.
     * Two of the five never leave the browser — selection is resolved against
     * the topology sidecar and a retune goes straight to the deterministic
     * rebuild — so the common "point at that and make it bigger" loop costs no
     * model call at all.
     */
    send: async (message: string) => {
        // `rebuilding` as well as `busy`: a slider release and a "make it 5 mm
        // thicker" both end in a rebuild, and they are started from different
        // panels. Two in flight at once means the slower one wins `adopt` and
        // the undo stack gets an entry for a part nobody asked for. `busy`
        // alone did not cover it — that flag belongs to the conversation.
        if (!message.trim() || get().busy || get().rebuilding) return;

        const { part } = get();
        const edit = useEditStore.getState();
        const routed = route(message, {
            hasPart: !!part,
            canSelect: !!edit.topology?.faces?.length,
            hasVariables: Object.keys(part?.variables ?? {}).length > 0,
        });

        await runTurn(set, get, message, routed);
    },

    resolveChoice: async (messageId, optionId) => {
        const msg = get().messages.find((m) => m.id === messageId);
        if (!msg?.choice || msg.choice.chosen) return;

        // The answer is written into the message that asked, so scrolling back
        // shows the question and what was chosen rather than an orphaned pair
        // of buttons that no longer do anything.
        set((s) => ({
            messages: s.messages.map((m) =>
                m.id === messageId && m.choice
                    ? { ...m, choice: { ...m.choice, chosen: optionId } }
                    : m,
            ),
        }));

        // The part can have changed since the question was asked — a rebuild,
        // an undo, a different project opened. Answering into a variable that
        // is no longer there must say so rather than quietly doing nothing,
        // which is how a button comes to look broken.
        const part = get().part;
        const stale = (why: string) => {
            const note = blank('assistant', why, 'modify');
            note.actions = [{ verb: 'refused', what: optionId, tone: 'fail' }];
            set((s: StudioState) => ({ messages: [...s.messages, note] }));
        };

        if (!part?.blueprint) {
            stale('That part is no longer open, so there is nothing to retune.');
            return;
        }
        if (part.variables[optionId] == null) {
            stale(
                `\`${optionId}\` is not a dimension of the part that is open now — it has changed since I asked. Tell me the change again and I will read it against the current part.`,
            );
            return;
        }

        const value = readEdit(msg.choice.request, { [optionId]: part.variables[optionId] });
        if (!value.ok) {
            stale(
                `I could not re-read "${msg.choice.request}" as a change to \`${optionId}\`. Give me the value directly — for example "${optionId} = 12".`,
            );
            return;
        }
        await applyRetune(set, get, value.edit, msg.choice.request);
    },
}));

/* ══════════════════════════ the turn ══════════════════════════ */

type Setter = (fn: (s: StudioState) => Partial<StudioState>) => void;
type Getter = () => StudioState;

/** Route one message and run whichever path it belongs to. */
async function runTurn(
    set: any,
    get: Getter,
    message: string,
    routed: ReturnType<typeof route>,
) {
    const user = blank('user', message, routed.intent, routed.lens);
    const reply = blank('assistant', '', routed.intent, routed.lens, routed.because);
    reply.streaming = true;

    set((s: StudioState) => ({ messages: [...s.messages, user, reply], busy: true }));

    const patch = (fn: (m: StudioMessage) => StudioMessage) =>
        set((s: StudioState) => ({
            messages: s.messages.map((m) => (m.id === reply.id ? fn(m) : m)),
        }));

    try {
        if (routed.intent === 'build' && get().planFirst) {
            await runPlanned(patch, message);
        } else if (routed.intent === 'select') {
            await runSelect(patch, routed.text);
        } else if (routed.intent === 'modify') {
            await runModify(set, get, patch, routed.text);
        } else {
            await runServer(get, patch, message, routed);
        }
    } catch (err: any) {
        patch((m) => ({
            ...m,
            streaming: false,
            phase: null,
            error: err?.message || 'the turn could not be completed',
        }));
    } finally {
        set(() => ({ busy: false }));
    }
}

/* ─────────────────────── the reviewed route ─────────────────────── */

/**
 * Design it, but build nothing until someone says so.
 *
 * The session lives on the server and owns its own state machine; this only
 * starts it and marks the turn so the transcript renders the live plan. The
 * import is dynamic because `sessionStore` imports `showInViewer` from this
 * module, and a static cycle between two stores is the kind of thing that
 * works until a bundler reorders it.
 */
async function runPlanned(
    patch: (fn: (m: StudioMessage) => StudioMessage) => void,
    message: string,
) {
    const { useSessionStore } = await import('./sessionStore');

    patch((m) => ({
        ...m,
        showsSession: true,
        content:
            'Working the design out as a plan first. Nothing is built until you approve it — you can also reject it or ask for changes, and every revision is kept.',
    }));

    await useSessionStore.getState().start(message);

    const s = useSessionStore.getState();
    patch((m) => ({
        ...m,
        streaming: false,
        error: s.error?.message ?? null,
        actions: s.session
            ? [
                  {
                      verb: 'planned',
                      what: s.session.revision?.part_class?.replace(/_/g, ' ') || 'design',
                      note: s.session.state.replace(/_/g, ' '),
                      tone: 'info',
                  },
              ]
            : [{ verb: 'refused', what: 'the plan could not be started', tone: 'fail' }],
    }));
}

/* ─────────────────────── selection ─────────────────────── */

/** Point at part of the model. Never leaves the browser. */
async function runSelect(
    patch: (fn: (m: StudioMessage) => StudioMessage) => void,
    text: string,
) {
    const edit = useEditStore.getState();
    const result = resolveSelection(text, edit.topology);

    if (result.refusal) {
        patch((m) => ({
            ...m,
            streaming: false,
            content: result.refusal!,
            actions: [{ verb: 'no match', what: text.trim(), tone: 'fail' }],
            suggestion:
                'Click a face in the viewport to select it directly, or ask me what this part is made of.',
        }));
        return;
    }

    await edit.selectRefs(result.refs, result.describe);

    const featureNote =
        result.features.length === 1
            ? `They belong to **${result.features[0]}**.`
            : result.features.length > 1
              ? `They span ${result.features.length} features: ${result.features.join(', ')}.`
              : '';

    patch((m) => ({
        ...m,
        streaming: false,
        content:
            `Selected ${result.describe}. ${featureNote}`.trim() +
            (result.refs.length === 1
                ? '\n\nIts parameters are open in the inspector — say what you want changed, or edit them by hand.'
                : ''),
        actions: [
            {
                verb: 'selected',
                what: result.describe,
                note: `${result.refs.length} ${result.refs.length === 1 ? 'face' : 'faces'}`,
                tone: 'ok',
            },
        ],
    }));
}

/* ─────────────────────── modification ─────────────────────── */

/** Change a dimension of the open part, deterministically. */
async function runModify(
    set: any,
    get: Getter,
    patch: (fn: (m: StudioMessage) => StudioMessage) => void,
    text: string,
) {
    const part = get().part;
    if (!part?.blueprint) {
        patch((m) => ({
            ...m,
            streaming: false,
            content:
                'This part has no Blueprint behind it, so there is nothing to retune — it was loaded as geometry rather than built here. Describe it to me and I will build a parametric version.',
            actions: [{ verb: 'refused', what: 'no Blueprint to edit', tone: 'fail' }],
        }));
        return;
    }

    const reading = readEdit(text, part.variables);

    if (!reading.ok) {
        patch((m) => ({ ...m, streaming: false, ...refusalFor(reading, text, part.variables) }));
        return;
    }

    // Say what is about to happen, before it happens. The user gets a chance to
    // see a misread dimension while the old geometry is still on screen.
    const e = reading.edit;
    patch((m) => ({
        ...m,
        content: `I will change **${e.label}** (\`${e.variable}\`) from ${tidy(e.from)} to ${tidy(e.to)} ${e.unit} and rebuild the dependent features.`,
    }));

    await applyRetune(set, get, e, text, patch);
}

/** Perform a resolved retune and report exactly what moved. */
async function applyRetune(
    set: any,
    get: Getter,
    e: { variable: string; label: string; from: number; to: number; unit: string },
    _request: string,
    patch?: (fn: (m: StudioMessage) => StudioMessage) => void,
) {
    const part = get().part!;
    const before = part.featureTree;

    set(() => ({ rebuilding: true }));
    try {
        const r = await rebuildPart({
            blueprint: part.blueprint!,
            variables: { [e.variable]: e.to },
        });

        if (!r.success) {
            const fail = {
                streaming: false,
                error: r.error || 'the part would not rebuild at that value',
                suggestion: `The part is unchanged at ${tidy(e.from)} ${e.unit}. Try a smaller change, or ask me why that value fails.`,
                actions: [
                    { verb: 'refused', what: `${e.variable} → ${tidy(e.to)} ${e.unit}`, tone: 'fail' as const },
                ],
            };
            if (patch) patch((m) => ({ ...m, ...fail }));
            else {
                const note = blank('assistant');
                Object.assign(note, fail);
                set((s: StudioState) => ({ messages: [...s.messages, note] }));
            }
            return;
        }

        const outcome = outcomeOf(r);
        get().adopt(outcome, get().partPrompt, `${e.variable} = ${tidy(e.to)}`);

        // What else moved, measured rather than asserted. This is the sentence
        // an engineer actually needs: not "done", but which other dimensions
        // followed and which held still.
        const moved = movedParameters(before, outcome.featureTree, e.variable);
        const verdict = (outcome.verification?.verdict || '').toLowerCase();

        const held =
            (before?.features.length ?? 0) > 0 &&
            before!.features.length === (outcome.featureTree?.features.length ?? -1);

        const lines = [
            `Done. **${e.label}** is now ${tidy(e.to)} ${e.unit}, up from ${tidy(e.from)}.`,
        ];
        if (moved.length)
            lines.push(
                `Dependent dimensions followed: ${moved.map((x) => `\`${x}\``).join(', ')}.`,
            );
        if (held)
            lines.push(
                `All ${before!.features.length} features rebuilt — nothing was dropped.`,
            );
        if (verdict)
            lines.push(
                verdict === 'verified'
                    ? 'The part re-checked clean against its original assertions.'
                    : `The verdict is now **${verdict}** — worth reading the checks before you rely on it.`,
            );

        const done = {
            streaming: false,
            content: lines.join(' '),
            design: outcome,
            actions: [
                {
                    verb: 'edited',
                    what: `${e.variable}  ${tidy(e.from)} → ${tidy(e.to)} ${e.unit}`,
                    tone: 'ok' as const,
                },
                {
                    verb: 'rebuilt',
                    what: outcome.partClass?.replace(/_/g, ' ') || 'part',
                    note: verdict || undefined,
                    tone: verdict && verdict !== 'verified' ? ('info' as const) : ('ok' as const),
                },
            ],
        };

        if (patch) patch((m) => ({ ...m, ...done }));
        else {
            const note = blank('assistant', '', 'modify');
            Object.assign(note, done);
            set((s: StudioState) => ({ messages: [...s.messages, note] }));
        }
    } finally {
        set(() => ({ rebuilding: false }));
    }
}

/** Which feature parameters changed value between two builds. */
function movedParameters(
    before: FeatureTree | null,
    after: FeatureTree | null,
    driver: string,
): string[] {
    if (!before || !after) return [];
    const was = new Map<string, number>();
    for (const f of before.features)
        for (const [k, v] of Object.entries(f.parameters ?? {})) was.set(`${f.id}.${k}`, v);

    const moved: string[] = [];
    for (const f of after.features) {
        for (const [k, v] of Object.entries(f.parameters ?? {})) {
            const key = `${f.id}.${k}`;
            const old = was.get(key);
            if (old != null && Math.abs(old - v) > 1e-9) moved.push(key);
        }
    }
    // The variable the user moved is the cause, not a consequence.
    return moved.filter((m) => !m.endsWith(`.${driver}`)).slice(0, 6);
}

/** Turn a failed reading into something the user can act on. */
function refusalFor(
    reading: Extract<ReturnType<typeof readEdit>, { ok: false }>,
    text: string,
    variables: Record<string, number>,
): Partial<StudioMessage> {
    const names = Object.keys(variables);
    const list = (c: Candidate[]) =>
        c.map((x) => `\`${x.variable}\` (${x.label}, currently ${tidy(x.value)})`).join(', ');

    if (reading.reason === 'ambiguous') {
        return {
            content: `More than one dimension fits "${text.trim()}". Which did you mean?`,
            choice: {
                kind: 'variable',
                question: 'Pick the dimension to change',
                options: reading.candidates.map((c) => ({
                    id: c.variable,
                    label: c.label,
                    hint: `${c.variable} · currently ${tidy(c.value)} mm`,
                })),
                request: text,
                chosen: null,
            },
            actions: [{ verb: 'paused', what: 'more than one dimension matches', tone: 'info' }],
        };
    }

    if (reading.reason === 'no-amount') {
        return {
            content: `I can see you mean ${list(reading.candidates.slice(0, 2))} — but not by how much. Give me a value, like "12 mm" or "3 mm thicker".`,
            actions: [{ verb: 'paused', what: 'no value given', tone: 'info' }],
        };
    }

    if (reading.reason === 'not-positive') {
        return {
            content: `That arithmetic comes out at or below zero, which is not a dimension a part can have. The current value is ${tidy(reading.candidates[0]?.value ?? 0)} mm.`,
            actions: [{ verb: 'refused', what: 'value would be ≤ 0', tone: 'fail' }],
        };
    }

    return {
        content:
            names.length > 0
                ? `Nothing in this part's Blueprint matches "${text.trim()}". It drives ${names.length} named dimension${names.length === 1 ? '' : 's'}: ${names.map((n) => `\`${n}\``).join(', ')}.`
                : 'This part declares no named dimensions, so there is nothing I can retune on it.',
        suggestion:
            names.length > 0
                ? 'Name one of those, or click the face you mean and tell me what to change.'
                : undefined,
        actions: [{ verb: 'no match', what: text.trim(), tone: 'fail' }],
    };
}

/* ─────────────────────── the server routes ─────────────────────── */

/** Build, review or answer — the paths that need the model. */
async function runServer(
    get: Getter,
    patch: (fn: (m: StudioMessage) => StudioMessage) => void,
    message: string,
    routed: ReturnType<typeof route>,
) {
    const intent = routed.intent === 'build' ? 'design' : 'explain';
    const { part, messages } = get();

    const history = messages
        .filter((m) => !m.streaming && (m.content || m.role === 'user'))
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.content }));

    await streamStudioChat(
        {
            message,
            intent,
            lens: routed.lens,
            history,
            part: part ? partContext(get) : null,
            request_id: part?.requestId || undefined,
        },
        (e) => {
            switch (e.type) {
                case 'model':
                    patch((m) => ({ ...m, model: e.model }));
                    break;
                case 'phase':
                    patch((m) => ({ ...m, phase: e.phase }));
                    break;
                case 'step':
                    patch((m) => {
                        const i = m.steps.findIndex((s) => s.id === e.step.id);
                        const steps =
                            i === -1
                                ? [...m.steps, e.step]
                                : m.steps.map((s, j) => (j === i ? e.step : s));
                        return { ...m, steps };
                    });
                    break;
                case 'tool':
                    patch((m) => ({
                        ...m,
                        checks: [...m.checks, { name: e.name, ok: e.ok, arguments: e.arguments }],
                    }));
                    break;
                case 'narrative':
                    patch((m) => ({ ...m, narrative: e.narrative }));
                    break;
                case 'thinking':
                    patch((m) => ({ ...m, thinking: m.thinking + e.text }));
                    break;
                case 'answer':
                    patch((m) => ({ ...m, content: m.content + e.text }));
                    break;
                case 'built':
                    if (e.success && e.files.glb) showInViewer(message, e.files, e.stats);
                    break;
                case 'verification':
                    patch((m) => ({
                        ...m,
                        design: m.design ? { ...m.design, verification: e.report } : m.design,
                    }));
                    break;
                case 'done': {
                    if (e.result.intent === 'design') {
                        const r = e.result as StudioDesignResult;
                        const outcome = outcomeOf(r);
                        const verdict = (r.verification?.verdict || '').toLowerCase();
                        patch((m) => ({
                            ...m,
                            streaming: false,
                            phase: null,
                            model: r.model || m.model,
                            thinking: r.thinking || m.thinking,
                            narrative: r.narrative ?? m.narrative,
                            design: outcome,
                            content: r.narrative || m.narrative ? '' : m.content || summarise(outcome),
                            actions: [
                                {
                                    verb: 'built',
                                    what: (r.part_class || 'part').replace(/_/g, ' '),
                                    note: verdict || undefined,
                                    tone: verdict === 'verified' ? 'ok' : 'info',
                                },
                            ],
                        }));
                        get().adopt(outcome, message, r.part_class || 'Build');
                    } else {
                        const r = e.result as StudioExplainResult;
                        patch((m) => ({
                            ...m,
                            streaming: false,
                            phase: null,
                            model: r.model || m.model,
                            content: r.answer || m.content,
                            error: r.error ?? null,
                        }));
                    }
                    break;
                }
                case 'error':
                    patch((m) => ({
                        ...m,
                        streaming: false,
                        phase: null,
                        error: e.error,
                        model: e.model || m.model,
                        suggestion:
                            routed.intent === 'build'
                                ? 'Try naming the overall size and the features you need — for example "a 120 × 80 × 10 plate with four M6 holes on a 100 × 60 pattern".'
                                : 'Ask again more specifically, or click the feature you mean first.',
                    }));
                    break;
            }
        },
    );
}

/**
 * Everything the agent is allowed to know about the current engineering state.
 *
 * Sent with every conversational turn so the model is answering about the part
 * on screen rather than about a description of it. The selection is in here
 * deliberately: "why is this face here?" is only answerable if the server knows
 * which face "this" is.
 */
function partContext(get: Getter): Record<string, unknown> {
    const { part, partPrompt, history, cursor, messages } = get();
    if (!part) return {};
    const edit = useEditStore.getState();

    const lastError =
        [...messages].reverse().find((m) => m.role === 'assistant' && m.error)?.error ?? null;

    return {
        prompt: partPrompt,
        part_class: part.partClass,
        variables: part.variables,
        blueprint: part.blueprint,
        stats: part.stats,
        verification: part.verification,

        // ── what the user is pointing at
        selection: edit.selectedFace
            ? {
                  face: edit.selectedFace.ref,
                  feature: edit.selectedFeature,
                  surface: edit.selectedFace.surface,
                  radius: edit.selectedFace.radius ?? null,
                  area: edit.selectedFace.area ?? null,
              }
            : edit.agentRefs.length
              ? { faces: edit.agentRefs, note: edit.agentSelectionNote }
              : null,

        // ── how the part was built
        feature_tree: part.featureTree
            ? part.featureTree.features.map((f) => ({
                  id: f.id,
                  type: f.type,
                  label: f.label,
                  status: f.status,
              }))
            : null,

        // ── what has been done to it recently, newest last
        recent_operations: history.slice(Math.max(0, cursor - 4), cursor + 1).map((h) => h.label),

        // ── the last thing that went wrong, so a follow-up can address it
        last_error: lastError,

        contract_broken: !!part.contractBroken,
    };
}

/* ─────────────────────── shared ─────────────────────── */

/** The one place a server result becomes a `DesignOutcome`. */
function outcomeOf(r: {
    part_class: string;
    variables?: Record<string, number> | null;
    blueprint: Record<string, unknown> | null;
    files?: StudioFiles | null;
    stats: StudioStats | null;
    verification: VerificationReport | null;
    generation_time_ms?: number;
    request_id: string;
    feature_tree?: FeatureTree | null;
    contract_broken?: boolean;
}): DesignOutcome {
    return {
        partClass: r.part_class,
        variables: r.variables ?? {},
        blueprint: r.blueprint,
        files: r.files ?? {},
        stats: r.stats,
        verification: r.verification,
        generationTimeMs: r.generation_time_ms ?? 0,
        requestId: r.request_id,
        featureTree: r.feature_tree ?? null,
        contractBroken: r.contract_broken,
    };
}

/** One-line summary used when the model streamed no prose of its own. */
function summarise(o: DesignOutcome): string {
    const bits: string[] = [];
    if (o.partClass) bits.push(o.partClass.replace(/_/g, ' '));
    if (o.stats?.bbox_mm?.length === 3)
        bits.push(`${o.stats.bbox_mm.map((v) => Math.round(v)).join('×')} mm`);
    if (o.stats?.volume_mm3) bits.push(`${(o.stats.volume_mm3 / 1000).toFixed(2)} cm³`);
    return bits.length ? `Built — ${bits.join(' · ')}.` : 'Built.';
}

/** Push geometry into the viewer. */
export function showInViewer(
    prompt: string,
    files: StudioFiles,
    stats: StudioStats | null,
) {
    const abs = {
        glb: fullUrl(files.glb),
        step: fullUrl(files.step),
        stl: fullUrl(files.stl),
    };
    if (!abs.glb) return;

    const design = useDesignStore.getState();
    const existing = design.current;

    if (!existing) {
        design.addCreation({
            id: crypto.randomUUID(),
            prompt,
            parameters: {},
            material: { roughness: 0.5, metalness: 0.1 },
            files: abs,
        });
    } else {
        useDesignStore.setState((s) => {
            const creations = s.creations.map((c) =>
                c.id === existing.id ? { ...c, prompt, files: abs } : c,
            );
            return {
                creations,
                current: creations.find((c) => c.id === existing.id) || s.current,
            };
        });
    }

    useOFLStore.setState({
        glbUrl: abs.glb,
        stepUrl: abs.step,
        stlUrl: abs.stl,
        error: null,
        isGenerating: false,
        generationTimeMs: 0,
    });
    void stats;
}

export { describeVariable };
export type { Setter };
