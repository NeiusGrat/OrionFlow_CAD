/**
 * useManifoldPreview Hook
 * 
 * React hook for client-side WASM preview rendering.
 * Provides instant "fast-draft" geometry while server generates high-fidelity files.
 */

import { useState, useEffect, useRef } from 'react';
import * as THREE from 'three';

interface PreviewState {
    mesh: THREE.BufferGeometry | null;
    isLoading: boolean;
    error: string | null;
}

interface FeatureGraph {
    sketches?: any[];
    features?: any[];
    parameters?: Record<string, any>;
}

export function useManifoldPreview(featureGraph: FeatureGraph | null | undefined): PreviewState {
    const [state, setState] = useState<PreviewState>({
        mesh: null,
        isLoading: false,
        error: null,
    });

    const workerRef = useRef<Worker | null>(null);
    const requestIdRef = useRef<number>(0);

    // Initialize worker
    useEffect(() => {
        try {
            workerRef.current = new Worker(
                new URL('../workers/manifoldWorker.ts', import.meta.url),
                { type: 'module' }
            );

            workerRef.current.onmessage = (e: MessageEvent) => {
                const { type, id, payload, error } = e.data;

                // Ignore stale responses
                if (id !== requestIdRef.current) return;

                if (type === 'RESULT' && payload) {
                    // Convert to Three.js BufferGeometry
                    const geometry = new THREE.BufferGeometry();

                    // Manifold returns interleaved vertex properties (position, normal)
                    // Each vertex has 6 floats: x, y, z, nx, ny, nz
                    const vertexCount = payload.vertices.length / 6;
                    const positions = new Float32Array(vertexCount * 3);
                    const normals = new Float32Array(vertexCount * 3);

                    for (let i = 0; i < vertexCount; i++) {
                        positions[i * 3] = payload.vertices[i * 6];
                        positions[i * 3 + 1] = payload.vertices[i * 6 + 1];
                        positions[i * 3 + 2] = payload.vertices[i * 6 + 2];
                        normals[i * 3] = payload.vertices[i * 6 + 3];
                        normals[i * 3 + 1] = payload.vertices[i * 6 + 4];
                        normals[i * 3 + 2] = payload.vertices[i * 6 + 5];
                    }

                    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
                    geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
                    geometry.setIndex(new THREE.BufferAttribute(payload.indices, 1));

                    setState({ mesh: geometry, isLoading: false, error: null });
                } else if (type === 'ERROR') {
                    setState({ mesh: null, isLoading: false, error: error || 'Unknown error' });
                }
            };

            workerRef.current.onerror = (e) => {
                console.error('[useManifoldPreview] Worker error:', e);
                setState((s) => ({ ...s, isLoading: false, error: 'Worker error' }));
            };
        } catch (err) {
            console.warn('[useManifoldPreview] Could not create worker:', err);
        }

        return () => {
            workerRef.current?.terminate();
            workerRef.current = null;
        };
    }, []);

    // Compile feature graph when it changes
    useEffect(() => {
        if (!featureGraph || !workerRef.current) {
            setState((s) => ({ ...s, mesh: null }));
            return;
        }

        // Skip if no features
        if (!featureGraph.features?.length && !featureGraph.sketches?.length) {
            return;
        }

        const id = ++requestIdRef.current;
        setState((s) => ({ ...s, isLoading: true, error: null }));

        workerRef.current.postMessage({
            type: 'COMPILE',
            id,
            payload: featureGraph,
        });
    }, [featureGraph]);

    return state;
}

export default useManifoldPreview;
