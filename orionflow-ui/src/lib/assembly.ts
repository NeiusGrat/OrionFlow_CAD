/**
 * An articulated reference assembly: what it is made of and how it moves.
 *
 * The manifest is written by `microduck/tools/export_viewer.py` next to the
 * GLB, from the same model the STEP and FCStd were assembled from. A body's
 * frame is `parent · rest · R(axis, q)` — the composition the exporter checks
 * every body against at every named pose before it writes anything, so the
 * viewer moving a joint and the CAD file at that pose cannot disagree.
 *
 * Pure data and arithmetic, no three.js, so the agent tests can run it.
 */

export interface AssemblyJoint {
    name: string;
    label: string;
    axis: [number, number, number];
    /** Radians. Null means the joint is unbounded. */
    range: [number, number] | null;
}

export interface AssemblyBody {
    name: string;
    /** GLB node name. */
    node: string;
    parent: string | null;
    /** Row-major 4x4, millimetres, relative to the parent body. */
    rest: number[];
    mass_g: number;
    joint: AssemblyJoint | null;
}

export interface AssemblyInstance {
    id: string;
    node: string;
    part: string;
    body: string;
    color: [number, number, number, number];
}

export type GeometrySource = 'modelled' | 'revolved' | 'slab' | 'faceted';

export interface AssemblyPart {
    label: string;
    file: string;
    source: GeometrySource;
    source_note: string;
    faces: number;
    curved_faces: number;
    triangles: number;
    volume_mm3: number;
    area_mm2: number;
    bbox_mm: [number, number, number];
    closed_solid: boolean;
    valid: boolean;
    instances: number;
}

export interface AssemblyManifest {
    name: string;
    units: 'mm';
    up: 'Z';
    source: { robot: string; onshape: string; simulator: string; note: string };
    joints: string[];
    bodies: AssemblyBody[];
    instances: AssemblyInstance[];
    parts: Record<string, AssemblyPart>;
    poses: Record<string, Record<string, number>>;
    totals: {
        parts: number;
        instances: number;
        mass_g: number;
        by_source: Partial<Record<GeometrySource, number>>;
        instances_by_source: Partial<Record<GeometrySource, number>>;
        triangles: number;
    };
}

export type Angles = Record<string, number>;

/* ─────────────────────────── matrices ─────────────────────────── */

/** Row-major 4x4 rotation about a unit `axis` (Rodrigues). */
export function axisRotation(axis: [number, number, number], angle: number): number[] {
    const n = Math.hypot(axis[0], axis[1], axis[2]) || 1;
    const [x, y, z] = [axis[0] / n, axis[1] / n, axis[2] / n];
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const t = 1 - c;
    return [
        t * x * x + c, t * x * y - s * z, t * x * z + s * y, 0,
        t * x * y + s * z, t * y * y + c, t * y * z - s * x, 0,
        t * x * z - s * y, t * y * z + s * x, t * z * z + c, 0,
        0, 0, 0, 1,
    ];
}

/** Row-major 4x4 product a·b. */
export function mul(a: number[], b: number[]): number[] {
    const out = new Array(16).fill(0);
    for (let r = 0; r < 4; r++)
        for (let c = 0; c < 4; c++) {
            let v = 0;
            for (let k = 0; k < 4; k++) v += a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = v;
        }
    return out;
}

/** A body's transform relative to its parent at joint angle `q`. */
export function bodyLocal(body: AssemblyBody, q: number): number[] {
    if (!body.joint || !q) return body.rest;
    return mul(body.rest, axisRotation(body.joint.axis, q));
}

/** Every body's world transform (row-major), for checking and for tests. */
export function worldTransforms(m: AssemblyManifest, angles: Angles): Record<string, number[]> {
    const out: Record<string, number[]> = {};
    for (const b of m.bodies) {
        const local = bodyLocal(b, b.joint ? angles[b.joint.name] ?? 0 : 0);
        out[b.name] = b.parent ? mul(out[b.parent], local) : local;
    }
    return out;
}

