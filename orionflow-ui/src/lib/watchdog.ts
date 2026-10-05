/** Helpers shared by the watchdog modules (kept out of component files for fast refresh). */
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { blobUrl } from "../services/watchdogApi";

/** three's GLTFLoader renames nodes ("asm/plate" -> "asmplate"); compare like with like. */
export const nodeKey = (name: string) => THREE.PropertyBinding.sanitizeNodeName(name);

export const STAGES: [string, string, string][] = [
    ["01", "file_validation", "File"],
    ["02", "complexity", "Complexity"],
    ["03", "geometry_extraction", "Geometry"],
    ["04", "part_identification", "Parts"],
    ["05", "assembly_structure", "Structure"],
    ["06", "interface_detection", "Interfaces"],
    ["07", "clearance_collision", "Clearance"],
    ["08", "bom_consistency", "BOM"],
    ["09", "drawing_consistency", "Drawings"],
    ["10", "revision_comparison", "Revision"],
    ["11", "gdt_dimensions", "GD&T"],
    ["12", "robot_model", "Robot model"],
    ["13", "manufacturing", "Manufacturing"],
    ["14", "evidence", "Evidence"],
    ["15", "final_report", "Report"],
];

/** An authenticated file as an object URL, revoked when it changes or unmounts. */
export function useBlobUrl(path: string | null, what: string): { url: string | null; error: string | null } {
    const [state, setState] = useState<{ url: string | null; error: string | null }>({ url: null, error: null });
    useEffect(() => {
        if (!path) { setState({ url: null, error: null }); return; }
        let live = true;
        let made: string | null = null;
        blobUrl(path, what)
            .then((u) => { made = u; if (live) setState({ url: u, error: null }); else URL.revokeObjectURL(u); })
            .catch((e) => live && setState({ url: null, error: String(e.message ?? e) }));
        return () => { live = false; if (made) URL.revokeObjectURL(made); };
    }, [path, what]);
    return state;
}

/** Re-run `fn` every `ms` while `active`. */
export function usePoll(fn: () => void, ms: number, active: boolean) {
    const ref = useRef(fn);
    ref.current = fn;
    useEffect(() => {
        if (!active) return;
        const t = setInterval(() => ref.current(), ms);
        return () => clearInterval(t);
    }, [ms, active]);
}

export function ago(when: string | number): string {
    const t = typeof when === "number" ? when * 1000 : Date.parse(when);
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return new Date(t).toLocaleDateString();
}

/** Render a measured/expected value without "[object Object]". */
export function show(v: unknown): string {
    if (v == null) return "—";
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    if (typeof v === "string") return v;
    if (Array.isArray(v)) return v.map(show).join(", ");
    return JSON.stringify(v);
}

export const SEV_COLOR: Record<string, string> = {
    high: "#ff5d6e", error: "#ff5d6e", medium: "#ffb547", warning: "#ffb547", low: "#5ec8ff", info: "#9fb2c9",
};
