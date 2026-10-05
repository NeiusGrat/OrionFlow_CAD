/** Two revisions side by side: characteristics added, removed and changed, marked on both sheets. */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AppBar } from "../../components/Inspect/common";
import DrawingView, { type Mark } from "../../components/Inspect/DrawingView";
import { limits, short } from "../../lib/inspect";
import { compareRevisions, getProject, type Comparison, type Project } from "../../services/faiApi";
import "../../styles/inspect.css";

const WORD = { added: "added", removed: "removed", changed: "changed", same: "same" } as const;

export default function ComparePage() {
    const { pid = "" } = useParams();
    const [q] = useSearchParams();
    const a = q.get("a") ?? "";
    const b = q.get("b") ?? "";
    const [cmp, setCmp] = useState<Comparison | null>(null);
    const [project, setProject] = useState<Project | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [showSame, setShowSame] = useState(false);

    useEffect(() => {
        document.title = "Compare revisions — OrionFlow Inspect";
        compareRevisions(a, b).then(setCmp).catch((e) => setError(e.message));
        getProject(pid).then(setProject).catch(() => undefined);
    }, [a, b, pid]);

    const marks = useMemo(() => {
        const old: Mark[] = [];
        const neu: Mark[] = [];
        for (const r of cmp?.rows ?? []) {
            if (r.status === "same") continue;
            if (r.old) old.push({ page: r.old.page, bbox: r.old.bbox, label: WORD[r.status], kind: r.status });
            if (r.new) neu.push({ page: r.new.page, bbox: r.new.bbox, label: `${WORD[r.status]} #${r.new.no}`, kind: r.status });
        }
        return { old, neu };
    }, [cmp]);

    const crumbs = <><Link to={`/p/${pid}`}>{project?.part_number || "Project"}</Link><span className="sep">/</span>
        <b>Compare rev {cmp?.a.label || "…"} to rev {cmp?.b.label || "…"}</b></>;

    return (
        <div className="in">
            <AppBar crumbs={crumbs} />
            <main className="in-page" style={{ maxWidth: 1500 }}>
                {error && <div className="in-error">{error}</div>}
                {!cmp ? <p className="sub">Comparing…</p> : (
                    <>
                        <div className="in-head">
                            <div>
                                <h1>Rev {cmp.a.label} to rev {cmp.b.label}</h1>
                                <p>{cmp.same_drawing ? "The two revisions use the identical drawing file." :
                                    `${cmp.counts.changed} changed, ${cmp.counts.added} added, ${cmp.counts.removed} removed, ${cmp.counts.same} unchanged.`}
                                    {" "}Matched by what each characteristic is, not by balloon number.</p>
                            </div>
                            <div className="actions">
                                <Link className="in-btn line" to={`/r/${cmp.b.id}`}>Open rev {cmp.b.label}</Link>
                            </div>
                        </div>
                        <div className="in-compare" style={{ marginBottom: 24 }}>
                            <div>
                                <h3>Rev {cmp.a.label} <span className="mute mono" style={{ fontWeight: 400 }}>sha256 {short(cmp.a.drawing_sha)}</span></h3>
                                <div style={{ position: "relative", height: "62vh", background: "#f5f5f5" }}>
                                    <DrawingView rid={cmp.a.id} pages={cmp.a.pages} marks={marks.old} zoom={1} />
                                </div>
                            </div>
                            <div>
                                <h3>Rev {cmp.b.label} <span className="mute mono" style={{ fontWeight: 400 }}>sha256 {short(cmp.b.drawing_sha)}</span></h3>
                                <div style={{ position: "relative", height: "62vh", background: "#f5f5f5" }}>
                                    <DrawingView rid={cmp.b.id} pages={cmp.b.pages} marks={marks.neu} zoom={1} />
                                </div>
                            </div>
                        </div>
                        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12, marginBottom: 8 }}>
                            <input type="checkbox" checked={showSame} onChange={(e) => setShowSame(e.target.checked)} /> Show unchanged characteristics
                        </label>
                        <table className="in-table">
                            <thead><tr><th>Change</th><th>Rev {cmp.a.label}</th><th>Limits</th><th>Rev {cmp.b.label}</th><th>Limits</th><th>What changed</th></tr></thead>
                            <tbody>
                                {cmp.rows.filter((r) => showSame || r.status !== "same").map((r, i) => (
                                    <tr key={i}>
                                        <td><span className={`in-chg ${r.status}`}>{WORD[r.status]}</span></td>
                                        <td>{r.old ? <><span className="mono">#{r.old.no}</span> {r.old.designator}</> : <span className="mute">—</span>}</td>
                                        <td className="mono">{r.old ? limits(r.old) : ""}</td>
                                        <td>{r.new ? <><span className="mono">#{r.new.no}</span> {r.new.designator}</> : <span className="mute">—</span>}</td>
                                        <td className="mono">{r.new ? limits(r.new) : ""}</td>
                                        <td className="sub">{r.what}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </>
                )}
            </main>
        </div>
    );
}
