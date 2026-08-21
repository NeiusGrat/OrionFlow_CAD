/**
 * The manual workbench.
 *
 * Each tool is a real Blueprint operation, not a stub. Pressing one collects
 * its dimensions, names each of them as a variable, appends the feature to the
 * part's template and rebuilds under FreeCAD — the same kernel, the same
 * checker and the same measurement pass a generated part goes through.
 *
 * Naming every dimension is what keeps a hand edit parametric: a fillet added
 * here arrives as `fillet_r_1 = 2`, shows up in the parameters panel with the
 * dimensions the model chose, and can be retuned afterwards like any other.
 * The static checker enforces this — a bare number in a feature is rejected —
 * so it is not a convention that can quietly lapse.
 *
 * Tools that cannot be expressed honestly are listed and disabled with the
 * reason. A button that appears to work and silently does nothing is worse
 * than one that says what it needs.
 */

export type FieldKind = 'number' | 'select';

export interface ToolField {
    key: string;
    label: string;
    kind: FieldKind;
    unit?: string;
    value: number | string;
    min?: number;
    max?: number;
    step?: number;
    options?: { value: string; label: string }[];
    hint?: string;
    /** Only collected when this predicate holds — profile dimensions depend on
     *  which profile was chosen. */
    when?: (v: Record<string, string | number>) => boolean;
}

export interface ToolPayload {
    type: string;
    label: string;
    variables: Record<string, number>;
    parameters: Record<string, unknown>;
    sketch?: { builder: string; plane: string; args: Record<string, string> };
}

export interface ToolSpec {
    id: string;
    label: string;
    /** Blueprint feature type. */
    kind: string;
    group: string;
    icon: string;
    hint: string;
    /** Set when the tool is deliberately not wired up, and why. */
    unavailable?: string;
    fields: ToolField[];
    build: (v: Record<string, string | number>, seq: number) => ToolPayload;
}

const PLANE_FIELD: ToolField = {
    key: 'plane',
    label: 'Sketch plane',
    kind: 'select',
    value: 'XY',
    options: [
        { value: 'XY', label: 'XY — top' },
        { value: 'XZ', label: 'XZ — front' },
        { value: 'YZ', label: 'YZ — right' },
    ],
};

const PROFILE_FIELD: ToolField = {
    key: 'profile',
    label: 'Profile',
    kind: 'select',
    value: 'circle',
    options: [
        { value: 'circle', label: 'Circle' },
        { value: 'rect', label: 'Rectangle' },
        { value: 'rounded_rect', label: 'Rounded rectangle' },
        { value: 'slot', label: 'Slot' },
        { value: 'regular_polygon', label: 'Polygon' },
        { value: 'annulus', label: 'Annulus' },
    ],
};

/** Dimension fields for every profile, shown only for the one selected. */
const PROFILE_DIMS: ToolField[] = [
    { key: 'p_r', label: 'Radius', kind: 'number', unit: 'mm', value: 8, min: 0.1, step: 0.5, when: (v) => v.profile === 'circle' },
    { key: 'p_w', label: 'Width', kind: 'number', unit: 'mm', value: 30, min: 0.1, step: 1, when: (v) => v.profile === 'rect' || v.profile === 'rounded_rect' },
    { key: 'p_h', label: 'Height', kind: 'number', unit: 'mm', value: 20, min: 0.1, step: 1, when: (v) => v.profile === 'rect' || v.profile === 'rounded_rect' },
    { key: 'p_cr', label: 'Corner radius', kind: 'number', unit: 'mm', value: 3, min: 0.1, step: 0.5, when: (v) => v.profile === 'rounded_rect' },
    { key: 'p_len', label: 'Slot length', kind: 'number', unit: 'mm', value: 24, min: 0.1, step: 1, when: (v) => v.profile === 'slot' },
    { key: 'p_sr', label: 'Slot radius', kind: 'number', unit: 'mm', value: 5, min: 0.1, step: 0.5, when: (v) => v.profile === 'slot' },
    { key: 'p_n', label: 'Sides', kind: 'number', value: 6, min: 3, max: 24, step: 1, when: (v) => v.profile === 'regular_polygon' },
    { key: 'p_rc', label: 'Circumradius', kind: 'number', unit: 'mm', value: 12, min: 0.1, step: 0.5, when: (v) => v.profile === 'regular_polygon' },
    { key: 'p_ro', label: 'Outer radius', kind: 'number', unit: 'mm', value: 14, min: 0.1, step: 0.5, when: (v) => v.profile === 'annulus' },
    { key: 'p_ri', label: 'Inner radius', kind: 'number', unit: 'mm', value: 7, min: 0.1, step: 0.5, when: (v) => v.profile === 'annulus' },
];