/* ─────────────────────────── motion ─────────────────────────── */

export function clampToJoint(joint: AssemblyJoint, q: number): number {
    if (!joint.range) return q;
    return Math.min(joint.range[1], Math.max(joint.range[0], q));
}

/** A named pose as a full angle set, every joint present and in range. */
export function poseAngles(m: AssemblyManifest, pose: string): Angles {
    const named = m.poses[pose] ?? {};
    const out: Angles = {};
    for (const b of m.bodies) {
        if (b.joint) out[b.joint.name] = clampToJoint(b.joint, named[b.joint.name] ?? 0);
    }
    return out;
}

/** Linear blend between two angle sets, eased at both ends. */
export function blend(a: Angles, b: Angles, t: number): Angles {
    const e = t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
    const out: Angles = {};
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
        out[k] = (a[k] ?? 0) + ((b[k] ?? 0) - (a[k] ?? 0)) * e;
    }
    return out;
}

/**
 * A stepping-in-place cycle, from the stand pose.
 *
 * Kinematic playback, not a simulation: nothing here knows about balance or
 * contact, and the trunk does not travel. The legs are mirror images with
 * mirrored pitch axes, so each leg's cycle is written as flexion (hip h, knee
 * k) and turned into joint angles with that leg's own direction, read from
 * the stand pose rather than assumed. The ankle takes k - h, which keeps the
 * sole parallel to the trunk throughout; every angle is clamped to its range.
 */
export function walkAngles(m: AssemblyManifest, phase: number): Angles {
    const base = poseAngles(m, 'stand');
    const out: Angles = { ...base };
    const leg = (side: 'left' | 'right', p: number) => {
        const dir = Math.sign(base[`${side}_knee`] || 1);
        const h0 = (base[`${side}_hip_pitch`] ?? 0) * dir;
        const k0 = (base[`${side}_knee`] ?? 0) * dir;
        const swing = Math.sin(p);
        const lift = Math.max(0, Math.sin(p + Math.PI / 2));
        const h = h0 + 0.3 * swing + 0.28 * lift;
        const k = k0 + 0.56 * lift;
        out[`${side}_hip_pitch`] = dir * h;
        out[`${side}_knee`] = dir * k;
        out[`${side}_ankle`] = dir * (k - h);
    };
    leg('left', phase);
    leg('right', phase + Math.PI);
    // No hip-roll sway: the ankle has no roll joint, so any roll at the hip
    // tilts the sole sideways (0.05 rad of sway was 2.9 degrees of tilt).
    out.head_yaw = 0.18 * Math.sin(phase / 2);
    out.head_roll = 0.06 * Math.sin(phase);
    for (const b of m.bodies) {
        if (b.joint && b.joint.name in out) out[b.joint.name] = clampToJoint(b.joint, out[b.joint.name]);
    }
    return out;
}

/* ─────────────────────────── describing ─────────────────────────── */

/** The joint that moves a body: its own, or the nearest one above it. */
export function drivingJoint(m: AssemblyManifest, bodyName: string): AssemblyJoint | null {
    const byName = new Map(m.bodies.map((b) => [b.name, b]));
    let b = byName.get(bodyName);
    while (b) {
        if (b.joint) return b.joint;
        b = b.parent ? byName.get(b.parent) : undefined;
    }
    return null;
}

/** Bodies from the root down to `bodyName`, for a breadcrumb. */
export function bodyPath(m: AssemblyManifest, bodyName: string): string[] {
    const byName = new Map(m.bodies.map((b) => [b.name, b]));
    const path: string[] = [];
    let b = byName.get(bodyName);
    while (b) {
        path.unshift(b.name);
        b = b.parent ? byName.get(b.parent) : undefined;
    }
    return path;
}

export const SOURCE_LABEL: Record<GeometrySource, string> = {
    modelled: 'Hand-modelled',
    revolved: 'Revolved rebuild',
    slab: 'Profile rebuild',
    faceted: 'Faceted from mesh',
};

export const deg = (r: number) => (r * 180) / Math.PI;
