import { create } from 'zustand';
import {
    listDesigns,
    createDesign,
    updateDesign,
    deleteDesign,
    fetchFeatureTree,
    type SavedDesign,
} from '../services/designsApi';
import { fullUrl } from '../services/http';
import { useStudioStore, type StudioMessage } from './studioStore';
import { useOFLStore } from './oflStore';

/** A saved part carries its Blueprint, the report it earned, and the
 *  conversation that produced it — so reopening a project restores the
 *  reasoning and not just the mesh.
 *
 *  The transcript is trimmed on the way in: `thinking` is the model's raw
 *  working notes and `steps` are live progress rows, neither of which means
 *  anything once the turn is over, and both of which are large. */
interface StoredPayload {
    blueprint?: Record<string, unknown> | null;
    variables?: Record<string, number>;
    part_class?: string;
    stats?: Record<string, unknown> | null;
    verification?: Record<string, unknown> | null;
    chat?: Partial<StudioMessage>[];
}

/** Enough of a turn to read it back. Capped so a long session cannot grow the
 *  saved row without bound. */
const CHAT_KEEP = 40;

function packChat(messages: StudioMessage[]): Partial<StudioMessage>[] {
    return messages.slice(-CHAT_KEEP).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        narrative: m.narrative,
        model: m.model,
        error: m.error,
        timestamp: m.timestamp,
        mode: m.mode,
        lens: m.lens,
    }));
}

function unpackChat(stored: Partial<StudioMessage>[] | undefined): StudioMessage[] {
    if (!Array.isArray(stored)) return [];
    return stored.map((m) => ({
        id: m.id || crypto.randomUUID(),
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content ?? '',
        steps: [],
        narrative: m.narrative ?? null,
        thinking: '',
        model: m.model ?? '',
        phase: null,
        streaming: false,
        design: null,
        error: m.error ?? null,
        timestamp: m.timestamp ?? Date.now(),
        mode: m.mode ?? 'build',
        lens: m.lens ?? 'modeling',
    }));
}

interface LibraryState {
    designs: SavedDesign[];
    loading: boolean;
    saving: boolean;
    /** Set when the last save succeeded, so the button can say so briefly. */
    savedAt: number | null;
    error: string | null;
    /** id of the saved design the studio is currently working on, if any */
    activeId: string | null;

    hydrate: () => Promise<void>;
    saveCurrent: (name?: string) => Promise<SavedDesign | null>;
    rename: (id: string, name: string) => Promise<void>;
    remove: (id: string) => Promise<void>;
    open: (id: string) => void;
    /** Forget which project is open, so the next save creates a new one. */
    detach: () => void;
    clearError: () => void;
}

/** A short, human name from the prompt — users rename, but never from blank. */
function nameFrom(prompt: string, partClass: string): string {
    const base = (partClass || prompt || 'Untitled part').replace(/_/g, ' ').trim();
    const clean = base.charAt(0).toUpperCase() + base.slice(1);
    return clean.length > 60 ? clean.slice(0, 57) + '…' : clean;
}