const EDGE_FIELD: ToolField = {
    key: 'edges',
    label: 'Edges',
    kind: 'select',
    value: 'all',
    hint: 'Selected on the built shape, so the choice survives a dimension change.',
    options: [
        { value: 'all', label: 'All edges' },
        { value: 'vertical', label: 'Vertical' },
        { value: 'horizontal', label: 'Horizontal' },
        { value: 'top', label: 'Top' },
        { value: 'bottom', label: 'Bottom' },
        { value: 'circular', label: 'Circular' },
        { value: 'straight', label: 'Straight' },
        { value: 'convex', label: 'Convex' },
        { value: 'concave', label: 'Concave' },
    ],
};

const FACE_FIELD: ToolField = {
    key: 'faces',
    label: 'Faces',
    kind: 'select',
    value: 'top',
    options: [
        { value: 'top', label: 'Top' },
        { value: 'bottom', label: 'Bottom' },
        { value: 'vertical', label: 'Vertical walls' },
        { value: 'horizontal', label: 'Horizontal' },
        { value: 'all', label: 'All' },
    ],
};

/** Profile builder + its argument names, expressed over the variables the tool
 *  is about to declare. */
function profileSpec(
    v: Record<string, string | number>,
    n: number,
    plane: string,
): { spec: ToolPayload['sketch']; variables: Record<string, number> } {
    const p = String(v.profile);
    const num = (k: string) => Number(v[k]);
    const named = (stem: string) => `${stem}_${n}`;

    switch (p) {
        case 'rect':
            return {
                spec: { builder: 'rect', plane, args: { w: named('w'), h: named('h') } },
                variables: { [named('w')]: num('p_w'), [named('h')]: num('p_h') },
            };
        case 'rounded_rect':
            return {
                spec: { builder: 'rounded_rect', plane, args: { w: named('w'), h: named('h'), r: named('cr') } },
                variables: { [named('w')]: num('p_w'), [named('h')]: num('p_h'), [named('cr')]: num('p_cr') },
            };
        case 'slot':
            return {
                spec: { builder: 'slot', plane, args: { length: named('slot_l'), r: named('slot_r') } },
                variables: { [named('slot_l')]: num('p_len'), [named('slot_r')]: num('p_sr') },
            };
        case 'regular_polygon':
            return {
                // `n` is an instance count, not a dimension — the checker
                // exempts it, so it can travel as a plain number.
                spec: { builder: 'regular_polygon', plane, args: { n: String(num('p_n')), r_circum: named('poly_r') } },
                variables: { [named('poly_r')]: num('p_rc') },
            };
        case 'annulus':
            return {
                spec: { builder: 'annulus', plane, args: { r_outer: named('ro'), r_inner: named('ri') } },
                variables: { [named('ro')]: num('p_ro'), [named('ri')]: num('p_ri') },
            };
        default:
            return {
                spec: { builder: 'circle', plane, args: { r: named('r') } },
                variables: { [named('r')]: num('p_r') },
            };
    }
}

function profileTool(
    id: string,
    label: string,
    kind: string,
    icon: string,
    hint: string,
    depth: ToolField,
    depthParam: (name: string) => Record<string, unknown>,
): ToolSpec {
    return {
        id,
        label,
        kind,
        group: 'Solids',
        icon,
        hint,
        fields: [PROFILE_FIELD, ...PROFILE_DIMS, PLANE_FIELD, depth],
        build: (v, seq) => {
            const plane = String(v.plane || 'XY');
            const { spec, variables } = profileSpec(v, seq, plane);
            const dname = `${id}_${seq}`;
            return {
                type: kind,
                label: `${label} ${seq}`,
                variables: { ...variables, [dname]: Number(v[depth.key]) },
                parameters: depthParam(dname),
                sketch: spec,
            };
        },
    };
}

