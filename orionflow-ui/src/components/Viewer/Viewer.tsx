import ViewCube from "./ViewCube";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import { useDesignStore } from "../../store/designStore";
import * as THREE from "three";
import { useEffect } from "react";
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

function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    const current = useDesignStore((state) => state.current);
    const { camera, controls } = useThree();

    // Auto-fit on load with slight delay to ensure geometry is ready
    useEffect(() => {
        if (!scene) return;

        const fit = () => {
            const box = new THREE.Box3().setFromObject(scene);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());

            // Check if bounds are valid (not empty)
            if (size.lengthSq() === 0) return;

            // Center geometry
            scene.position.sub(center);

            // Fit camera
            // Use a slightly larger multiplier for better margins
            const maxDim = Math.max(size.x, size.y, size.z) || 10;
            const dist = maxDim * 2.0;

            // Position fitting isometric-ish
            camera.position.set(dist, dist, dist);
            camera.lookAt(0, 0, 0);

            if (controls) {
                // @ts-ignore
                controls.target.set(0, 0, 0);
                // @ts-ignore
                controls.update();
                // @ts-ignore
                controls.saveState(); // Save this as the "reset" state
            }
        };

        // Run immediately and after a short tick
        fit();
        const t = setTimeout(fit, 50);
        return () => clearTimeout(t);

    }, [scene, url, camera, controls]);

    scene.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.material = new THREE.MeshStandardMaterial({
                roughness: current?.material.roughness ?? 0.4,
                metalness: current?.material.metalness ?? 0.6,
                color: "#00A6FF"
            });
        }
    });

    return <primitive object={scene} />;
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
                    background: "rgba(240, 240, 240, 0.8)",
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
                    <Box size={48} color="#00A6FF" style={{ animation: "spin 2s linear infinite" }} />
                    <p style={{ marginTop: "20px", fontSize: "16px", fontWeight: 600 }}>Generating geometry...</p>
                </div>
            )}

            <Canvas camera={{ position: [20, 20, 20], fov: 45 }} style={{ background: "#f5f5f5" }}>
                <ambientLight intensity={0.8} />
                <directionalLight position={[10, 10, 5]} intensity={1} castShadow />
                <directionalLight position={[-10, -10, -5]} intensity={0.5} />

                {/* Guarantee NO GRID */}
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
