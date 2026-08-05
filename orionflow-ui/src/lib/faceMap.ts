/**
 * Which CAD face is each triangle of the mesh?
 *
 * The viewer renders one merged mesh. The topology sidecar knows every CAD face
 * and which Blueprint feature authored it, but nothing joins the two — a
 * raycast returns a triangle index, and a triangle index means nothing to a
 * feature tree.
 *
 * This computes the join once, when the model loads, by asking of every
 * triangle the same question the server asks of a click: which face's surface
 * is this point on? The distance maths is a deliberate port of
 * `app/services/topology.py::_distance_to_face` — exact for the planes,
 * cylinders and spheres these parts are made of, bounded by each face's own
 * extent because a plane is infinite and the face cut from it is not.
 *
 * Two things fall out of it:
 *
 *  - **clicking is local.** A pick resolves to a face and a feature with no
 *    round trip, so hover highlighting costs nothing.
 *  - **highlighting is exact.** Triangles are regrouped by feature so the
 *    renderer can give one feature its own material, rather than tinting a
 *    bounding box and hoping.
 *
 * The alternative was a GLB with one primitive per face. That means changing
 * how every model is exported and rendered; this needs neither, and the sidecar
 * it reads is already being served.
 */

import * as THREE from 'three';

/**
 * One element of the built shape — a face, or an edge.
 *
 * Both come out of the same sidecar with the same identity fields, and both are
 * selectable, so they share a type rather than being split into two that agree
 * on nine fields out of twelve. `surface` is set for faces, `curve` and `ends`
 * for edges; `ref` says which it is.
 */
export interface TopoFace {
    ref: string;
    index: number;
    stable?: string;
    feature: string | null;
    lineage?: string[];
    surface?: string;
    /** Edges only: `Line`, `Circle`, … */
    curve?: string;
    /** Edges only: the two endpoints, for straight edges. */
    ends?: number[][];
    length?: number;
    area?: number;
    radius?: number;
    /** Toroid only — it has no plain `radius`. */
    major_radius?: number;
    minor_radius?: number;
    axis?: number[];
    position?: number[];
    center?: number[];
    normal?: number[];
    bbox?: number[];
}

export interface TopologyRecord {
    schema?: string;
    attribution?: string;
    counts?: Record<string, number>;
    faces?: TopoFace[];
    edges?: unknown[];
    vertices?: unknown[];
    features?: Record<
        string,
        {
            type?: string;
            build_index?: number;
            blueprint_feature?: boolean | null;
            faces?: string[];
            edges?: string[];
            vertices?: string[];
        }
    >;
    error?: string;
}

/** The join, plus everything the renderer and the panel need from it. */
export interface FaceMap {
    /** Feature id per triangle, in the *reordered* index order. */
    featureOf: (triangle: number) => string | null;
    /** CAD face record per triangle, in the reordered index order. */
    faceOf: (triangle: number) => TopoFace | null;
    /** Draw groups, one per feature, in the order they were written. */
    groups: { feature: string | null; start: number; count: number }[];
    /** Feature id → its group index, for material swapping. */
    groupOfFeature: Map<string | null, number>;
    /**
     * Triangle indices per CAD face ref, in reordered order.
     *
     * What makes single-face highlighting possible without one draw group per
     * face: the viewer lifts just these triangles into a thin overlay mesh
     * rather than splitting the part into 121 groups, so a part with many faces
     * costs one extra draw call instead of a hundred.
     */
    trianglesOfFace: Map<string, number[]>;
    /** How many triangles could not be attributed to any face. */
    unassigned: number;
}

/** `Part::GeomPlane` and `Plane` are the same surface spelled two ways.
 *
 *  Matching only one makes every distance silently fall back to a centroid —
 *  a wrong answer that still looks like an answer. The server had this exact
 *  bug; normalising in both places is cheaper than keeping them in step. */
function surfaceKind(face: TopoFace): string {
    const name = face.surface || '';
    return name.split('::').pop()!.replace('Geom', '');
}

function withinBBox(p: THREE.Vector3, bbox: number[] | undefined, slack: number): boolean {
    if (!bbox || bbox.length !== 6) return true;
    return (
        p.x >= bbox[0] - slack &&
        p.x <= bbox[3] + slack &&
        p.y >= bbox[1] - slack &&
        p.y <= bbox[4] + slack &&
        p.z >= bbox[2] - slack &&
        p.z <= bbox[5] + slack
    );
}

