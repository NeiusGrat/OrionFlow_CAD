import React, { useEffect, useRef } from "react";
import ViewCube from "./ViewCube";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import { useDesignStore } from "../../store/designStore";
import * as THREE from "three";

import { Box as BoxIcon } from "lucide-react";

// frameModel function removed - logic moved to Model component

/**
 * Model component - loads GLB and applies professional CAD styling
 */
function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    const { camera, controls } = useThree();
    const hasFramed = useRef(false);

    // Auto-fit camera to model
    useEffect(() => {
        if (!scene || hasFramed.current) return;

        // Delay slightly to ensure Three.js has updated the world matrices
        const timer = setTimeout(() => {
            // 1. Calculate bounds based only on actual meshes
            const box = new THREE.Box3();
            let hasMesh = false;
            scene.traverse((child) => {
                if ((child as THREE.Mesh).isMesh && (child as THREE.Mesh).geometry) {
                    box.expandByObject(child);
                    hasMesh = true;
                }
            });

            if (!hasMesh || box.isEmpty()) return;

            const center = box.getCenter(new THREE.Vector3());
            const sphere = box.getBoundingSphere(new THREE.Sphere());
            const radius = sphere.radius;

            if (radius <= 0) return;

            if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
                const pCam = camera as THREE.PerspectiveCamera;
                const fov = pCam.fov * (Math.PI / 180);

                // Distance calculation: model should fill ~70% of viewport
                // Formula: distance = radius / tan(fov / 2)
                // Adding 1.5x margin for professional look
                const fitDistance = radius / Math.tan(fov / 2);
                const distance = fitDistance * 1.5;

                // Isometric direction vector (normalized)
                const dir = new THREE.Vector3(1, 1, 1).normalize();

                const finalPos = new THREE.Vector3().copy(center).add(dir.multiplyScalar(distance));
                camera.position.copy(finalPos);

                console.log(`Camera: radius=${radius.toFixed(1)}mm, distance=${distance.toFixed(1)}`);
            }

            camera.lookAt(center);

            // Update orbit controls target
            if (controls) {
                (controls as any).target.copy(center);
                (controls as any).update();
            }

            hasFramed.current = true;
        }, 50);

        return () => clearTimeout(timer);
    }, [scene, url, camera, controls]);

    // Reset framing flag when URL changes
    useEffect(() => {
        hasFramed.current = false;
    }, [url]);

    // Apply professional CAD material
    useEffect(() => {
        if (!scene) return;
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                mesh.material = new THREE.MeshStandardMaterial({
                    color: "#D1D5DB", // Professional cool grey
                    roughness: 0.4,
                    metalness: 0.2,
                    flatShading: false,
                });
            }
        });
    }, [scene]);

    return <primitive object={scene} />;
}


/**
 * View manager for orthographic/isometric view switching
 */
function ViewManager() {
    const viewAction = useDesignStore((state) => state.viewAction);
    const { camera, scene, controls } = useThree();

    useEffect(() => {
        if (!viewAction || !scene) return;

        // Calculate current model bounds
        const box = new THREE.Box3();
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) box.expandByObject(child);
        });

        if (box.isEmpty()) return;

        const center = box.getCenter(new THREE.Vector3());
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        const radius = sphere.radius;

        const fov = ((camera as THREE.PerspectiveCamera).fov || 50) * (Math.PI / 180);
        const dist = (radius / Math.tan(fov / 2)) * 1.5;

        if (viewAction.type === 'reset' || viewAction.type === 'iso') {
            const dir = new THREE.Vector3(1, 1, 1).normalize();
            camera.position.copy(center).add(dir.multiplyScalar(dist));
        } else if (viewAction.type === 'ortho') {
            // Plan view from +Y
            camera.position.set(center.x, center.y + dist, center.z);
        }

        camera.lookAt(center);

        if (controls) {
            (controls as any).target.copy(center);
            (controls as any).update();
        }

    }, [viewAction, camera, scene, controls]);

    return null;
}

/**
 * Ensures model is always visible if it somehow gets lost
 */
function ZoomGuard() {
    const { camera, scene, controls } = useThree();

    useFrame(() => {
        // Only guard if we have meshes
        let hasMesh = false;
        scene.traverse(c => { if ((c as any).isMesh) hasMesh = true; });
        if (!hasMesh) return;

        const cameraDist = camera.position.length();
        // If camera is ridiculously far (e.g. > 10000), reset it
        if (cameraDist > 5000) {
            const box = new THREE.Box3().setFromObject(scene);
            const center = box.getCenter(new THREE.Vector3());
            const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
            const dist = (radius / Math.sin((camera as any).fov * Math.PI / 360)) * 1.5;

            camera.position.set(center.x + dist, center.y + dist, center.z + dist);
            camera.lookAt(center);
            if (controls) {
                (controls as any).target.copy(center);
                (controls as any).update();
            }
        }
    });

    return null;
}

export default function Viewer({ url }: { url: string }) {
    const isGenerating = useDesignStore((state) => state.isGenerating);

    return (
        <div style={{ height: "100%", width: "100%", position: "relative" }}>
            {/* LOADING OVERLAY */}
            {isGenerating && (
                <div style={{
                    position: "absolute", zIndex: 100, inset: 0,
                    background: "rgba(255, 255, 255, 0.95)",
                    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                    color: "#333"
                }}>
                    <style>
                        {`
                        @keyframes spin { 
                            from { transform: rotate(0deg); } 
                            to { transform: rotate(360deg); } 
                        }
                        `}
                    </style>
                    <BoxIcon size={48} color="#F97316" style={{ animation: "spin 2s linear infinite" }} />
                    <p style={{ marginTop: "20px", fontSize: "16px", fontWeight: 600 }}>Generating geometry...</p>
                </div>
            )}


            <Canvas
                camera={{ position: [50, 50, 50], fov: 45, near: 0.1, far: 10000 }}
                style={{ background: "#f3f4f6" }}
            >
                {/* Clean studio lighting for CAD */}
                <ambientLight intensity={0.7} />
                <directionalLight position={[10, 20, 10]} intensity={1.0} />
                <directionalLight position={[-10, 10, -5]} intensity={0.5} />
                <spotLight position={[0, 40, 0]} intensity={0.5} />

                {url && <Model url={url} />}

                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.1}
                    minDistance={0.1}
                    maxDistance={2000}
                />

                <ViewManager />
                <ZoomGuard />
                <ViewCube />
            </Canvas>
        </div>
    );
}
