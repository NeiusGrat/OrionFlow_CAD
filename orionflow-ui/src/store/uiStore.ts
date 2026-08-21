import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Theme = 'dark' | 'light';

/** Which manual operation the workbench is collecting parameters for. */
export interface ToolRequest {
    /** Blueprint feature type — "Fillet", "Pocket", … */
    kind: string;
    label: string;
}

interface UIState {
    theme: Theme;
    setTheme: (t: Theme) => void;
    toggleTheme: () => void;

    /** Left dock sections, open independently like a CAD combo view. */
    openSections: Record<string, boolean>;
    toggleSection: (id: string) => void;

    ribbonOpen: boolean;
    toggleRibbon: () => void;

    /** The left model panel. Collapsing it is how the part gets the screen. */
    dockOpen: boolean;
    toggleDock: () => void;

    /** Null when no tool dialog is up. */
    tool: ToolRequest | null;
    openTool: (t: ToolRequest) => void;
    closeTool: () => void;

    /** The first-run tour. Persisted, so it is shown once and never nags. */
    tourStep: number | null;
    startTour: () => void;
    /** `total` is passed in rather than hard-coded here: the tour's length is a
     *  property of the tour, and the two drifted apart once already — the store
     *  still thought there were four cards after one was removed, which left a
     *  final step that rendered nothing. */
    nextTour: (total: number) => void;
    endTour: () => void;
    tourSeen: boolean;
}

/** The theme has to be on the document element, not in React state alone:
 *  the CSS custom properties hang off `:root[data-theme]`, and the viewport's
 *  background gradient is painted from them. */
function applyTheme(theme: Theme) {
    document.documentElement.setAttribute('data-theme', theme);
}

export const useUIStore = create<UIState>()(
    persist(
        (set, get) => ({
            theme: 'dark',
            setTheme: (theme) => {
                applyTheme(theme);
                set({ theme });
            },
            toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),

            openSections: { tree: true, parameters: true, inspector: true, projects: false },
            toggleSection: (id) =>
                set((s) => ({ openSections: { ...s.openSections, [id]: !s.openSections[id] } })),

            ribbonOpen: true,
            toggleRibbon: () => set((s) => ({ ribbonOpen: !s.ribbonOpen })),

            dockOpen: true,
            toggleDock: () => set((s) => ({ dockOpen: !s.dockOpen })),

            tool: null,
            openTool: (tool) => set({ tool }),
            closeTool: () => set({ tool: null }),

            tourStep: null,
            tourSeen: false,
            startTour: () => set({ tourStep: 0 }),
            nextTour: (total) =>
                set((s) => {
                    const next = (s.tourStep ?? 0) + 1;
                    return next >= total
                        ? { tourStep: null, tourSeen: true }
                        : { tourStep: next };
                }),
            endTour: () => set({ tourStep: null, tourSeen: true }),
        }),
        {
            name: 'orionflow-ui',
            // The tool dialog and the live tour step are per-session; only
            // preferences survive a reload.
            partialize: (s) => ({
                theme: s.theme,
                openSections: s.openSections,
                ribbonOpen: s.ribbonOpen,
                dockOpen: s.dockOpen,
                tourSeen: s.tourSeen,
            }),
            onRehydrateStorage: () => (state) => {
                applyTheme(state?.theme ?? 'dark');
            },
        },
    ),
);

// Paint the stored theme before first render so the app never flashes the
// wrong one on the way in.
applyTheme(
    (() => {
        try {
            return JSON.parse(localStorage.getItem('orionflow-ui') || '{}')?.state?.theme ?? 'dark';
        } catch {
            return 'dark';
        }
    })() as Theme,
);