/** Distance from a point to a face's surface. See the module docstring. */
function distanceTo(p: THREE.Vector3, face: TopoFace): number | null {
    const kind = surfaceKind(face);
    const pos = face.position;
    const r = face.radius;

    if (kind === 'Plane' && pos && face.normal) {
        const n = face.normal;
        return Math.abs((p.x - pos[0]) * n[0] + (p.y - pos[1]) * n[1] + (p.z - pos[2]) * n[2]);
    }

    if (kind === 'Cylinder' && pos && face.axis && r != null) {
        const a = face.axis;
        const dx = p.x - pos[0];
        const dy = p.y - pos[1];
        const dz = p.z - pos[2];
        const along = dx * a[0] + dy * a[1] + dz * a[2];
        const px = dx - along * a[0];
        const py = dy - along * a[1];
        const pz = dz - along * a[2];
        return Math.abs(Math.hypot(px, py, pz) - r);
    }

    if (kind === 'Sphere' && pos && r != null) {
        return Math.abs(Math.hypot(p.x - pos[0], p.y - pos[1], p.z - pos[2]) - r);
    }

    if (kind === 'Toroid' && pos && face.axis) {
        const R = face.major_radius;
        const minor = face.minor_radius;
        if (R != null && minor != null) {
            // Collapse to the generating circle of radius R in the plane
            // through `pos` normal to the axis, then measure the tube.
            // A toroid is where two fillets meet and it blends tangentially
            // into both neighbours, so without this the neighbour always wins.
            const a = face.axis;
            const dx = p.x - pos[0];
            const dy = p.y - pos[1];
            const dz = p.z - pos[2];
            const along = dx * a[0] + dy * a[1] + dz * a[2];
            const px = dx - along * a[0];
            const py = dy - along * a[1];
            const pz = dz - along * a[2];
            const radial = Math.hypot(px, py, pz) - R;
            return Math.abs(Math.hypot(radial, along) - minor);
        }
    }

    const c = face.center;
    if (c) return Math.hypot(p.x - c[0], p.y - c[1], p.z - c[2]);
    return null;
}

/**
 * Attribute every triangle, then reorder the index buffer so each feature's
 * triangles are contiguous and can be drawn as one group.
 *
 * Reordering rather than per-vertex colouring is what keeps the machined-metal
 * look: a group gets a real material, with its own metalness and emissive, and
 * the highlight is a material swap rather than a tint painted over one.
 *
 * Mutates `geometry` — it is called once per loaded model and guards itself.
 */
export function buildFaceMap(geometry: THREE.BufferGeometry, topology: TopologyRecord): FaceMap | null {
    const faces = (topology.faces || []).filter((f) => f && f.surface);
    if (!faces.length) return null;

    const position = geometry.getAttribute('position');
    if (!position) return null;

    // A non-indexed geometry gets an identity index so the reorder below has
    // something to permute; three renders both the same way.
    if (!geometry.getIndex()) {
        const identity = new Uint32Array(position.count);
        for (let i = 0; i < position.count; i++) identity[i] = i;
        geometry.setIndex(new THREE.BufferAttribute(identity, 1));
    }
    const index = geometry.getIndex()!;
    const triangleCount = Math.floor(index.count / 3);

    // Slack scales with the part: a coarse tessellation puts a triangle
    // centroid measurably off a curved surface, and a fixed tolerance would
    // either drop those on a large part or over-match on a small one.
    geometry.computeBoundingSphere();
    const slack = Math.max((geometry.boundingSphere?.radius ?? 10) * 0.02, 0.05);

    const assigned: (TopoFace | null)[] = new Array(triangleCount).fill(null);
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const c = new THREE.Vector3();
    const centroid = new THREE.Vector3();
    let unassigned = 0;

    for (let t = 0; t < triangleCount; t++) {
        a.fromBufferAttribute(position, index.getX(t * 3));
        b.fromBufferAttribute(position, index.getX(t * 3 + 1));
        c.fromBufferAttribute(position, index.getX(t * 3 + 2));
        centroid.copy(a).add(b).add(c).multiplyScalar(1 / 3);

        let best: TopoFace | null = null;
        let bestDistance = Infinity;
        for (const face of faces) {
            if (!withinBBox(centroid, face.bbox, slack)) continue;
            const d = distanceTo(centroid, face);
            if (d == null || d >= bestDistance) continue;
            bestDistance = d;
            best = face;
        }
        if (best) assigned[t] = best;
        else unassigned++;
    }

    // Group by feature, keeping the sidecar's feature order so the colouring is
    // stable between rebuilds rather than following hash order.
    const order: (string | null)[] = [];
    const buckets = new Map<string | null, number[]>();
    for (let t = 0; t < triangleCount; t++) {
        const key = assigned[t]?.feature ?? null;
        let bucket = buckets.get(key);
        if (!bucket) {
            bucket = [];
            buckets.set(key, bucket);
            order.push(key);
        }
        bucket.push(t);
    }

    const source = index.array;
    const reordered = new (source.constructor as new (n: number) => typeof source)(
        index.count,
    );
    const triangleFace: (TopoFace | null)[] = new Array(triangleCount).fill(null);
    const groups: FaceMap['groups'] = [];
    const groupOfFeature = new Map<string | null, number>();

    const trianglesOfFace = new Map<string, number[]>();

    let cursor = 0;
    for (const key of order) {
        const bucket = buckets.get(key)!;
        const start = cursor;
        for (const t of bucket) {
            const triangle = cursor / 3;
            const face = assigned[t];
            triangleFace[triangle] = face;
            if (face) {
                const list = trianglesOfFace.get(face.ref);
                if (list) list.push(triangle);
                else trianglesOfFace.set(face.ref, [triangle]);
            }
            reordered[cursor] = source[t * 3];
            reordered[cursor + 1] = source[t * 3 + 1];
            reordered[cursor + 2] = source[t * 3 + 2];
            cursor += 3;
        }
        groupOfFeature.set(key, groups.length);
        groups.push({ feature: key, start, count: bucket.length * 3 });
    }

    index.set(reordered);
    index.needsUpdate = true;

    geometry.clearGroups();
    groups.forEach((g, i) => geometry.addGroup(g.start, g.count, i));

    return {
        featureOf: (triangle) => triangleFace[triangle]?.feature ?? null,
        faceOf: (triangle) => triangleFace[triangle] ?? null,
        groups,
        groupOfFeature,
        trianglesOfFace,
        unassigned,
    };
}

