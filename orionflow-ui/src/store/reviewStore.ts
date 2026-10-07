/**
 * The one selection model for OrionFlow Review.
 *
 * Selecting a part anywhere — 3D pick, tree row, command palette, later a
 * finding, BOM row or sim body — writes here, and every panel reads from
 * here. No panel keeps its own idea of "what is selected".
 */
import { create } from 'zustand';

export type EntityKind = 'instance' | 'part' | 'contact';

export interface Selection {
    kind: EntityKind;
    id: string;
}

interface ReviewState {
    selection: Selection | null;
    hovered: string | null;            // instance id under the pointer
    hoveredFeature: string | null;     // feature id (inspector row under the pointer)
    showContacts: boolean;
    hidden: Set<string>;               // hidden instance ids
    isolated: string[] | null;         // instance ids shown alone, or null
    fitRequest: number;                // bump to ask the viewer to frame the selection (or all)
    select: (s: Selection | null, frame?: boolean) => void;
    hover: (iid: string | null) => void;
    hoverFeature: (fid: string | null) => void;
    setShowContacts: (on: boolean) => void;
    toggleHidden: (ids: string[]) => void;
    showAll: () => void;
    isolate: (ids: string[] | null) => void;
    requestFit: () => void;
    reset: () => void;
}

export const useReview = create<ReviewState>((set) => ({
    selection: null,
    hovered: null,
    hoveredFeature: null,
    showContacts: false,
    hidden: new Set(),
    isolated: null,
    fitRequest: 0,
    select: (selection, frame = false) =>
        set((s) => ({ selection, fitRequest: frame ? s.fitRequest + 1 : s.fitRequest })),
    hover: (hovered) => set({ hovered }),
    hoverFeature: (hoveredFeature) => set({ hoveredFeature }),
    setShowContacts: (showContacts) => set({ showContacts }),
    toggleHidden: (ids) =>
        set((s) => {
            const hidden = new Set(s.hidden);
            const allHidden = ids.every((i) => hidden.has(i));
            for (const i of ids) {
                if (allHidden) hidden.delete(i);
                else hidden.add(i);
            }
            return { hidden };
        }),
    showAll: () => set({ hidden: new Set(), isolated: null }),
    isolate: (isolated) => set((s) => ({ isolated, fitRequest: s.fitRequest + 1 })),
    requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),
    reset: () => set({ selection: null, hovered: null, hoveredFeature: null, hidden: new Set(), isolated: null }),
}));
