import React, { useEffect, useState } from "react";
import ViewCube from "./ViewCube";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import { useDesignStore } from "../../store/designStore";
import * as THREE from "three";

import { Box } from "lucide-react";

/**
 * Aggressively removes any GridHelper found in the scene
 */
function GridRemover() {
    const { scene } = useThree();
    useFrame(() => {
        scene.traverse((child) => {
            if ((child as any).isGridHelper || child.type === "GridHelper") {
                child.visible = false;
                scene.remove(child);
            }
        });
    });
    return null;
}



function frameModel(camera: THREE.Camera, controls: any, model: THREE.Object3D) {
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    const maxDim = Math.max(size.x, size.y, size.z);

    // cast camera only if perspective
    if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
        const perspectiveCam = camera as THREE.PerspectiveCamera;
        const fov = perspectiveCam.fov * (Math.PI / 180);
        let cameraZ = Math.abs(maxDim / (2 * Math.tan(fov / 2)));

        // Zoom factor - increased for better visibility of small models
        // 2.5x gives a good balance between model visibility and context
        cameraZ *= 2.5;

        // Ensure minimum distance for very small models
        const minDistance = 50;
        cameraZ = Math.max(cameraZ, minDistance);

        perspectiveCam.position.set(
            center.x + cameraZ * 0.7,
            center.y + cameraZ * 0.7,
            center.z + cameraZ * 0.7
        );
    } else {
        // Fallback for Ortho if we ever swap
        camera.position.set(
            center.x + maxDim * 3,
            center.y + maxDim * 3,
            center.z + maxDim * 3
        );
    }

    camera.lookAt(center);

    if (controls) {
        controls.target.copy(center);
        controls.update();
    }
}

function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    const { camera, controls } = useThree();

    // Auto-fit on load using Professional logic
    useEffect(() => {
        if (!scene) return;
        frameModel(camera, controls, scene);
    }, [scene, url, camera, controls]);

    // Apply SolidWorks-ish Material + Edges
    scene.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            // Matte Grey Material
            mesh.material = new THREE.MeshStandardMaterial({
                color: "#E0E0E0", // Light Grey
                roughness: 0.5,
                metalness: 0.1,
                flatShading: false,
                polygonOffset: true,
                polygonOffsetFactor: 1, // Push back slightly so lines show
                polygonOffsetUnits: 1
            });
        }
    });

    return (
        <group>
            <primitive object={scene} />
            <SceneEdges scene={scene} />
        </group>
    );
}

function SceneEdges({ scene }: { scene: THREE.Group }) {
    const [edges, setEdges] = useState<React.ReactElement[]>([]);

    useEffect(() => {
        const newEdges: React.ReactElement[] = [];
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                newEdges.push(
                    <lineSegments key={mesh.uuid}>
                        <edgesGeometry args={[mesh.geometry, 30]} />
                        <lineBasicMaterial color="#000000" />
                    </lineSegments>
                );
            }
        });
        setEdges(newEdges);
    }, [scene]);

    return <>{edges}</>;
}


function ViewManager() {
    const viewAction = useDesignStore((state) => state.viewAction);
    const { camera, scene, controls } = useThree();

    useEffect(() => {
        if (!viewAction) return;

        const box = new THREE.Box3().setFromObject(scene);
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x || 10, size.y || 10, size.z || 10);
        const dist = maxDim * 2.0;

        if (viewAction.type === 'reset') {
            camera.position.set(dist, dist, dist);
            camera.lookAt(0, 0, 0);
        } else if (viewAction.type === 'ortho') {
            camera.position.set(0, dist, 0);
            camera.lookAt(0, 0, 0);
        } else if (viewAction.type === 'iso') {
            camera.position.set(dist, dist, dist);
            camera.lookAt(0, 0, 0);
        }

        if (controls) {
            // @ts-ignore
            controls.target.set(0, 0, 0);
            // @ts-ignore
            controls.update();
        }

    }, [viewAction, camera, scene, controls]);

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
                    background: "rgba(255, 255, 255, 0.9)",
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
                    <Box size={48} color="#F97316" style={{ animation: "spin 2s linear infinite" }} />
                    <p style={{ marginTop: "20px", fontSize: "16px", fontWeight: 600 }}>Generating geometry...</p>
                </div>
            )}


            <Canvas camera={{ position: [20, 20, 20], fov: 45 }} style={{ background: "#f9fafb" }}> {/* Very light grey bg */}
                {/* Stronger lighting for CAD look */}
                <ambientLight intensity={1.0} />
                <directionalLight position={[10, 20, 10]} intensity={1.5} castShadow />
                <directionalLight position={[-10, -10, -5]} intensity={0.5} />
                <directionalLight position={[0, 0, 10]} intensity={0.5} />

                <GridRemover />

                {url && <Model url={url} />}

                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.1}
                    minDistance={1}
                    maxDistance={2000}
                />

                <ViewManager />

                <ViewCube />
            </Canvas>
        </div>
    );
}