export const useLibraryStore = create<LibraryState>((set, get) => ({
    designs: [],
    loading: false,
    saving: false,
    savedAt: null,
    error: null,
    activeId: null,

    clearError: () => set({ error: null }),
    detach: () => set({ activeId: null }),

    hydrate: async () => {
        set({ loading: true, error: null });
        try {
            const res = await listDesigns();
            set({ designs: res.items, loading: false });
        } catch (e: any) {
            // A library that will not load must not block designing.
            set({ loading: false, error: e?.message ?? 'Loading your projects failed' });
        }
    },

    saveCurrent: async (name?: string) => {
        const studio = useStudioStore.getState();
        const part = studio.part;
        if (!part) {
            set({ error: 'there is no part to save yet' });
            return null;
        }

        set({ saving: true, error: null });
        const payload: StoredPayload = {
            blueprint: part.blueprint,
            variables: part.variables,
            part_class: part.partClass,
            stats: part.stats as unknown as Record<string, unknown>,
            verification: part.verification as unknown as Record<string, unknown>,
            chat: packChat(studio.messages),
        };

        try {
            const { activeId } = get();
            if (activeId) {
                const updated = await updateDesign(activeId, {
                    ...(name ? { name } : {}),
                    feature_graph: payload as unknown as Record<string, unknown>,
                });
                set((s) => ({
                    saving: false,
                    savedAt: Date.now(),
                    designs: s.designs.map((d) => (d.id === updated.id ? updated : d)),
                }));
                return updated;
            }

            const created = await createDesign({
                name: name || nameFrom(studio.partPrompt, part.partClass),
                // The API requires at least three characters, and a part class
                // alone can be shorter than that — which used to come back as a
                // validation error with no readable reason attached.
                prompt:
                    (studio.partPrompt || part.partClass || 'Untitled part').padEnd(3, ' '),
                feature_graph: payload as unknown as Record<string, unknown>,
                glb_path: part.files.glb,
                step_path: part.files.step,
                stl_path: part.files.stl,
                request_id: part.requestId || undefined,
            });
            set((s) => ({
                saving: false,
                savedAt: Date.now(),
                designs: [created, ...s.designs],
                activeId: created.id,
            }));
            return created;
        } catch (e: any) {
            set({ saving: false, error: e?.message ?? 'Saving the project failed' });
            return null;
        }
    },

    rename: async (id: string, name: string) => {
        const trimmed = name.trim();
        if (!trimmed) return;
        const previous = get().designs;
        // Optimistic: renaming is cheap and a round trip makes it feel broken.
        set((s) => ({
            designs: s.designs.map((d) => (d.id === id ? { ...d, name: trimmed } : d)),
        }));
        try {
            await updateDesign(id, { name: trimmed });
        } catch (e: any) {
            set({ designs: previous, error: e?.message ?? 'Renaming failed' });
        }
    },

    remove: async (id: string) => {
        const previous = get().designs;
        set((s) => ({
            designs: s.designs.filter((d) => d.id !== id),
            activeId: s.activeId === id ? null : s.activeId,
        }));
        try {
            await deleteDesign(id);
        } catch (e: any) {
            set({ designs: previous, error: e?.message ?? 'Deleting failed' });
        }
    },

    open: (id: string) => {
        const design = get().designs.find((d) => d.id === id);
        if (!design) return;

        const stored = (design.feature_graph ?? {}) as StoredPayload;
        const files = {
            glb: design.glb_path ?? undefined,
            step: design.step_path ?? undefined,
            stl: design.stl_path ?? undefined,
        };

        set({ activeId: id });

        const outcome = {
            partClass: stored.part_class ?? '',
            variables: stored.variables ?? {},
            blueprint: stored.blueprint ?? null,
            files,
            stats: (stored.stats ?? null) as any,
            verification: (stored.verification ?? null) as any,
            generationTimeMs: 0,
            requestId: '',
            // Fetched below. Null until then, which the history panel renders
            // as "no history on record" rather than as an error.
            featureTree: null,
        };

        // Reopening starts a fresh undo stack: the states this part passed
        // through in an earlier session were never saved, so offering to step
        // back into them would be offering something that does not exist.
        useStudioStore.setState({
            messages: unpackChat(stored.chat),
            history: [],
            cursor: -1,
            part: null,
            partPrompt: '',
        });
        useStudioStore.getState().adopt(outcome, design.original_prompt, design.name);

        useOFLStore.setState({
            glbUrl: fullUrl(design.glb_path),
            stepUrl: fullUrl(design.step_path),
            stlUrl: fullUrl(design.stl_path),
            error: null,
            isGenerating: false,
        });

        // The history lives with the build, not with the saved Blueprint, so it
        // comes from the server. Deliberately not awaited: the part is already
        // on screen and a side panel must not hold it up.
        fetchFeatureTree(id).then((tree) => {
            if (!tree) return;
            // Identity, not similarity: the user may have opened something else
            // while this was in flight, and two different designs can easily
            // share a part class — matching on that would attach one part's
            // history to another's geometry.
            if (get().activeId !== id) return;
            const current = useStudioStore.getState().part;
            if (current) {
                useStudioStore.setState({ part: { ...current, featureTree: tree } });
            }
        });
    },
}));
