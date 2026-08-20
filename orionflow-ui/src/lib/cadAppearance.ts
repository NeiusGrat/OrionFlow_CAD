/**
 * The one definition of what a part looks like in this application.
 *
 * There were two, and they disagreed. `Viewer.tsx` rendered the part as
 * machined aluminium (#c2c7cf, metalness 0.72, roughness 0.29) under a
 * three-point rig with ACES tone mapping and drawn edges; `thumbnailRenderer`
 * used a different grey (#b9bec6), a different metalness (0.85), a
 * hemisphere-plus-blue-fill rig, no tone mapping and no edges at all. The same
 * part therefore had two appearances depending on where you looked at it, and
 * the thumbnail — being untonemapped, unedged and more metallic — was the one
 * that read as a shiny 3D blob rather than an engineering part.
 *
 * Anything that renders a part imports from here. Adding a third renderer with
 * its own constants re-creates exactly the drift this module exists to remove.
 *
 * The values are the viewer's, because the viewer is the surface the look was
 * tuned on. Notes on the two that are counter-intuitive:
 *
 * - **Metalness 0.72, not ~0.9.** A fully metallic surface takes its entire
 *   colour from the environment, so against a plain studio map it reads as a
 *   grey mirror with no form. Staying slightly dielectric keeps the diffuse
 *   term that makes a machined face look machined.
 * - **ACES tone mapping is not optional.** Untonemapped metal highlights clip
 *   to flat white, which is precisely what makes a metallic part read as
 *   plastic. Without it the rest of the PBR set is wasted.
 */
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

/** Canonical machined-aluminium surface. */
export const CAD_SURFACE = {
    color: "#c2c7cf",
    metalness: 0.72,
    roughness: 0.29,
    envMapIntensity: 1.15,
} as const;

/** Edge lines. Subtle rather than black-and-hard: an engineering viewport
 *  shows the geometry, it does not outline it like a cartoon. */
export const CAD_EDGE = {
    color: "#191b1e",
    opacity: 0.55,
    /** Dihedral angle (deg) above which a shared edge is drawn. Low enough to
     *  catch chamfers, high enough not to draw every tessellation seam on a
     *  cylinder. */
    thresholdDeg: 28,
} as const;

/** Filmic response, applied to every renderer that shows a part. */
export const CAD_TONE_MAPPING = {
    toneMapping: THREE.ACESFilmicToneMapping,
    exposure: 1.05,
} as const;

/** Three-point rig laid over the environment map: a key that casts, a cool
 *  fill that keeps shadowed faces readable, and a rim that separates the
 *  silhouette from the background. */
export const CAD_LIGHTS = {
    key: { position: [8, 16, 10] as const, intensity: 1.5 },
    fill: { position: [-12, 7, -6] as const, intensity: 0.45, color: "#c9d6ea" },
    rim: { position: [0, -8, -12] as const, intensity: 0.25, color: "#dfe6f2" },
    ambient: { intensity: 0.12 },
} as const;

/** FreeCAD is Z-up; three.js is Y-up, and `stl_to_glb` writes an identity
 *  transform. A part therefore arrives with its height along three's Z and
 *  renders standing on edge — a plate looks like a wall. Rotating -90 degrees
 *  about X puts it on the ground plane, which is what every CAD package shows.
 *
 *  Shared because it is a property of *the file format*, not of one renderer:
 *  the viewport applied it and the thumbnail grid did not, so the same disc lay
 *  flat in the viewport and stood on edge in the library. */
export const CAD_Z_UP_TO_Y_UP: [number, number, number] = [-Math.PI / 2, 0, 0];

/** The part material. A factory, not a shared instance: the viewer mutates
 *  per-mesh material state (hover, selection) and a module-level singleton
 *  would leak one mesh's state into every other renderer. */
export function createPartMaterial(
    overrides: Partial<THREE.MeshStandardMaterialParameters> = {}
): THREE.MeshStandardMaterial {
    return new THREE.MeshStandardMaterial({
        color: new THREE.Color(CAD_SURFACE.color),
        metalness: CAD_SURFACE.metalness,
        roughness: CAD_SURFACE.roughness,
        envMapIntensity: CAD_SURFACE.envMapIntensity,
        ...overrides,
    });
}

export function createEdgeMaterial(
    overrides: Partial<THREE.LineBasicMaterialParameters> = {}
): THREE.LineBasicMaterial {
    return new THREE.LineBasicMaterial({
        color: new THREE.Color(CAD_EDGE.color),
        transparent: true,
        opacity: CAD_EDGE.opacity,
        ...overrides,
    });
}

/** Apply the filmic response to a renderer. */
export function applyCadToneMapping(gl: THREE.WebGLRenderer): void {
    gl.toneMapping = CAD_TONE_MAPPING.toneMapping;
    gl.toneMappingExposure = CAD_TONE_MAPPING.exposure;
}

/** Build the neutral studio environment. Deterministic and offline — three's
 *  built-in RoomEnvironment, no network fetch. Metal with no environment to
 *  reflect renders black, so this is required, not decorative.
 *
 *  Caller owns the returned texture and the generator's disposal. */
export function createStudioEnvironment(gl: THREE.WebGLRenderer): {
    texture: THREE.Texture;
    dispose: () => void;
} {
    const pmrem = new THREE.PMREMGenerator(gl);
    const texture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    return {
        texture,
        dispose: () => {
            texture.dispose();
            pmrem.dispose();
        },
    };
}

/** Add the standard rig to a scene built imperatively (the thumbnail path;
 *  the viewer declares the same rig as JSX from {@link CAD_LIGHTS}). */
export function addCadLights(scene: THREE.Scene): void {
    const key = new THREE.DirectionalLight(0xffffff, CAD_LIGHTS.key.intensity);
    key.position.set(...CAD_LIGHTS.key.position);
    scene.add(key);

    const fill = new THREE.DirectionalLight(
        new THREE.Color(CAD_LIGHTS.fill.color),
        CAD_LIGHTS.fill.intensity
    );
    fill.position.set(...CAD_LIGHTS.fill.position);
    scene.add(fill);

    const rim = new THREE.DirectionalLight(
        new THREE.Color(CAD_LIGHTS.rim.color),
        CAD_LIGHTS.rim.intensity
    );
    rim.position.set(...CAD_LIGHTS.rim.position);
    scene.add(rim);

    scene.add(new THREE.AmbientLight(0xffffff, CAD_LIGHTS.ambient.intensity));
}

/** Attach CAD edge lines to a mesh exactly once.
 *
 *  Edges never take pointer picks: they sit in front of the face they belong
 *  to, so a raycast would hit the line instead of the surface and face
 *  selection would become unusable. */
export function attachCadEdges(
    mesh: THREE.Mesh,
    material: THREE.LineBasicMaterial
): THREE.LineSegments | null {
    if (mesh.userData.__edgesAdded) return null;
    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(mesh.geometry, CAD_EDGE.thresholdDeg),
        material
    );
    edges.name = "__edges";
    edges.raycast = () => {};
    mesh.add(edges);
    mesh.userData.__edgesAdded = true;
    return edges;
}
