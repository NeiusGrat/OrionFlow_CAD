/** Projects: every part under inspection, its latest revision and where it stands. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppBar, NewInspection } from "../../components/Inspect/common";
import { usePoll } from "../../lib/watchdog";
import { revStatus, when } from "../../lib/inspect";
import { createSample, listProjects, type Project } from "../../services/faiApi";
import "../../styles/inspect.css";

export default function InspectHome() {
    const navigate = useNavigate();
    const [projects, setProjects] = useState<Project[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [creating, setCreating] = useState(false);
    const [sampling, setSampling] = useState(false);

    const load = useCallback(() => listProjects().then(setProjects).catch((e) => setError(e.message)), []);
    useEffect(() => { document.title = "Projects — OrionFlow Inspect"; load(); }, [load]);
    usePoll(load, 3000, !!projects?.some((p) => p.latest && ["queued", "running"].includes(p.latest.status)));

    async function sample() {
        setSampling(true);
        setError(null);
        try {
            const p = await createSample();
            navigate(`/p/${p.id}`);
        } catch (e) {
            setError((e as Error).message);
            setSampling(false);
        }
    }

    return (
        <div className="in">
            <AppBar right={<button className="in-btn" onClick={() => setCreating(true)}>New inspection</button>} />
            <main className="in-page">
                <div className="in-head">
                    <div>
                        <h1>Projects</h1>
                        <p>Each part you inspect, with its revisions. Upload a drawing to get ballooned characteristics,
                            a drawing-to-model cross-check and an AS9102 draft ready for review.</p>
                    </div>
                    <div className="actions">
                        <button className="in-btn line" onClick={sample} disabled={sampling}>{sampling ? "Building sample…" : "Load sample project"}</button>
                    </div>
                </div>
                {error && <div className="in-error">{error}</div>}
                {projects === null ? <p className="sub">Loading…</p> : projects.length === 0 ? (
                    <div className="in-empty">
                        <h2>No inspections yet</h2>
                        <p>Start with the customer's drawing PDF. Add the STEP model and the PO line if you have them;
                            every value on the drawing is then checked against both.</p>
                        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                            <button className="in-btn" onClick={() => setCreating(true)}>New inspection</button>
                            <button className="in-btn line" onClick={sample} disabled={sampling}>{sampling ? "Building sample…" : "Load sample project"}</button>
                        </div>
                    </div>
                ) : (
                    <table className="in-table">
                        <thead>
                            <tr><th>Part number</th><th>Name</th><th>Customer</th><th>Rev</th><th>Status</th>
                                <th className="num">Critical</th><th className="num">Characteristics</th><th>Last run</th></tr>
                        </thead>
                        <tbody>
                            {projects.map((p) => {
                                const r = p.latest;
                                const st = revStatus(r);
                                return (
                                    <tr key={p.id} className="link" tabIndex={0}
                                        onClick={() => navigate(r && r.status !== "error" ? `/r/${r.id}` : `/p/${p.id}`)}
                                        onKeyDown={(e) => e.key === "Enter" && navigate(`/p/${p.id}`)}>
                                        <td className="mono"><b>{p.part_number || "—"}</b></td>
                                        <td>{p.part_name || <span className="mute">—</span>}</td>
                                        <td>{p.customer || <span className="mute">—</span>}</td>
                                        <td className="mono">{r?.label || "—"}</td>
                                        <td><span className={`in-status ${st.cls}`}>{st.word}</span></td>
                                        <td className="num">{r?.result?.stats?.findings?.critical ?? ""}</td>
                                        <td className="num">{r?.result?.stats?.characteristics ?? ""}</td>
                                        <td className="mute">{when(r?.finished ?? r?.created ?? p.created)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </main>
            {creating && <NewInspection onClose={() => setCreating(false)} />}
        </div>
    );
}
