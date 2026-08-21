/**
 * What the user has selected on the part, and what changing it would do.
 *
 * Kept apart from `studioStore` on purpose. That store owns the *part* — the
 * built solid, its history, undo and redo. This owns a transient pointing
 * gesture: a hovered face, a selected feature, a proposed number. Selection
 * survives no rebuild and belongs in no undo stack, and mixing the two would
 * put a hover into the history the user steps back through.
 *
 * The commit does cross over: it produces a real built part, so it is handed to
 * `studioStore.adopt` and joins the same history as a generated one.
 */

import { create } from 'zustand';
import type { FaceMap, TopoFace, TopologyRecord } from '../lib/faceMap';
import {
    commitAdd,
    commitEdit,
    fetchOperations,
    fetchTopology,
    inspectTarget,
    planAdd,
    planEdit,
    type EditPlan,
    type InspectResult,
    type OperationCatalogue,
    type PlannedOperation,
} from '../services/editApi';
import { useStudioStore } from './studioStore';

interface EditState {
    /** The sidecar for the part on screen, and the triangle→face join. */
    topology: TopologyRecord | null;
    faceMap: FaceMap | null;
    /** Which build the two above describe, so a stale pair is never used. */
    topologyFor: string;

    /** The face under the cursor. The whole record, not just its feature: the
     *  viewer highlights the face itself and the panel names it. */
    hoveredFace: TopoFace | null;
    selectedFeature: string | null;
    selectedFace: TopoFace | null;

    /** Faces the agent picked out in answer to a request like "the two holes
     *  on the left".
     *
     *  Kept apart from `selectedFace` because it is plural and that is not: the
     *  inspector edits one feature at a time, so a set of six faces cannot be
     *  squeezed into the single slot without either losing five of them or
     *  breaking the panel. The viewport lights all of them; when the set is
     *  exactly one, `selectFace` runs as well so the inspector opens on it and
     *  the agent's pick is editable by hand. */
    agentRefs: string[];
    /** The sentence the agent used to describe what it selected. */
    agentSelectionNote: string;

    inspecting: boolean;
    inspection: InspectResult | null;

    /** The parameter being edited and the value being tried. */
    parameter: string | null;
    draft: number | null;
    plan: EditPlan | null;
    planning: boolean;

    committing: boolean;
    error: string | null;

    /** The workbench catalogue, fetched once. */
    catalogue: OperationCatalogue | null;
    /** The operation the user is configuring, and the numbers typed into it. */
    operation: string | null;
    dimensions: Record<string, number>;
    /** What adding it would do. Reported before the kernel runs. */
    proposal: PlannedOperation | null;
    proposing: boolean;

    loadTopology: (requestId: string) => Promise<void>;
    setFaceMap: (map: FaceMap | null, forRequest: string) => void;
    hover: (face: TopoFace | null) => void;
    selectFace: (face: TopoFace | null) => Promise<void>;
    /** Light a set of faces the agent resolved from a request. */
    selectRefs: (refs: string[], note: string) => Promise<void>;
    chooseParameter: (name: string | null) => void;
    setDraft: (value: number) => void;
    preview: () => Promise<void>;
    commit: () => Promise<void>;
    clear: () => void;

    loadCatalogue: () => Promise<void>;
    chooseOperation: (kind: string | null) => void;
    setDimension: (name: string, value: number) => void;
    previewOperation: () => Promise<void>;
    applyOperation: () => Promise<void>;
}

const EMPTY = {
    hoveredFace: null,
    selectedFeature: null,
    selectedFace: null,
    inspection: null,
    parameter: null,
    draft: null,
    plan: null,
    error: null,
    operation: null,
    dimensions: {},
    proposal: null,
    agentRefs: [] as string[],
    agentSelectionNote: '',
};

