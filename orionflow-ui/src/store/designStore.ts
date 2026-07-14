import * as THREE from "three";
import { create } from "zustand";

// Chat message type for conversation history
export interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: number;
    partVersion?: number;
    files?: {
        glb: string;
        step: string;
    };
}

export type PartVersion = {
    label: string;
    timestamp: number;
    files: { glb: string; step: string; stl: string };
    oflCode: string;
    parameters: Record<string, number>;
};

export type DesignState = {
    id: string;
    prompt: string;
    versions?: PartVersion[];
    activeVersion?: number;
    parameters: Record<string, number>;
    featureGraph?: any;
    history?: ChatMessage[];  // Conversation history
    material: {
        roughness: number;
        metalness: number;
    };
    files: {
        glb: string;
        step: string;
        stl: string;
    };
    source?: "v1" | "v2";  // Track generation source (V1 or V2)
};

export type ViewAction = {
    type: 'ortho' | 'iso' | 'reset';
    timestamp: number;
};

type AppStore = {
    camera?: THREE.PerspectiveCamera;

    creations: DesignState[];
    current: DesignState | null;

    isGenerating: boolean;
    setIsGenerating: (val: boolean) => void;

    viewAction?: ViewAction;
    triggerViewAction: (type: 'ortho' | 'iso' | 'reset') => void;

    addCreation: (design: DesignState) => void;
    setCurrent: (id: string) => void;
    addVersion: (id: string, v: PartVersion) => void;
    activateVersion: (id: string, index: number) => void;
};

export const useDesignStore = create<AppStore>((set) => ({
    creations: [],
    current: null,

    isGenerating: false,
    setIsGenerating: (val) => set({ isGenerating: val }),

    triggerViewAction: (type) => set({ viewAction: { type, timestamp: Date.now() } }),

    addCreation: (design) =>
        set((state) => ({
            creations: [...state.creations, design],
            current: design,
        })),

    setCurrent: (id) =>
        set((state) => ({
            current: state.creations.find((c) => c.id === id) || null,
        })),

    addVersion: (id, v) =>
        set((state) => {
            const update = (c: DesignState) =>
                c.id === id
                    ? { ...c, versions: [...(c.versions || []), v], activeVersion: (c.versions?.length || 0) }
                    : c;
            const creations = state.creations.map(update);
            return {
                creations,
                current: state.current?.id === id ? creations.find((c) => c.id === id) || null : state.current,
            };
        }),

    activateVersion: (id, index) =>
        set((state) => {
            const update = (c: DesignState) => {
                if (c.id !== id || !c.versions?.[index]) return c;
                const v = c.versions[index];
                return { ...c, activeVersion: index, files: { ...v.files }, parameters: { ...v.parameters } };
            };
            const creations = state.creations.map(update);
            const current = state.current?.id === id ? creations.find((c) => c.id === id) || null : state.current;
            // keep the code panel in sync with the activated version
            const v = current?.versions?.[index];
            if (v) {
                import('./oflStore').then(({ useOFLStore }) =>
                    useOFLStore.setState({
                        oflCode: v.oflCode,
                        glbUrl: v.files.glb, stepUrl: v.files.step, stlUrl: v.files.stl,
                    })
                );
            }
            return { creations, current };
        }),

}));
