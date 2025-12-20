import ViewCube from "./ViewCube";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, useGLTF, Center } from "@react-three/drei";
import { useDesignStore } from "../../store/designStore";
import * as THREE from "three";
import { useEffect } from "react";

function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    const current = useDesignStore((state) => state.current);

    scene.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.material = new THREE.MeshStandardMaterial({
                roughness: current?.material.roughness ?? 0.4,
                metalness: current?.material.metalness ?? 0.6,
                color: "#00A6FF" // Default Adam blue
            });
        }
    });

    return <primitive object={scene} />;
}

/**
 * Exposes camera control to the global store
 */
function CameraController() {
    const { camera } = useThree();
    const setCamera = useDesignStore.setState;

    useEffect(() => {
        setCamera({ camera: camera as any });
    }, [camera]);

    return null;
}

export default function Viewer({ url }: { url: string }) {
    return (
        <div style={{ height: "100%", width: "100%", position: "relative" }}>
            <Canvas camera={{ position: [5, 5, 5], fov: 45 }} style={{ background: "#f5f5f5" }}>
                <ambientLight intensity={0.8} />
                <directionalLight position={[10, 10, 5]} intensity={1} castShadow />
                <directionalLight position={[-10, -10, -5]} intensity={0.5} />

                {/* Subtle Grid Helper for CAD feel */}
                <gridHelper args={[20, 20, 0xd4d4d8, 0xe4e4e7]} />

                <CameraController />
                <Center top>
                    {url && <Model url={url} />}
                </Center>

                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.1}
                    minDistance={2}
                    maxDistance={50}
                />

                <ViewCube />
            </Canvas>
        </div>
    );
}
