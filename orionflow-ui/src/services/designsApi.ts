/**
 * Designs API — the user's saved parts.
 *
 * The backend CRUD (app/api/v1/designs.py) has existed for a long time and
 * nothing called it, so a browser refresh threw away the session. This is the
 * client that makes saved work actually saved.
 *
 * The part's Blueprint is stored in `feature_graph`: it is the parametric
 * source of truth, so a saved design can be rebuilt or re-verified later,
 * whereas the STEP/STL are only a snapshot of one resolution of it.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function authHeaders(): Record<string, string> {
    try {
        const token = JSON.parse(localStorage.getItem('orionflow-auth') || '{}')
            ?.state?.accessToken;
        return token ? { Authorization: `Bearer ${token}` } : {};
    } catch {
        return {};
    }
}

function jsonHeaders(): Record<string, string> {
    return { 'Content-Type': 'application/json', ...authHeaders() };
}

export interface SavedDesign {
    id: string;
    name: string;
    description: string | null;
    original_prompt: string;
    feature_graph: Record<string, unknown>;
    glb_path: string | null;
    step_path: string | null;
    stl_path: string | null;
    is_public: boolean;
    tags: string[];
    created_at: string;
    updated_at: string;
}

export interface DesignListResponse {
    items: SavedDesign[];
    total: number;
    page: number;
    per_page: number;
    pages: number;
}

async function handle<T>(res: Response, what: string): Promise<T> {
    if (!res.ok) {
        let detail = res.statusText;
        try {
            const body = await res.json();
            if (typeof body.detail === 'string') detail = body.detail;
        } catch {
            /* non-JSON error body; status text stands */
        }
        throw new Error(`${what} failed: ${detail}`);
    }
    return res.json() as Promise<T>;
}

export async function listDesigns(page = 1, perPage = 50): Promise<DesignListResponse> {
    const res = await fetch(
        `${API_BASE}/api/v1/designs?page=${page}&per_page=${perPage}`,
        { headers: authHeaders() }
    );
    return handle<DesignListResponse>(res, 'Loading designs');
}

export interface CreateDesignInput {
    name: string;
    prompt: string;
    feature_graph: Record<string, unknown>;
    description?: string;
    glb_path?: string;
    step_path?: string;
    stl_path?: string;
}

export async function createDesign(input: CreateDesignInput): Promise<SavedDesign> {
    const res = await fetch(`${API_BASE}/api/v1/designs`, {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify(input),
    });
    return handle<SavedDesign>(res, 'Saving the design');
}

export async function updateDesign(
    id: string,
    patch: Partial<Pick<SavedDesign, 'name' | 'description' | 'is_public' | 'tags'>> & {
        feature_graph?: Record<string, unknown>;
    }
): Promise<SavedDesign> {
    const res = await fetch(`${API_BASE}/api/v1/designs/${id}`, {
        method: 'PATCH',
        headers: jsonHeaders(),
        body: JSON.stringify(patch),
    });
    return handle<SavedDesign>(res, 'Updating the design');
}

export async function deleteDesign(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/v1/designs/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
    });
    await handle<{ message: string }>(res, 'Deleting the design');
}
