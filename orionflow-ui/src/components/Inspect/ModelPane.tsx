/**
 * The part in graphite: every face light grey, the faces a characteristic was
 * matched to in solid black. The GLB has one node per face group (h1 = first
 * hole, p3 = third plane group...), named by the server's measurement, so the
 * highlight is exactly the geometry the CAD value came from.
 */
import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Bounds, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import { CAD_Z_UP_TO_Y_UP } from "../../lib/cadAppearance";

function Model({ url, highlight }: { url: string; highlight: string[] }) {
    const { scene } = useGLTF(url);
    const bounds = useBounds();
    const group = useRef<THREE.Group>(null);
    const meshes = useMemo(() => {
        const out: { name: string; mesh: THREE.Mesh }[] = [];
        scene.traverse((o) => {
            const m = o as THREE.Mesh;
            if (!m.isMesh) return;
            if (!m.geometry.attributes.normal) m.geometry = toCreasedNormals(m.geometry, Math.PI / 6);
            m.material = new THREE.MeshStandardMaterial({ color: "#d9d9d9", roughness: 0.85, metalness: 0, side: THREE.DoubleSide,
                polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
            if (!m.userData.__edges) {
                const lines = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 28),
                    new THREE.LineBasicMaterial({ color: "#000000" }));
                lines.raycast = () => undefined;
                m.add(lines);
                m.userData.__edges = true;
            }
            out.push({ name: m.name, mesh: m });
        });
        return out;
    }, [scene]);

    useEffect(() => {
        const keys = new Set(highlight.map((h) => THREE.PropertyBinding.sanitizeNodeName(h)));
        for (const { name, mesh } of meshes) {
            const mat = mesh.material as THREE.MeshStandardMaterial;
            const hit = keys.has(name);
            mat.color.set(hit ? "#5c5c5c" : keys.size ? "#efefef" : "#d9d9d9");
            mat.needsUpdate = true;
            // edges go white on a highlighted body, so its form still reads in dark grey
            for (const child of mesh.children) {
                const line = child as THREE.LineSegments;
                if (line.isLineSegments) (line.material as THREE.LineBasicMaterial).color.set(hit ? "#ffffff" : "#000000");
            }
        }
    }, [meshes, highlight]);

    useEffect(() => {
        if (group.current) bounds.refresh(group.current).clip().fit();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scene]);

    return (
        <group ref={group} rotation={CAD_Z_UP_TO_Y_UP}>
            <primitive object={scene} />
        </group>
    );
}

function White() {
    const { gl } = useThree();
    useEffect(() => { gl.setClearColor("#ffffff"); }, [gl]);
    return null;
}

export default function ModelPane({ url, highlight }: { url: string; highlight: string[] }) {
    return (
        <Canvas dpr={[1, 2]} camera={{ position: [0.3, 0.25, 0.3], fov: 32, near: 0.0005, far: 50 }} gl={{ antialias: true }}>
            <White />
            <ambientLight intensity={0.75} />
            <directionalLight position={[3, 6, 4]} intensity={1.1} />
            <directionalLight position={[-4, 2, -3]} intensity={0.35} />
            <Suspense fallback={null}>
                <Bounds margin={1.25}>
                    <Model url={url} highlight={highlight} />
                </Bounds>
            </Suspense>
            <OrbitControls makeDefault enableDamping />
        </Canvas>
    );
}
