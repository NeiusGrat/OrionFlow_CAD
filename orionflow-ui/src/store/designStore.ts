import * as THREE from "three";
import { create } from "zustand";

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

}));
