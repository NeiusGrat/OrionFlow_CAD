/**
 * The watchdog viewport: one colour per component, and an x-ray focus mode.
 *
 * The GLB is one node per assembly instance (interface_check) or per robot
 * link (robot worker). Every node gets its own anodised colour from
 * `componentTint`, assigned by sorted node name so a re-run colours the same
 * assembly the same way. When a finding is selected, the parts it names keep
 * their colour and glow in the finding's severity, and every other part drops
 * to a translucent ghost — the question "where is this?" is answered by what
 * is still solid.
 *
 * Both writers export Z-up millimetres-as-metres; three.js is Y-up, so the
 * model group is rotated by `CAD_Z_UP_TO_Y_UP`, the same as the studio.
 */
import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Bounds, ContactShadows, Grid, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { CAD_LIGHTS, CAD_Z_UP_TO_Y_UP, applyCadToneMapping, componentTint, createPartMaterial } from "../../lib/cadAppearance";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import { nodeKey } from "../../lib/watchdog";


export interface ModelFocus {
    /** Node names (unsanitized) to keep solid. Empty = no focus, everything solid. */
    nodes: string[];
    color: string;
    /** Finding location in the file's own units (mm), assembly frame. */
    marker?: number[] | null;
}

interface Props {
    url: string;
    focus?: ModelFocus | null;
    selected?: string | null;
    onPick?: (node: string | null) => void;
    /** Called once with the node names actually in the file. */
    onNodes?: (nodes: string[]) => void;
}

/** The GLB node a mesh stands for (sanitized name). */
function meshNode(o: THREE.Object3D, root: THREE.Object3D): string {
    if (o.name) return o.name;
    const p = o.parent;
    return p && p !== root && p.name && p.name !== "world" ? p.name : o.uuid;
}

function Environment() {
    const { gl, scene } = useThree();
    useEffect(() => {
        applyCadToneMapping(gl);
        const pm = new THREE.PMREMGenerator(gl);
        const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
        scene.environment = env;
        return () => {
            env.dispose();
            pm.dispose();
            scene.environment = null;
        };
    }, [gl, scene]);
    return null;
}

function Model({ url, focus, selected, onPick, onNodes }: Props) {
    const { scene } = useGLTF(url);
    const bounds = useBounds();
    const outer = useRef<THREE.Group>(null);
    const meshes = useMemo(() => {
        const list: { node: string; mesh: THREE.Mesh; tint: string }[] = [];
        scene.traverse((o) => {
            const m = o as THREE.Mesh;
            if (!m.isMesh) return;
            // GLTFLoader folds a single-mesh node into the Mesh, so the node's
            // name is on the mesh itself; trimesh's shared "world" root above
            // it must not be mistaken for the part.
            const node = meshNode(m, scene);
            list.push({ node, mesh: m, tint: "" });
        });
        const names = [...new Set(list.map((x) => x.node))].sort();
        for (const x of list) {
            x.tint = componentTint(names.indexOf(x.node));
            // Neither writer stores normals. Smooth normals averaged across a
            // box's 90 degree edges shade it like a pillow; crease at 30 degrees
            // so flats stay flat and bores stay round.
            if (!x.mesh.geometry.attributes.normal) x.mesh.geometry = toCreasedNormals(x.mesh.geometry, Math.PI / 6);
            x.mesh.material = createPartMaterial({ color: new THREE.Color(x.tint), side: THREE.DoubleSide });
            x.mesh.castShadow = true;
        }
        return list;
    }, [scene]);

    useEffect(() => {
        onNodes?.([...new Set(meshes.map((m) => m.node))].sort());
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [meshes]);

    // Stand the model on the grid, centred: assemblies arrive wherever their
    // CAD origin was, often half below the floor.
    useEffect(() => {
        const g = outer.current;
        if (!g) return;
        g.position.set(0, 0, 0);
        g.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(g);
        const c = box.getCenter(new THREE.Vector3());
        g.position.set(-c.x, -box.min.y, -c.z);
        g.updateMatrixWorld(true);
        bounds.refresh(g).clip().fit();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scene]);

    useEffect(() => {
        const keys = new Set((focus?.nodes ?? []).map(nodeKey));
        const focusing = keys.size > 0;
        const glow = new THREE.Color(focus?.color ?? "#ffffff");
        for (const { node, mesh, tint } of meshes) {
            const mat = mesh.material as THREE.MeshStandardMaterial;
            const hit = keys.has(node);
            const sel = selected === node;
            mat.color.set(focusing && !hit ? "#8A9BB4" : tint);
            mat.transparent = focusing && !hit;
            mat.opacity = focusing && !hit ? 0.12 : 1;
            mat.depthWrite = !(focusing && !hit);
            mat.emissive.copy(hit ? glow : sel ? new THREE.Color("#ffffff") : new THREE.Color(0));
            mat.emissiveIntensity = hit ? 0.35 : sel ? 0.18 : 0;
            mat.needsUpdate = true;
        }
    }, [meshes, focus, selected]);

    const marker = focus?.marker && focus.marker.length === 3 ? focus.marker.map((v) => v / 1000) : null;
    const size = useMemo(() => new THREE.Box3().setFromObject(scene).getSize(new THREE.Vector3()).length(), [scene]);

    return (
        <group ref={outer}>
        <group rotation={CAD_Z_UP_TO_Y_UP}>
            <primitive
                object={scene}
                onClick={(e: { stopPropagation: () => void; object: THREE.Object3D }) => {
                    e.stopPropagation();
                    onPick?.(meshNode(e.object, scene));
                }}
                onPointerMissed={() => onPick?.(null)}
            />
            {marker && (
                <mesh position={marker as [number, number, number]}>
                    <sphereGeometry args={[Math.max(size * 0.012, 0.0015), 24, 16]} />
                    <meshBasicMaterial color={focus?.color ?? "#fff"} toneMapped={false} />
                </mesh>
            )}
        </group>
        </group>
    );
}

export default function ModelView(props: Props) {
    const lastUrl = useRef(props.url);
    useEffect(() => {
        const prev = lastUrl.current;
        lastUrl.current = props.url;
        return () => {
            if (prev && prev !== props.url) useGLTF.clear(prev);
        };
    }, [props.url]);

    return (
        <Canvas
            shadows
            dpr={[1, 2]}
            camera={{ position: [0.25, 0.2, 0.25], fov: 35, near: 0.0005, far: 50 }}
            gl={{ antialias: true, preserveDrawingBuffer: true }}
            onPointerMissed={() => props.onPick?.(null)}
        >
            <Environment />
            <ambientLight intensity={CAD_LIGHTS.ambient.intensity + 0.15} />
            <directionalLight position={[...CAD_LIGHTS.key.position]} intensity={CAD_LIGHTS.key.intensity} castShadow />
            <directionalLight position={[...CAD_LIGHTS.fill.position]} intensity={CAD_LIGHTS.fill.intensity} color="#9fc2ff" />
            <directionalLight position={[...CAD_LIGHTS.rim.position]} intensity={0.5} color="#ffd6a8" />
            <Suspense fallback={null}>
                <Bounds margin={1.3}>
                    <Model {...props} />
                </Bounds>
                <ContactShadows position={[0, -0.0005, 0]} opacity={0.45} scale={2} blur={2.4} far={0.6} />
            </Suspense>
            <Grid
                infiniteGrid
                cellSize={0.01}
                sectionSize={0.1}
                cellColor="#22385a"
                sectionColor="#2f5487"
                fadeDistance={3}
                position={[0, -0.001, 0]}
            />
            <OrbitControls makeDefault enableDamping />
        </Canvas>
    );
}
