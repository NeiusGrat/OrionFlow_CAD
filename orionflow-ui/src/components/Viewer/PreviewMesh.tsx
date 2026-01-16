/**
 * PreviewMesh Component
 * 
 * Renders the fast-draft WASM-generated mesh with a distinct "draft" material.
 * Shows wireframe overlay to indicate it's a preview.
 */

import { useRef } from 'react';
import * as THREE from 'three';

interface PreviewMeshProps {
    geometry: THREE.BufferGeometry;
}

export default function PreviewMesh({ geometry }: PreviewMeshProps) {
    const meshRef = useRef<THREE.Mesh>(null);

    return (
        <group>
            {/* Solid preview */}
            <mesh ref={meshRef} geometry={geometry}>
                <meshStandardMaterial
                    color="#B8C4CE"
                    roughness={0.6}
                    metalness={0.1}
                    transparent
                    opacity={0.9}
                />
            </mesh>

            {/* Wireframe overlay to indicate "draft" mode */}
            <mesh geometry={geometry}>
                <meshBasicMaterial
                    color="#6B7280"
                    wireframe
                    transparent
                    opacity={0.3}
                />
            </mesh>
        </group>
    );
}