/** Distance from a point to a line segment, clamped to the segment. */
function distanceToSegment(p: THREE.Vector3, a: number[], b: number[]): number {
    const abx = b[0] - a[0];
    const aby = b[1] - a[1];
    const abz = b[2] - a[2];
    const len2 = abx * abx + aby * aby + abz * abz;
    if (len2 === 0) return Math.hypot(p.x - a[0], p.y - a[1], p.z - a[2]);
    let t = ((p.x - a[0]) * abx + (p.y - a[1]) * aby + (p.z - a[2]) * abz) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(
        p.x - (a[0] + t * abx),
        p.y - (a[1] + t * aby),
        p.z - (a[2] + t * abz),
    );
}

/**
 * The CAD edge nearest a point, if one is close enough to have been meant.
 *
 * Edges cannot be raycast: they are drawn as `LineSegments` with picking
 * disabled, because a one-pixel line stealing every click would make faces
 * unselectable. But an edge operation — chamfer, fillet — has no other way to
 * be aimed, so the pick is resolved by proximity instead: raycast the solid,
 * then ask whether the hit landed near a boundary.
 *
 * `tolerance` is a world-space distance and should scale with the part, not the
 * screen. Too tight and edges are unhittable; too loose and the middle of a
 * small face resolves to its rim.
 */
export function pickEdge(
    topology: TopologyRecord,
    point: THREE.Vector3,
    tolerance: number,
): TopoFace | null {
    const edges = (topology.edges as TopoFace[] | undefined) || [];
    let best: TopoFace | null = null;
    let bestDistance = tolerance;

    for (const edge of edges) {
        let d: number;
        if (edge.ends && edge.ends.length === 2) {
            d = distanceToSegment(point, edge.ends[0], edge.ends[1]);
        } else if (edge.center && edge.radius != null) {
            // A circular rim: everything on it is `radius` from the centre, so
            // the distance to the circle is what is left after removing that.
            const c = edge.center;
            const dx = point.x - c[0];
            const dy = point.y - c[1];
            const dz = point.z - c[2];
            d = Math.abs(Math.hypot(dx, dy, dz) - edge.radius);
        } else if (edge.center) {
            const c = edge.center;
            d = Math.hypot(point.x - c[0], point.y - c[1], point.z - c[2]);
        } else {
            continue;
        }
        if (d < bestDistance) {
            bestDistance = d;
            best = edge;
        }
    }
    return best;
}

/**
 * A thin geometry holding only the triangles of one CAD face.
 *
 * Drawn over the part with a polygon offset so a single face can be lit without
 * splitting the mesh into a draw group per face. Returns null when the face has
 * no triangles, which happens for a face the tessellation never reached.
 */
export function faceOverlay(
    geometry: THREE.BufferGeometry,
    map: FaceMap,
    ref: string | null | undefined,
): THREE.BufferGeometry | null {
    if (!ref) return null;
    const triangles = map.trianglesOfFace.get(ref);
    if (!triangles || !triangles.length) return null;

    const index = geometry.getIndex();
    const position = geometry.getAttribute('position');
    if (!index || !position) return null;

    // Vertices are copied rather than referenced so the overlay owns its
    // buffers: the base geometry belongs to the GLTF cache and is reused when
    // the same model is opened again.
    const out = new Float32Array(triangles.length * 9);
    let w = 0;
    for (const t of triangles) {
        for (let c = 0; c < 3; c++) {
            const v = index.getX(t * 3 + c);
            out[w++] = position.getX(v);
            out[w++] = position.getY(v);
            out[w++] = position.getZ(v);
        }
    }
    const overlay = new THREE.BufferGeometry();
    overlay.setAttribute('position', new THREE.BufferAttribute(out, 3));
    overlay.computeVertexNormals();
    return overlay;
}
