/**
 * Renders GLB models to PNG data-URLs using a single shared offscreen WebGL
 * context. Browsers cap live WebGL contexts (~8-16), so a grid of 20 model
 * previews must not mount 20 canvases — we render sequentially instead.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

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
        // Metal needs an environment to read; RoomEnvironment is built-in/offline.
        const pmrem = new THREE.PMREMGenerator(renderer);
        envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    }
    return renderer;
}

const loader = new GLTFLoader();

const PART_MATERIAL = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#b9bec6"),
    metalness: 0.85,
    roughness: 0.34,
});

async function renderOne(url: string): Promise<string> {
    const gltf = await loader.loadAsync(url);
    const model = gltf.scene;

    model.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
            (child as THREE.Mesh).material = PART_MATERIAL;
        }
    });

    const scene = new THREE.Scene();
    getRenderer(); // ensure envMap exists
    scene.environment = envMap;
    scene.add(new THREE.HemisphereLight(0xf1f5f9, 0x334155, 1.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(4, 6, 5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x93c5fd, 0.5);
    fill.position.set(-5, -2, -4);
    scene.add(fill);
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
