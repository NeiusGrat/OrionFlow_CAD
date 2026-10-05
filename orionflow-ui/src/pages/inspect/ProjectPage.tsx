/** One part: its revisions as a timeline, the record of every decision, and compare. */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AppBar, NewInspection } from "../../components/Inspect/common";
import { usePoll } from "../../lib/watchdog";
import { ACTION_WORD, revStatus, short, when } from "../../lib/inspect";
import { deleteProject, getProject, updateProject, type Event, type Project, type Revision } from "../../services/faiApi";
import "../../styles/inspect.css";

type Full = Project & { revisions: Revision[]; events: Event[] };

function describe(e: Event): string {
    const d = e.detail as Record<string, unknown>;
    switch (e.action) {
        case "characteristic_edited": {
            const after = d.after as Record<string, unknown> | undefined;
            return `${e.target}: ${Object.entries(after ?? {}).map(([k, v]) => `${k} = ${v === "" ? "—" : v}`).join(", ")}`;
        }
        case "finding_decided":
            return `${d.title}: ${d.after || "reopened"}${d.note ? ` (“${d.note}”)` : ""}${d.standing_for_customer ? `, standing for ${d.standing_for_customer}` : ""}`;
        case "revision_uploaded":
            return [d.drawing, d.step, d.bom].filter(Boolean).join(", ");
        case "revision_checked": {
            const s = d.stats as { characteristics?: number; findings?: Record<string, number> } | undefined;
            return s ? `${s.characteristics} characteristics, ${s.findings?.critical ?? 0} critical, ${s.findings?.major ?? 0} major` : "";
        }
        case "revision_signed":
            return `${d.name} (${d.role}), ${d.fai_scope}`;
        case "form1_updated":
            return Object.entries(d).map(([k, v]) => `${k.replace(/_/g, " ")} = ${v}`).join(", ");
        default:
            return e.target || "";
    }
}

