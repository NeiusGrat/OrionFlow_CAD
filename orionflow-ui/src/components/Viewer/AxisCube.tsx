import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { useRef } from "react";

function Cube() {
    const meshRef = useRef<THREE.Mesh>(null);
    const { camera } = useThree();

    // Rotate cube opposite to camera so it reflects orientation
    useFrame(() => {
        if (meshRef.current) {
            meshRef.current.quaternion.copy(camera.quaternion).invert();
        }
    });

    return (
        <mesh ref={meshRef}>
            <boxGeometry args={[1, 1, 1]} />
            <meshStandardMaterial color="#888" />
        </mesh>
    );
}

export default function AxisCube() {
    return (
        <div
            style={{
                position: "absolute",
                bottom: 16,
                right: 16,
                width: 80,
                height: 80,
                pointerEvents: "none",
            }}
        >
            <Canvas
                camera={{ position: [2, 2, 2], fov: 50 }}
                style={{ background: "#111" }}
            >
                <ambientLight intensity={0.6} />
                <directionalLight position={[3, 3, 3]} />
                <Cube />
            </Canvas>
        </div>
    );
}
