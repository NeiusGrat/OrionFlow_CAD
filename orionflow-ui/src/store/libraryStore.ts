import { create } from 'zustand';
import {
    listDesigns,
    createDesign,
    updateDesign,
    deleteDesign,
    fetchFeatureTree,
    type SavedDesign,
} from '../services/designsApi';
import { fullUrl } from '../services/studioApi';
import { useDesignStore } from './designStore';
import { useStudioStore } from './studioStore';
import { useOFLStore } from './oflStore';

/** A saved part carries its Blueprint plus the report it earned, so reopening
 *  it restores the evidence and not just the mesh. */
interface StoredPayload {
    blueprint?: Record<string, unknown> | null;
    variables?: Record<string, number>;
    part_class?: string;
    stats?: Record<string, unknown> | null;
    verification?: Record<string, unknown> | null;
}

interface LibraryState {
    designs: SavedDesign[];
    loading: boolean;
    saving: boolean;
    error: string | null;
    /** id of the saved design the studio is currently working on, if any */
    activeId: string | null;

    hydrate: () => Promise<void>;
    saveCurrent: (name?: string) => Promise<SavedDesign | null>;
    rename: (id: string, name: string) => Promise<void>;
    remove: (id: string) => Promise<void>;
    open: (id: string) => void;
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
    error: null,
    activeId: null,

    clearError: () => set({ error: null }),

    hydrate: async () => {
        set({ loading: true, error: null });
        try {
            const res = await listDesigns();
            set({ designs: res.items, loading: false });
        } catch (e: any) {
            // A library that will not load must not block designing.
            set({ loading: false, error: e?.message ?? 'could not load your designs' });
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
        };

        try {
            const { activeId } = get();
            if (activeId) {
                const updated = await updateDesign(activeId, {
                    ...(name ? { name } : {}),
                    feature_graph: payload as Record<string, unknown>,
                });
                set((s) => ({
                    saving: false,
                    designs: s.designs.map((d) => (d.id === updated.id ? updated : d)),
                }));
                return updated;
            }

            const created = await createDesign({
                name: name || nameFrom(studio.partPrompt, part.partClass),
                prompt: studio.partPrompt || part.partClass || 'Untitled part',
                feature_graph: payload as Record<string, unknown>,
                glb_path: part.files.glb,
                step_path: part.files.step,
                stl_path: part.files.stl,
                request_id: part.requestId || undefined,
            });
            set((s) => ({
                saving: false,
                designs: [created, ...s.designs],
                activeId: created.id,
            }));
            return created;
        } catch (e: any) {
            set({ saving: false, error: e?.message ?? 'could not save the design' });
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
            set({ designs: previous, error: e?.message ?? 'rename failed' });
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
            set({ designs: previous, error: e?.message ?? 'delete failed' });
        }
    },

    open: (id: string) => {
        const design = get().designs.find((d) => d.id === id);
        if (!design) return;

        const stored = (design.feature_graph ?? {}) as StoredPayload;
        const files = {
            glb: fullUrl(design.glb_path),
            step: fullUrl(design.step_path),
            stl: fullUrl(design.stl_path),
        };

        set({ activeId: id });

        const ds = useDesignStore.getState();
        const existing = ds.creations.find((c) => c.id === id);
        if (existing) {
            ds.setCurrent(id);
        } else {
            ds.addCreation({
                id,
                prompt: design.original_prompt,
                parameters: (stored.variables ?? {}) as Record<string, number>,
                material: { roughness: 0.5, metalness: 0.1 },
                files,
            });
        }

        useOFLStore.setState({
            glbUrl: files.glb,
            stepUrl: files.step,
            stlUrl: files.stl,
            error: null,
            isGenerating: false,
        });

        // Restore the assistant's context so follow-up questions are about
        // THIS part rather than whatever was open before.
        useStudioStore.setState({
            part: {
                partClass: stored.part_class ?? '',
                variables: stored.variables ?? {},
                blueprint: stored.blueprint ?? null,
                files: {
                    glb: design.glb_path ?? undefined,
                    step: design.step_path ?? undefined,
                    stl: design.stl_path ?? undefined,
                },
                stats: (stored.stats ?? null) as any,
                verification: (stored.verification ?? null) as any,
                generationTimeMs: 0,
                requestId: '',
                // Fetched below. Null until then, which the history panel
                // renders as "no history on record" rather than as an error.
                featureTree: null,
            },
            partPrompt: design.original_prompt,
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
