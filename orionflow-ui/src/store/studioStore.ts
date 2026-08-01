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
import type { VerificationReport } from '../services/agentApi';
import { useDesignStore } from './designStore';
import { useOFLStore } from './oflStore';

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

export interface StudioMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    /** Stages that actually happened, in order, as they happened. */
    steps: StudioStep[];
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
    timestamp: number;
    /** Which mode produced this turn — a refine answer is offered a "Build
     *  this" action, a build answer already is one. */
    mode: StudioMode;
    /** The lens the turn was answered under, so a DFM review stays labelled
     *  as one when the selector moves on. */
    lens: Lens;
}

/** Refine talks the idea through; Build commits it to geometry. */
export type StudioMode = 'refine' | 'build';

function blank(
    role: 'user' | 'assistant',
    content = '',
    mode: StudioMode = 'build',
    lens: Lens = 'modeling',
): StudioMessage {
    return {
        id: crypto.randomUUID(),
        role,
        content,
        steps: [],
        narrative: null,
        thinking: '',
        model: '',
        phase: null,
        streaming: false,
        design: null,
        error: null,
        timestamp: Date.now(),
        mode,
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

    mode: StudioMode;
    lens: Lens;
    setMode: (m: StudioMode) => void;
    setLens: (l: Lens) => void;

    /** Every state of the part, oldest first, and where in it we are. This is
     *  what undo and redo move through: each entry is a solid that was really
     *  built, not a replayed command. */
    history: { outcome: DesignOutcome; prompt: string; label: string }[];
    cursor: number;
    undo: () => void;
    redo: () => void;

    send: (message: string, override?: Partial<{ mode: StudioMode; lens: Lens }>) => Promise<void>;
    /** Promote a refined brief into a build without retyping it. */
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
    mode: 'build',
    lens: 'modeling',
    history: [],
    cursor: -1,

    setMode: (mode) => set({ mode }),
    setLens: (lens) => set({ lens }),

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
    },

    /** Take a newly built part as the current one and push it on the stack.
     *
     *  Anything ahead of the cursor is dropped: building after an undo forks
     *  the history, and keeping the abandoned branch reachable through redo
     *  would let the user step forward into a part that no longer follows from
     *  what is on screen. */
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
        set({ mode: 'build' });
        await get().send(brief, { mode: 'build' });
    },

    /** Rebuild the open part from its Blueprint — no model, no drift.
     *
     *  Parameter changes and workbench tools both land here. The result is
     *  adopted exactly like a generated part, so undo covers hand edits too. */
    rebuild: async (edit, label) => {
        const part = get().part;
        if (!part?.blueprint || get().rebuilding) return;

        set({ rebuilding: true });
        try {
            const r = await rebuildPart({ blueprint: part.blueprint, ...edit });
            if (!r.success) {
                // A rebuild that will not build is reported in the conversation,
                // because that is where the user is watching for consequences.
                const note = blank('assistant', '', get().mode, get().lens);
                note.error = r.error || 'the edited part could not be built';
                set((s) => ({ messages: [...s.messages, note] }));
                return;
            }
            const outcome: DesignOutcome = {
                partClass: r.part_class,
                variables: r.variables ?? {},
                blueprint: r.blueprint,
                files: r.files ?? {},
                stats: r.stats,
                verification: r.verification,
                generationTimeMs: r.generation_time_ms,
                requestId: r.request_id,
                featureTree: r.feature_tree ?? null,
                contractBroken: r.contract_broken || part.contractBroken,
            };
            get().adopt(outcome, get().partPrompt, label);
        } catch (err: any) {
            const note = blank('assistant', '', get().mode, get().lens);
            note.error = err?.message || 'the rebuild could not be reached';
            set((s) => ({ messages: [...s.messages, note] }));
        } finally {
            set({ rebuilding: false });
        }
    },

    send: async (message: string, override) => {
        if (!message.trim() || get().busy) return;

        const mode = override?.mode ?? get().mode;
        const lens = override?.lens ?? get().lens;
        // Refine talks; Build commits. The server infers an intent when none is
        // given, but the mode switch is an explicit instruction from the user
        // and must not be second-guessed.
        const intent = mode === 'refine' ? 'explain' : 'design';

        const user = blank('user', message, mode, lens);
        const reply = blank('assistant', '', mode, lens);
        reply.streaming = true;

        set((s) => ({ messages: [...s.messages, user, reply], busy: true }));

        const patch = (fn: (m: StudioMessage) => StudioMessage) =>
            set((s) => ({
                messages: s.messages.map((m) => (m.id === reply.id ? fn(m) : m)),
            }));

        const { part, partPrompt, messages } = get();
        const history = messages
            .filter((m) => !m.streaming && (m.content || m.role === 'user'))
            .slice(-6)
            .map((m) => ({ role: m.role, content: m.content }));

        try {
            await streamStudioChat(
                {
                    message,
                    intent,
                    lens,
                    history,
                    part: part
                        ? {
                              prompt: partPrompt,
                              part_class: part.partClass,
                              variables: part.variables,
                              blueprint: part.blueprint,
                              stats: part.stats,
                              verification: part.verification,
                          }
                        : null,
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
                            // A step re-reported with a new status replaces the
                            // earlier one, so "active" becomes "done" in place
                            // rather than accumulating duplicates.
                            patch((m) => {
                                const i = m.steps.findIndex((s) => s.id === e.step.id);
                                const steps =
                                    i === -1
                                        ? [...m.steps, e.step]
                                        : m.steps.map((s, j) => (j === i ? e.step : s));
                                return { ...m, steps };
                            });
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
                            // Geometry exists — show it immediately rather than
                            // waiting for the verdict, so the viewer fills while
                            // the checks run.
                            if (e.success && e.files.glb) {
                                showInViewer(message, e.files, e.stats);
                            }
                            break;
                        case 'verification':
                            patch((m) => ({
                                ...m,
                                design: m.design
                                    ? { ...m.design, verification: e.report }
                                    : m.design,
                            }));
                            break;
                        case 'done': {
                            if (e.result.intent === 'design') {
                                const r = e.result as StudioDesignResult;
                                const outcome: DesignOutcome = {
                                    partClass: r.part_class,
                                    variables: r.variables ?? {},
                                    blueprint: r.blueprint,
                                    files: r.files ?? {},
                                    stats: r.stats,
                                    verification: r.verification,
                                    generationTimeMs: r.generation_time_ms,
                                    requestId: r.request_id,
                                    featureTree: r.feature_tree ?? null,
                                };
                                patch((m) => ({
                                    ...m,
                                    streaming: false,
                                    phase: null,
                                    model: r.model || m.model,
                                    thinking: r.thinking || m.thinking,
                                    narrative: r.narrative ?? m.narrative,
                                    design: outcome,
                                    // Only fall back to a one-liner when the
                                    // narrative is absent; otherwise the
                                    // narrative IS the answer.
                                    content:
                                        r.narrative || m.narrative
                                            ? ''
                                            : m.content || summarise(outcome),
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
                            }));
                            break;
                    }
                },
            );
        } catch (err: any) {
            patch((m) => ({
                ...m,
                streaming: false,
                phase: null,
                error: err?.message || 'the connection dropped',
            }));
        } finally {
            set({ busy: false });
        }
    },
}));

/** One-line summary used when the model streamed no prose of its own. */
function summarise(o: DesignOutcome): string {
    const bits: string[] = [];
    if (o.partClass) bits.push(o.partClass.replace(/_/g, ' '));
    if (o.stats?.bbox_mm?.length === 3)
        bits.push(`${o.stats.bbox_mm.map((v) => Math.round(v)).join('×')} mm`);
    if (o.stats?.volume_mm3)
        bits.push(`${(o.stats.volume_mm3 / 1000).toFixed(2)} cm³`);
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

    // Keep the shared panels (viewer status line, exports) consistent.
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