export const useEditStore = create<EditState>((set, get) => ({
    topology: null,
    faceMap: null,
    topologyFor: '',
    inspecting: false,
    planning: false,
    committing: false,
    catalogue: null,
    proposing: false,
    ...EMPTY,

    clear: () => set({ ...EMPTY }),

    loadTopology: async (requestId) => {
        if (!requestId || get().topologyFor === requestId) return;
        // Cleared before the await, not after: the part on screen has already
        // changed, and a selection pointing into the previous build's faces
        // would highlight the wrong geometry until the fetch returned.
        set({ topology: null, faceMap: null, topologyFor: requestId, ...EMPTY });
        const record = await fetchTopology(requestId);
        if (get().topologyFor !== requestId) return; // a newer part arrived
        set({ topology: record });
    },

    setFaceMap: (map, forRequest) => {
        if (get().topologyFor !== forRequest) return;
        set({ faceMap: map });
    },

    hover: (face) => {
        // Compared by ref, not by identity: the viewer hands back the same
        // record object on every pointer event over one face, but a new object
        // after a rebuild, and re-setting state on every mouse move would
        // re-render the whole panel at pointer rate.
        if (get().hoveredFace?.ref !== face?.ref) set({ hoveredFace: face });
    },

    selectFace: async (face) => {
        if (!face) {
            set({ ...EMPTY });
            return;
        }
        const part = useStudioStore.getState().part;
        if (!part?.blueprint) return;

        set({
            selectedFace: face,
            selectedFeature: face.feature,
            inspection: null,
            parameter: null,
            draft: null,
            plan: null,
            error: null,
            inspecting: true,
            // A click is the user overriding whatever the agent had lit. Left
            // standing, the previous set would keep glowing next to the new
            // pick and neither would read as "the selection".
            agentRefs: [],
            agentSelectionNote: '',
        });

        try {
            // Asked by selector rather than by the feature the client already
            // inferred: the server is the authority on attribution, and a panel
            // that opened on a feature the backend disagrees with would be a
            // silent divergence between two copies of the same rule.
            const result = await inspectTarget({
                blueprint: part.blueprint,
                target: { selector: face.ref },
                request_id: part.requestId,
            });
            if (get().selectedFace?.ref !== face.ref) return;
            set({
                inspection: result,
                selectedFeature: result.feature,
                inspecting: false,
            });
            const first = result.parameters.find((p) => p.direct);
            if (first) set({ parameter: first.name, draft: first.value });
        } catch (e) {
            if (get().selectedFace?.ref !== face.ref) return;
            set({ inspecting: false, error: (e as Error).message });
        }
    },

    /** Light what the agent resolved.
     *
     *  A set of one is promoted to a full selection: the inspector opens on it,
     *  its parameters load, and the user can retune it by hand straight away.
     *  A set of many stays a highlight, because the inspector edits one feature
     *  and pretending otherwise would put a panel of controls next to six faces
     *  and act on one of them. */
    selectRefs: async (refs, note) => {
        const faces = get().topology?.faces ?? [];
        const found = refs
            .map((r) => faces.find((f) => f.ref === r))
            .filter((f): f is TopoFace => !!f);

        if (found.length === 1) {
            await get().selectFace(found[0]);
            set({ agentRefs: refs, agentSelectionNote: note });
            return;
        }
        set({
            ...EMPTY,
            agentRefs: found.map((f) => f.ref),
            agentSelectionNote: note,
            // Named when every face agrees, so the tree can still show which
            // feature is under discussion without claiming a single pick.
            selectedFeature:
                new Set(found.map((f) => f.feature)).size === 1 ? found[0]?.feature ?? null : null,
        });
    },

    chooseParameter: (name) => {
        const found = get().inspection?.parameters.find((p) => p.name === name);
        set({ parameter: name, draft: found ? found.value : null, plan: null });
    },

    setDraft: (value) => set({ draft: value }),

    preview: async () => {
        const { inspection, parameter, draft } = get();
        const part = useStudioStore.getState().part;
        if (!part?.blueprint || !inspection || !parameter || draft == null) return;

        const current = inspection.parameters.find((p) => p.name === parameter);
        if (!current || current.value === draft) {
            set({ plan: null });
            return;
        }

        set({ planning: true, error: null });
        try {
            const { plan } = await planEdit({
                blueprint: part.blueprint,
                target: { feature: inspection.feature },
                parameter,
                value: draft,
            });
            // A slower reply from an earlier drag must not overwrite a newer
            // one; the draft is the ordering key because it is what was asked.
            if (get().draft !== draft || get().parameter !== parameter) return;
            set({ plan, planning: false });
        } catch (e) {
            if (get().draft !== draft) return;
            set({ planning: false, plan: null, error: (e as Error).message });
        }
    },

    loadCatalogue: async () => {
        if (get().catalogue) return;
        try {
            set({ catalogue: await fetchOperations() });
        } catch {
            // A missing catalogue disables the workbench rather than breaking
            // the panel: inspection and retuning still work without it.
        }
    },

    chooseOperation: (kind) => {
        const spec = get().catalogue?.operations.find((o) => o.kind === kind);
        set({
            operation: kind,
            proposal: null,
            error: null,
            dimensions: spec
                ? Object.fromEntries(spec.dimensions.map((d) => [d.name, d.default]))
                : {},
        });
    },

    setDimension: (name, value) =>
        set({ dimensions: { ...get().dimensions, [name]: value }, proposal: null }),

    previewOperation: async () => {
        const { selectedFace, operation, dimensions } = get();
        const part = useStudioStore.getState().part;
        if (!part?.blueprint || !selectedFace || !operation) return;

        set({ proposing: true, error: null });
        try {
            const { operation: proposal } = await planAdd({
                blueprint: part.blueprint,
                operation,
                target: { selector: selectedFace.ref },
                dimensions,
                request_id: part.requestId,
            });
            if (get().operation !== operation) return;
            set({ proposal, proposing: false });
        } catch (e) {
            if (get().operation !== operation) return;
            set({ proposing: false, proposal: null, error: (e as Error).message });
        }
    },

    applyOperation: async () => {
        const { selectedFace, operation, dimensions } = get();
        const studio = useStudioStore.getState();
        const part = studio.part;
        if (!part?.blueprint || !selectedFace || !operation) return;

        set({ committing: true, error: null });
        try {
            const result = await commitAdd({
                blueprint: part.blueprint,
                operation,
                target: { selector: selectedFace.ref },
                dimensions,
                request_id: part.requestId,
            });
            if (!result.success) {
                // `not_applied` is the specific case worth naming: the build
                // worked, the part is unchanged, and the operation is the thing
                // that failed. Saying "the rebuild failed" there would send the
                // user looking at the wrong thing.
                set({
                    committing: false,
                    error:
                        result.not_applied
                            ? `${operation} was not applied — ${result.not_applied}`
                            : result.error || 'the rebuild failed',
                });
                return;
            }
            studio.adopt(
                {
                    partClass: result.part_class,
                    variables: result.variables ?? {},
                    blueprint: result.blueprint,
                    files: result.files ?? {},
                    stats: result.stats,
                    verification: result.verification,
                    generationTimeMs: result.generation_time_ms ?? 0,
                    requestId: result.request_id,
                    featureTree: result.feature_tree ?? null,
                    // True here, unlike a retune. The UI must stop presenting
                    // the verdict as a grade of the model's own design.
                    contractBroken: result.contract_broken,
                },
                studio.partPrompt,
                result.operation.label,
            );
            set({ committing: false, ...EMPTY });
        } catch (e) {
            set({ committing: false, error: (e as Error).message });
        }
    },

    commit: async () => {
        const { inspection, parameter, draft } = get();
        const studio = useStudioStore.getState();
        const part = studio.part;
        if (!part?.blueprint || !inspection || !parameter || draft == null) return;

        set({ committing: true, error: null });
        try {
            const result = await commitEdit({
                blueprint: part.blueprint,
                target: { feature: inspection.feature },
                parameter,
                value: draft,
            });
            if (!result.success) {
                set({ committing: false, error: result.error || 'the rebuild failed' });
                return;
            }
            // Joins the same history as a generated part, because it is one: a
            // solid that was really built, not a replayed command.
            studio.adopt(
                {
                    partClass: result.part_class,
                    variables: result.variables ?? {},
                    blueprint: result.blueprint,
                    files: result.files ?? {},
                    stats: result.stats,
                    verification: result.verification,
                    generationTimeMs: result.generation_time_ms ?? 0,
                    requestId: result.request_id,
                    featureTree: result.feature_tree ?? null,
                    // Structurally always false for a retune, and carried
                    // rather than assumed: if the server ever reports true here
                    // the UI must stop presenting the verdict as a grade of
                    // this part, exactly as it does after a hand-added feature.
                    contractBroken: result.contract_broken,
                },
                studio.partPrompt,
                `${inspection.feature}.${parameter} = ${draft}`,
            );
            set({ committing: false, ...EMPTY });
        } catch (e) {
            set({ committing: false, error: (e as Error).message });
        }
    },
}));
