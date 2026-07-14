/**
 * Client for the local OrionFlow FreeCAD bridge (orion_agent addon).
 *
 * The addon runs an HTTP RPC server on 127.0.0.1:8765 inside FreeCAD.
 * Because it is localhost, browsers exempt it from mixed-content blocking,
 * so the hosted studio at https://app.orionflow.in can talk to it directly.
 */

const BRIDGE_URL = "http://127.0.0.1:8765";

interface BridgeResponse {
    ok: boolean;
    result: unknown;
    error_code?: string;
    error_message?: string;
}

/** True if FreeCAD is running with the OrionFlow addon bridge started. */
export async function bridgeAvailable(timeoutMs = 1500): Promise<boolean> {
    try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), timeoutMs);
        const res = await fetch(`${BRIDGE_URL}/health`, { signal: ctrl.signal });
        clearTimeout(t);
        return res.ok;
    } catch {
        return false;
    }
}

async function callBridge(capability: string, params: Record<string, unknown>): Promise<BridgeResponse> {
    const res = await fetch(BRIDGE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            capability,
            params,
            request_id: crypto.randomUUID(),
        }),
    });
    return res.json();
}

export type FreeCADOpenResult =
    | { status: "opened" }
    | { status: "bridge_down" }
    | { status: "error"; message: string };

/**
 * Send the current part's STEP file to a locally running FreeCAD.
 * The addon downloads the URL itself (it validates https/localhost sources).
 */
export async function openInFreeCAD(stepUrl: string, label: string): Promise<FreeCADOpenResult> {
    if (!(await bridgeAvailable())) return { status: "bridge_down" };
    try {
        const resp = await callBridge("import_shape", {
            url: stepUrl,
            label: label.slice(0, 60) || "OrionFlow part",
        });
        if (resp.ok) return { status: "opened" };
        return { status: "error", message: resp.error_message || "FreeCAD rejected the import" };
    } catch (e: any) {
        return { status: "error", message: e?.message || "bridge call failed" };
    }
}
