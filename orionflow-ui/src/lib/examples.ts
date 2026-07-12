/** Shared access to the showcase example library (public/examples/manifest.json). */
import { useDesignStore } from "../store/designStore";
import { useChatStore } from "../store/chatStore";
import { useOFLStore } from "../store/oflStore";
import type { OFLParameter } from "../services/oflApi";

export interface ExampleEntry {
    id: string;
    title: string;
    category: string;
    prompt: string;
    ofl_code: string;
    parameters: OFLParameter[];
    files: { glb: string; step: string; stl: string };
    stats?: { volume_mm3: number; bbox_mm: number[]; triangles: number };
}

let manifestCache: ExampleEntry[] | null = null;

export async function fetchExamples(): Promise<ExampleEntry[]> {
    if (manifestCache) return manifestCache;
    const res = await fetch("/examples/manifest.json");
    if (!res.ok) throw new Error("Failed to load examples");
    const data = await res.json();
    manifestCache = data.examples as ExampleEntry[];
    return manifestCache;
}

export function loadExampleIntoStudio(ex: ExampleEntry) {
    const designId = `example-${ex.id}`;
    const store = useDesignStore.getState();
    const existing = store.creations.find((c) => c.id === designId);

    useOFLStore.setState({
        oflCode: ex.ofl_code,
        parameters: ex.parameters,
        glbUrl: ex.files.glb,
        stepUrl: ex.files.step,
        stlUrl: ex.files.stl,
        error: null,
        isGenerating: false,
        generationTimeMs: 0,
    });

    if (existing) {
        store.setCurrent(designId);
        return;
    }

    store.addCreation({
        id: designId,
        prompt: ex.prompt,
        parameters: Object.fromEntries(ex.parameters.map((p) => [p.name, p.value])),
        material: { roughness: 0.5, metalness: 0.1 },
        files: { ...ex.files },
    });

    const chat = useChatStore.getState();
    chat.addMessage(designId, {
        id: crypto.randomUUID(),
        role: "user",
        content: ex.prompt,
        timestamp: Date.now(),
    });
    chat.addMessage(designId, {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Loaded example "${ex.title}". Edit the code, drag a parameter, or describe a change to make it yours.`,
        timestamp: Date.now(),
        partVersion: 1,
        files: { ...ex.files },
    });
}
