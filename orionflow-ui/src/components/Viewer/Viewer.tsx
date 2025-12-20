import ViewCube from "./ViewCube";



import { Canvas, useThree } from "@react-three/fiber";


import { OrbitControls, useGLTF } from "@react-three/drei";
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
            <Canvas camera={{ position: [2, 2, 2], fov: 50 }}>
                <ambientLight intensity={0.6} />
                <directionalLight position={[5, 5, 5]} intensity={0.8} />

                <CameraController />
                {url && <Model url={url} />}
                <OrbitControls enableDamping />
            </Canvas>

            <ViewCube />
        </div>
    );

}