export default function ProjectPage() {
    const { pid = "" } = useParams();
    const navigate = useNavigate();
    const [p, setP] = useState<Full | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [adding, setAdding] = useState(false);
    const [editing, setEditing] = useState(false);
    const [form, setForm] = useState({ part_number: "", part_name: "", customer: "" });
    const [cmpA, setCmpA] = useState("");
    const [cmpB, setCmpB] = useState("");

    const load = useCallback(() => getProject(pid).then((x) => {
        setP(x);
        document.title = `${x.part_number || "Project"} — OrionFlow Inspect`;
    }).catch((e) => setError(e.message)), [pid]);
    useEffect(() => { load(); }, [load]);
    usePoll(load, 2500, !!p?.revisions.some((r) => ["queued", "running"].includes(r.status)));
    useEffect(() => {
        if (!p) return;
        const done = p.revisions.filter((r) => r.status === "done" || r.status === "signed");
        if (done.length >= 2 && !cmpA) { setCmpB(done[0].id); setCmpA(done[1].id); }
    }, [p, cmpA]);

    if (error) return <div className="in"><AppBar /><main className="in-page"><div className="in-error">{error}</div></main></div>;
    if (!p) return <div className="in"><AppBar /><main className="in-page"><p className="sub">Loading…</p></main></div>;

    const done = p.revisions.filter((r) => r.status === "done" || r.status === "signed");
    return (
        <div className="in">
            <AppBar crumbs={<b>{p.part_number || "Untitled part"}</b>}
                    right={<button className="in-btn" onClick={() => setAdding(true)}>New revision</button>} />
            <main className="in-page">
                <div className="in-head">
                    {editing ? (
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, width: "100%", alignItems: "end" }}>
                            <label className="in-field"><span>Part number</span><input className="in-input" value={form.part_number} onChange={(e) => setForm({ ...form, part_number: e.target.value })} /></label>
                            <label className="in-field"><span>Name</span><input className="in-input" value={form.part_name} onChange={(e) => setForm({ ...form, part_name: e.target.value })} /></label>
                            <label className="in-field"><span>Customer</span><input className="in-input" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })} /></label>
                            <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
                                <button className="in-btn" onClick={async () => { await updateProject(pid, form); setEditing(false); load(); }}>Save</button>
                                <button className="in-btn line" onClick={() => setEditing(false)}>Cancel</button>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div>
                                <h1 className="mono">{p.part_number || "Untitled part"}</h1>
                                <p>{p.part_name || "No name"}{p.customer ? ` for ${p.customer}` : ""}</p>
                            </div>
                            <div className="actions">
                                <button className="in-btn line" onClick={() => { setForm({ part_number: p.part_number, part_name: p.part_name, customer: p.customer }); setEditing(true); }}>Edit details</button>
                                <button className="in-btn quiet" onClick={async () => {
                                    if (!window.confirm(`Delete ${p.part_number || "this project"} and all its revisions?`)) return;
                                    await deleteProject(pid); navigate("/");
                                }}>Delete</button>
                            </div>
                        </>
                    )}
                </div>

                <div className="in-grid2">
                    <section>
                        <h2 className="in-section-h">Revisions <span className="mute mono">{p.revisions.length}</span></h2>
                        {p.revisions.length === 0 ? (
                            <div className="in-empty"><p>No revisions yet.</p><button className="in-btn" onClick={() => setAdding(true)}>Upload the drawing</button></div>
                        ) : (
                            <ol className="in-timeline">
                                {p.revisions.map((r) => {
                                    const st = revStatus(r);
                                    return (
                                        <li key={r.id} className={`in-tl${r.signoff ? " signed" : ""}`}>
                                            <h3>
                                                <Link to={`/r/${r.id}`}>Rev {r.label || "—"}</Link>
                                                <span className={`in-status ${st.cls}`}>{st.word}</span>
                                                {r.drawing_changed === true && <span className="in-badge">drawing updated</span>}
                                                {r.drawing_changed === false && <span className="in-badge faint">same drawing</span>}
                                            </h3>
                                            <p>{when(r.created)}{r.signoff ? `, signed by ${r.signoff.name} ${r.signoff.at}` : ""}</p>
                                            <p className="mono" style={{ fontSize: 11 }}>
                                                {r.drawing_name} <span className="mute">sha256 {short(r.drawing_sha)}</span>
                                                {r.step_name && <><br />{r.step_name} <span className="mute">sha256 {short(r.step_sha)}</span></>}
                                                {r.bom_name && <><br />{r.bom_name} <span className="mute">sha256 {short(r.bom_sha)}</span></>}
                                            </p>
                                            {r.error && <p>■ {r.error}</p>}
                                        </li>
                                    );
                                })}
                            </ol>
                        )}
                        {done.length >= 2 && (
                            <div style={{ border: "1px solid #000", padding: 14, marginTop: 6 }}>
                                <h3 className="in-side-h">Compare revisions</h3>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr auto", gap: 8, alignItems: "center" }}>
                                    <select className="in-select" value={cmpA} onChange={(e) => setCmpA(e.target.value)} aria-label="Older revision">
                                        {done.map((r) => <option key={r.id} value={r.id}>Rev {r.label} ({when(r.created)})</option>)}
                                    </select>
                                    <span className="mute">to</span>
                                    <select className="in-select" value={cmpB} onChange={(e) => setCmpB(e.target.value)} aria-label="Newer revision">
                                        {done.map((r) => <option key={r.id} value={r.id}>Rev {r.label} ({when(r.created)})</option>)}
                                    </select>
                                    <button className="in-btn" disabled={!cmpA || !cmpB || cmpA === cmpB} onClick={() => navigate(`/compare/${pid}?a=${cmpA}&b=${cmpB}`)}>Compare</button>
                                </div>
                            </div>
                        )}
                    </section>

                    <section>
                        <h2 className="in-section-h">Audit trail <span className="mute mono">{p.events.length}</span></h2>
                        <table className="in-table">
                            <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
                            <tbody>
                                {p.events.map((e) => (
                                    <tr key={e.id}>
                                        <td className="mono mute" style={{ whiteSpace: "nowrap" }}>{when(e.at)}</td>
                                        <td style={{ whiteSpace: "nowrap" }}>{e.actor || "—"}</td>
                                        <td><b style={{ fontWeight: 500 }}>{ACTION_WORD[e.action] ?? e.action}</b>
                                            <div className="sub" style={{ fontSize: 12 }}>{describe(e)}</div></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                </div>
            </main>
            {adding && <NewInspection projectId={pid} onClose={() => setAdding(false)} />}
        </div>
    );
}
