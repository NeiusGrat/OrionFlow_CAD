import * as THREE from "three";
import { create } from "zustand";

export type ChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: number;
    // If assistant generated a part
    partVersion?: number;
    files?: {
        glb: string;
        step: string;
    };
    image?: string; // For user uploads
};

export type DesignState = {
    id: string;
    prompt: string;
    parameters: Record<string, number>;
    featureGraph?: any;
    material: {
        roughness: number;
        metalness: number;
    };
    files: {
        glb: string;
        step: string;
    };
    history: ChatMessage[];
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
    addMessage: (id: string, message: ChatMessage) => void;
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

    addMessage: (id, message) =>
        set((state) => {
            const creations = state.creations.map((c) => {
                if (c.id === id) {
                    return { ...c, history: [...(c.history || []), message] };
                }
                return c;
            });
            // Update current if it's the one being modified
            const current = state.current?.id === id
                ? { ...state.current, history: [...(state.current.history || []), message] }
                : state.current;

            return { creations, current };
        }),

}));
