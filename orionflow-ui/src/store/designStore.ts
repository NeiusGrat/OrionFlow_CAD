import * as THREE from "three";


import { create } from "zustand";


export type DesignState = {
    id: string;
    prompt: string;
    parameters: Record<string, number>;
    material: {
        roughness: number;
        metalness: number;
    };
    files: {
        glb: string;
        step: string;
    };
};

type AppStore = {
    camera?: THREE.PerspectiveCamera;

    creations: DesignState[];
    current: DesignState | null;

    addCreation: (design: DesignState) => void;
    setCurrent: (id: string) => void;
};

export const useDesignStore = create<AppStore>((set) => ({
    creations: [],
    current: null,

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
