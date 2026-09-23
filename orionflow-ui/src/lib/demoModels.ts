/**
 * Reference models the studio can show on request, clearly labelled as such.
 *
 * MicroDuck is a legged robot assembly — 71 placed parts — that the build path
 * cannot produce from a sentence yet. It was rebuilt offline from Pollen
 * Robotics' open simulator (`microduck/` at the repo root) and verified there.
 * Asking for it in the studio loads that finished assembly so a demo can show
 * where the product is going.
 *
 * It must never read as generated. The turn says it is a reference model, it
 * carries no verification report and no Blueprint, and the action chip says
 * "loaded", not "built". A demo that passed a pre-built part off as text-to-CAD
 * would be the one thing worse than not having the part.
 *
 * Pure data and one matcher, so the router tests can exercise it without a
 * store or a browser.
 */

export type DuckPose = 'zero' | 'stand' | 'crouch' | 'walk' | 'rollers';

export interface DemoModel {
    id: string;
    title: string;
    pose: DuckPose;
    /** The articulated assembly: same-origin paths under `public/`, and the
     *  pose (or "walk") the viewer should move to. */
    assembly: { manifest: string; glb: string; pose: string };
    bbox_mm: [number, number, number];
    volume_mm3: number;
    parts: number;
}

/** Numbers from `microduck/work/assembly_report.json`, one entry per pose.
 *  The walk cycle starts from the stand pose, so it reports that one. */
const MICRODUCK: Record<DuckPose, Pick<DemoModel, 'bbox_mm' | 'volume_mm3' | 'parts'>> = {
    zero: { bbox_mm: [144.07, 141.0, 263.97], volume_mm3: 549695.0, parts: 71 },
    stand: { bbox_mm: [185.22, 141.0, 262.83], volume_mm3: 549695.0, parts: 71 },
    crouch: { bbox_mm: [149.53, 141.0, 251.7], volume_mm3: 549695.0, parts: 71 },
    walk: { bbox_mm: [185.22, 141.0, 262.83], volume_mm3: 549695.0, parts: 71 },
    rollers: { bbox_mm: [164.55, 141.0, 286.43], volume_mm3: 542327.6, parts: 77 },
};

const NAMES = /\bmicro[\s_-]?duck\b/i;

/** Words that pick a pose. "zero" is the default and needs no word. */
const POSE_WORDS: [DuckPose, RegExp][] = [
    ['rollers', /\b(roller|rollers|wheel|wheels|wheeled|skate|skates)\b/i],
    ['crouch', /\b(crouch|crouching|crouched|squat|squatting|bent)\b/i],
    ['walk', /\b(walk|walking|walks|step|stepping|march|marching|moving|motion|animate|animated)\b/i],
    ['stand', /\b(stand|standing|stride)\b/i],
];

/**
 * Asking about MicroDuck ("what is microduck?") should still be a question.
 * Only a request to see or make it loads the model.
 */
const WANTS_MODEL =
    /\b(show|load|open|display|view|see|create|build|make|design|generate|model|draw|give me|i need|i want)\b/i;

export function matchDemoModel(message: string): DemoModel | null {
    const text = message.replace(/^\/\w+\s*/, '');
    if (!NAMES.test(text) || !WANTS_MODEL.test(text)) return null;

    const pose = POSE_WORDS.find(([, re]) => re.test(text))?.[0] ?? 'zero';
    return {
        id: `microduck-${pose}`,
        title: 'MicroDuck',
        pose,
        assembly: {
            manifest: `/demo/microduck/${pose === 'rollers' ? 'microduck_rollers' : 'microduck'}.json`,
            glb: `/demo/microduck/${pose === 'rollers' ? 'microduck_rollers' : 'microduck'}.glb`,
            pose: pose === 'rollers' ? 'zero' : pose,
        },
        ...MICRODUCK[pose],
    };
}
