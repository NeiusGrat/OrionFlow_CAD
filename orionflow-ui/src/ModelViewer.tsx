import { Canvas } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";

function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    return <primitive object={scene} />;
}

export default function ModelViewer({ url }: { url: string }) {
    return (
        <div style={{ height: 400, marginTop: 20 }}>
            <Canvas camera={{ position: [2, 2, 2] }}>
                <ambientLight />
                <directionalLight position={[5, 5, 5]} />
                <Model url={url} />
                <OrbitControls />
            </Canvas>
        </div>
    );
}