export const TOOLS: ToolSpec[] = [
    profileTool(
        'extrude', 'Extrude', 'Pad', 'pad',
        'Adds material: a profile pushed along the sketch normal.',
        { key: 'length', label: 'Distance', kind: 'number', unit: 'mm', value: 10, min: 0.1, step: 1 },
        (name) => ({ Length: name, Type: 'Length' }),
    ),
    profileTool(
        'pocket', 'Pocket', 'Pocket', 'pocket',
        'Removes material: a profile cut into the solid.',
        { key: 'length', label: 'Depth', kind: 'number', unit: 'mm', value: 5, min: 0.1, step: 0.5 },
        (name) => ({ Length: name, Type: 'Length' }),
    ),
    profileTool(
        'revolve', 'Revolve', 'Revolution', 'revolve',
        'Sweeps a profile about the sketch axis.',
        { key: 'angle', label: 'Angle', kind: 'number', unit: '°', value: 360, min: 1, max: 360, step: 5 },
        (name) => ({ Angle: name }),
    ),
    profileTool(
        'groove', 'Groove', 'Groove', 'groove',
        'Revolved cut — the subtractive twin of revolve.',
        { key: 'angle', label: 'Angle', kind: 'number', unit: '°', value: 360, min: 1, max: 360, step: 5 },
        (name) => ({ Angle: name }),
    ),

    {
        id: 'fillet', label: 'Fillet', kind: 'Fillet', group: 'Modify', icon: 'fillet',
        hint: 'Rounds edges. Radius has to fit the material either side of the edge.',
        fields: [
            { key: 'radius', label: 'Radius', kind: 'number', unit: 'mm', value: 2, min: 0.05, step: 0.25 },
            EDGE_FIELD,
        ],
        build: (v, seq) => ({
            type: 'Fillet',
            label: `Fillet ${seq}`,
            variables: { [`fillet_r_${seq}`]: Number(v.radius) },
            parameters: { Radius: `fillet_r_${seq}`, _Edges: String(v.edges) },
        }),
    },
    {
        id: 'chamfer', label: 'Chamfer', kind: 'Chamfer', group: 'Modify', icon: 'chamfer',
        hint: 'Breaks edges with a flat. Cheaper to machine than a fillet.',
        fields: [
            { key: 'size', label: 'Size', kind: 'number', unit: 'mm', value: 1, min: 0.05, step: 0.25 },
            EDGE_FIELD,
        ],
        build: (v, seq) => ({
            type: 'Chamfer',
            label: `Chamfer ${seq}`,
            variables: { [`chamfer_s_${seq}`]: Number(v.size) },
            parameters: { Size: `chamfer_s_${seq}`, _Edges: String(v.edges) },
        }),
    },
    {
        id: 'shell', label: 'Shell', kind: 'Thickness', group: 'Modify', icon: 'shell',
        hint: 'Hollows the solid, leaving a wall and opening the chosen faces.',
        fields: [
            { key: 'value', label: 'Wall thickness', kind: 'number', unit: 'mm', value: 2, min: 0.1, step: 0.25 },
            { ...FACE_FIELD, label: 'Faces to open' },
        ],
        build: (v, seq) => ({
            type: 'Thickness',
            label: `Shell ${seq}`,
            variables: { [`shell_t_${seq}`]: Number(v.value) },
            parameters: { Value: `shell_t_${seq}`, _Faces: String(v.faces) },
        }),
    },
    {
        id: 'draft', label: 'Draft', kind: 'Draft', group: 'Modify', icon: 'draft',
        hint: 'Tapers faces so a moulded or cast part releases from the tool.',
        fields: [
            { key: 'angle', label: 'Draft angle', kind: 'number', unit: '°', value: 2, min: 0.1, max: 45, step: 0.5 },
            { ...FACE_FIELD, value: 'vertical', label: 'Faces to taper' },
        ],
        build: (v, seq) => ({
            type: 'Draft',
            label: `Draft ${seq}`,
            variables: { [`draft_a_${seq}`]: Number(v.angle) },
            parameters: { Angle: `draft_a_${seq}`, _Faces: String(v.faces) },
        }),
    },

    {
        id: 'linear', label: 'Linear', kind: 'LinearPattern', group: 'Pattern', icon: 'linear',
        hint: 'Repeats the last feature along an axis.',
        fields: [
            { key: 'length', label: 'Total length', kind: 'number', unit: 'mm', value: 40, min: 0.1, step: 1 },
            { key: 'count', label: 'Occurrences', kind: 'number', value: 3, min: 2, max: 200, step: 1 },
            {
                key: 'axis', label: 'Direction', kind: 'select', value: 'X_Axis',
                options: [
                    { value: 'X_Axis', label: 'X' },
                    { value: 'Y_Axis', label: 'Y' },
                    { value: 'Z_Axis', label: 'Z' },
                ],
            },
        ],
        build: (v, seq) => ({
            type: 'LinearPattern',
            label: `Linear pattern ${seq}`,
            variables: { [`pattern_l_${seq}`]: Number(v.length) },
            parameters: {
                Length: `pattern_l_${seq}`,
                Occurrences: Number(v.count),
                _Direction: { role: String(v.axis) },
            },
        }),
    },
    {
        id: 'polar', label: 'Polar', kind: 'PolarPattern', group: 'Pattern', icon: 'polar',
        hint: 'Repeats the last feature about an axis — bolt circles, spokes, teeth.',
        fields: [
            { key: 'angle', label: 'Sweep', kind: 'number', unit: '°', value: 360, min: 1, max: 360, step: 5 },
            { key: 'count', label: 'Occurrences', kind: 'number', value: 6, min: 2, max: 200, step: 1 },
            {
                key: 'axis', label: 'Axis', kind: 'select', value: 'Z_Axis',
                options: [
                    { value: 'Z_Axis', label: 'Z' },
                    { value: 'X_Axis', label: 'X' },
                    { value: 'Y_Axis', label: 'Y' },
                ],
            },
        ],
        build: (v, seq) => ({
            type: 'PolarPattern',
            label: `Polar pattern ${seq}`,
            variables: { [`polar_a_${seq}`]: Number(v.angle) },
            parameters: {
                Angle: `polar_a_${seq}`,
                Occurrences: Number(v.count),
                _Axis: { role: String(v.axis) },
            },
        }),
    },
    {
        id: 'mirror', label: 'Mirror', kind: 'Mirrored', group: 'Pattern', icon: 'mirror',
        hint: 'Reflects the last feature across a datum plane.',
        fields: [
            {
                key: 'plane', label: 'Mirror plane', kind: 'select', value: 'YZ_Plane',
                options: [
                    { value: 'YZ_Plane', label: 'YZ' },
                    { value: 'XZ_Plane', label: 'XZ' },
                    { value: 'XY_Plane', label: 'XY' },
                ],
            },
        ],
        build: (v, seq) => ({
            type: 'Mirrored',
            label: `Mirror ${seq}`,
            variables: {},
            parameters: { _Plane: { role: String(v.plane) } },
        }),
    },

    // Both need more than one profile — a set of sections for a loft, a spine
    // and a section for a sweep — which a single-profile dialog cannot express.
    // Shown rather than hidden, so the toolbar tells the truth about what the
    // workbench can and cannot do, and points at the route that does work.
    {
        id: 'loft', label: 'Loft', kind: 'Loft', group: 'Solids', icon: 'loft',
        hint: 'Blends between profiles.',
        unavailable: 'A loft needs two or more sections. Describe the transition to Orion and it will build one.',
        fields: [],
        build: () => ({ type: 'Loft', label: 'Loft', variables: {}, parameters: {} }),
    },
    {
        id: 'sweep', label: 'Sweep', kind: 'Sweep', group: 'Solids', icon: 'sweep',
        hint: 'Drives a profile along a path.',
        unavailable: 'A sweep needs a profile and a separate path sketch. Describe it to Orion and it will build one.',
        fields: [],
        build: () => ({ type: 'Sweep', label: 'Sweep', variables: {}, parameters: {} }),
    },
];

export const TOOL_GROUPS = ['Solids', 'Modify', 'Pattern'] as const;

export function toolsIn(group: string): ToolSpec[] {
    return TOOLS.filter((t) => t.group === group);
}

export function findTool(id: string): ToolSpec | undefined {
    return TOOLS.find((t) => t.id === id);
}

/** Fields that apply given the values collected so far. */
export function activeFields(
    tool: ToolSpec,
    values: Record<string, string | number>,
): ToolField[] {
    return tool.fields.filter((f) => !f.when || f.when(values));
}

export function defaultValues(tool: ToolSpec): Record<string, string | number> {
    const out: Record<string, string | number> = {};
    for (const f of tool.fields) out[f.key] = f.value;
    return out;
}
