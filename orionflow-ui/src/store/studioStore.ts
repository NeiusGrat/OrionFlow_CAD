import { create } from 'zustand';
import {
    streamStudioChat,
    fullUrl,
    type StudioDesignResult,
    type StudioExplainResult,
    type StudioFiles,
    type StudioStats,
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
}

export interface StudioMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    /** Stages that actually happened, in order, as they happened. */
    steps: StudioStep[];
    /** The engineering account of the design, derived from the Blueprint.
     *  This is what the user reads; `thinking` and the Blueprint JSON stay
     *  available underneath for debugging. */
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
}

function blank(role: 'user' | 'assistant', content = ''): StudioMessage {
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
    };
}

interface StudioState {
    messages: StudioMessage[];
    busy: boolean;
    /** The most recent successful design — context for follow-up questions. */
    part: DesignOutcome | null;
    partPrompt: string;

    send: (message: string, intent?: 'design' | 'explain') => Promise<void>;
    reset: () => void;
}

export const useStudioStore = create<StudioState>((set, get) => ({
    messages: [],
    busy: false,
    part: null,
    partPrompt: '',

    reset: () => set({ messages: [], part: null, partPrompt: '', busy: false }),

    send: async (message: string, intent?: 'design' | 'explain') => {
        if (!message.trim() || get().busy) return;

        const user = blank('user', message);
        const reply = blank('assistant');
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
                                set({ part: outcome, partPrompt: message });
                                showInViewer(message, r.files, r.stats);
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
                }
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

/** Push geometry into the existing viewer + version timeline. */
function showInViewer(prompt: string, files: StudioFiles, stats: StudioStats | null) {
    const abs = {
        glb: fullUrl(files.glb),
        step: fullUrl(files.step),
        stl: fullUrl(files.stl),
    };
    if (!abs.glb) return;

    const design = useDesignStore.getState();
    const existing = design.current;

    if (!existing) {
        const id = crypto.randomUUID();
        design.addCreation({
            id,
            prompt,
            parameters: {},
            material: { roughness: 0.5, metalness: 0.1 },
            files: abs,
        });
        design.addVersion(id, {
            label: prompt,
            timestamp: Date.now(),
            files: abs,
            oflCode: '',
            parameters: {},
        });
    } else {
        useDesignStore.setState((s) => {
            const creations = s.creations.map((c) =>
                c.id === existing.id ? { ...c, files: abs } : c
            );
            return {
                creations,
                current: creations.find((c) => c.id === existing.id) || s.current,
            };
        });
        design.addVersion(existing.id, {
            label: prompt,
            timestamp: Date.now(),
            files: abs,
            oflCode: '',
            parameters: {},
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
