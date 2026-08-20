/**
 * Renders GLB models to PNG data-URLs using a single shared offscreen WebGL
 * context. Browsers cap live WebGL contexts (~8-16), so a grid of 20 model
 * previews must not mount 20 canvases — we render sequentially instead.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
    CAD_Z_UP_TO_Y_UP,
    addCadLights,
    applyCadToneMapping,
    attachCadEdges,
    createEdgeMaterial,
    createPartMaterial,
    createStudioEnvironment,
} from "./cadAppearance";

const THUMB_W = 320;
const THUMB_H = 240;

const cache = new Map<string, string>();
let renderer: THREE.WebGLRenderer | null = null;
let envMap: THREE.Texture | null = null;
let queue: Promise<void> = Promise.resolve();

function getRenderer(): THREE.WebGLRenderer {
    if (!renderer) {
        renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            preserveDrawingBuffer: true,
        });
        renderer.setSize(THUMB_W, THUMB_H);
        renderer.setPixelRatio(1);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        // Same filmic response the viewer uses. Without it a thumbnail's metal
        // highlights clip to white and the part reads as plastic — the single
        // biggest reason thumbnails used to look unlike the viewport.
        applyCadToneMapping(renderer);
        // Metal needs an environment to read; RoomEnvironment is built-in/offline.
        envMap = createStudioEnvironment(renderer).texture;
    }
    return renderer;
}

const loader = new GLTFLoader();

const PART_MATERIAL = createPartMaterial();
const EDGE_MATERIAL = createEdgeMaterial();

async function renderOne(url: string): Promise<string> {
    const gltf = await loader.loadAsync(url);
    const model = gltf.scene;

    getRenderer(); // ensure envMap and tone mapping exist

    model.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.material = PART_MATERIAL;
        // Edges are what make a thumbnail read as a machined part rather than
        // a smooth blob: a fillet and a sharp corner are indistinguishable
        // under shading alone at 320x240.
        attachCadEdges(mesh, EDGE_MATERIAL);
    });

    // Orient exactly as the viewport does, before the bounding box is taken —
    // the camera is framed from that box, so rotating afterwards would frame
    // the part in a pose it is not rendered in.
    model.rotation.set(...CAD_Z_UP_TO_Y_UP);

    const scene = new THREE.Scene();
    scene.environment = envMap;
    addCadLights(scene);
    scene.add(model);

    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const radius = Math.max(sphere.radius, 0.001);

    const camera = new THREE.PerspectiveCamera(35, THUMB_W / THUMB_H, radius / 100, radius * 20);
    const dir = new THREE.Vector3(1, 0.85, 1).normalize();
    const dist = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.25;
    camera.position.copy(center).add(dir.multiplyScalar(dist));
    camera.lookAt(center);

    const r = getRenderer();
    r.render(scene, camera);
    const dataUrl = r.domElement.toDataURL("image/png");

    // free GPU memory for this model
    model.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (mesh.isMesh) mesh.geometry?.dispose();
        const line = child as THREE.LineSegments;
        if (line.isLineSegments) line.geometry?.dispose();
    });

    return dataUrl;
}

/** Get (or lazily render) a thumbnail for a GLB url. Serialized internally. */
export function getThumbnail(url: string): Promise<string> {
    const hit = cache.get(url);
    if (hit) return Promise.resolve(hit);

    const task = queue.then(async () => {
        if (cache.has(url)) return;
        try {
            cache.set(url, await renderOne(url));
        } catch (e) {
            console.warn(`thumbnail render failed for ${url}`, e);
        }
    });
    queue = task;
    return task.then(() => cache.get(url) || "");
}
