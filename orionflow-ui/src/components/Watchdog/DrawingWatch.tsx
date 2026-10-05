/**
 * Drawing watch: a customer's PDF drawing in, the questions to send back
 * before quoting or machining out — each one boxed on the sheet it is about.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Play, Trash2 } from "lucide-react";
import { DropSlot } from "./parts";
import { SEV_COLOR, ago, useBlobUrl, usePoll } from "../../lib/watchdog";
import {
    createDrawingRun,
    decideDrawingFinding,
    deleteDrawingRun,
    download,
    getDrawingRun,
    listDrawingRuns,
    type DrawingFinding,
    type DrawingRun,
} from "../../services/watchdogApi";

const SEV_WORD = { error: "Must answer", warning: "Should answer", info: "Note" } as const;
const ORDER = { error: 0, warning: 1, info: 2 } as const;

function lampFor(r: DrawingRun) {
    if (r.status === "queued" || r.status === "running") return "busy";
    if (r.status === "error") return "failed";
    if (r.errors) return "high";
    if (r.warnings) return "medium";
    return "clear";
}

function Page({ run, index, findings, active, onPick }: {
    run: DrawingRun; index: number; findings: DrawingFinding[]; active: string | null; onPick: (id: string) => void;
}) {
    const img = useBlobUrl(`/drawing/api/runs/${run.id}/pages/${index}.png?dpi=130`, "Loading the sheet");
    const pg = run.pages?.[index];
    return (
        <div className="wd-page" style={{ width: "min(100%, 1100px)" }}>
            {img.url ? <img src={img.url} alt={`Sheet ${index + 1} of ${run.filename}`} /> :
                <div style={{ padding: 40, color: "#567" }}>{img.error ?? "Loading sheet…"}</div>}
            {img.url && pg && findings.filter((f) => f.page === index && f.bbox).map((f) => {
                const [x0, y0, x1, y1] = f.bbox!;
                const pad = 3;
                return (
                    <div key={f.id} className={`wd-box ${f.severity}${active === f.id ? " active" : ""}`} title={f.title}
                         onClick={() => onPick(f.id)}
                         style={{ left: `${((x0 - pad) / pg.w) * 100}%`, top: `${((y0 - pad) / pg.h) * 100}%`,
                                  width: `${((x1 - x0 + 2 * pad) / pg.w) * 100}%`, height: `${((y1 - y0 + 2 * pad) / pg.h) * 100}%` }} />
                );
            })}
        </div>
    );
}

export default function DrawingWatch({ available, reason }: { available: boolean; reason: string | null }) {
    const [runs, setRuns] = useState<DrawingRun[]>([]);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [run, setRun] = useState<DrawingRun | null>(null);
    const [file, setFile] = useState<File[]>([]);
    const [customer, setCustomer] = useState("");
    const [vision, setVision] = useState<"off" | "scanned" | "all">("scanned");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);

    const refresh = useCallback(() => listDrawingRuns().then(setRuns).catch((e) => setError(e.message)), []);
    useEffect(() => { if (available) refresh(); }, [available, refresh]);
    useEffect(() => { if (!activeId && runs.length) setActiveId(runs[0].id); }, [runs, activeId]);

    const load = useCallback(async (id: string) => {
        const r = await getDrawingRun(id);
        setRun(r);
        setRuns((l) => l.map((x) => (x.id === id ? { ...x, ...r, report: undefined } : x)));
    }, []);
    useEffect(() => { setRun(null); setOpenId(null); if (activeId) load(activeId).catch((e) => setError(e.message)); }, [activeId, load]);
    const busyRun = !!run && (run.status === "queued" || run.status === "running");
    usePoll(() => activeId && load(activeId).catch(() => undefined), 2000, busyRun);

    const findings = useMemo(
        () => [...(run?.report?.findings ?? [])].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]),
        [run?.report?.findings],
    );
    const worstByPage = useMemo(() => {
        const m = new Map<number, string>();
        for (const f of findings) if (f.page != null && !m.has(f.page)) m.set(f.page, f.severity);
        return m;
    }, [findings]);

    async function start() {
        if (!file[0]) return;
        setBusy(true);
        setError(null);
        try {
            const r = await createDrawingRun(file[0], customer, vision);
            setFile([]);
            await refresh();
            setActiveId(r.id);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }

    async function decide(f: DrawingFinding, decision: "" | "accepted" | "rejected") {
        if (!run) return;
        try {
            await decideDrawingFinding(run.id, f.id, decision);
            await load(run.id);
        } catch (e) {
            setError((e as Error).message);
        }
    }

    if (!available) {
        return <div className="wd-view-empty" style={{ position: "relative", gridRow: "2 / 4" }}><h2>The drawing checker is not running on this server</h2><p>{reason}</p></div>;
    }

    const pages = run?.pages ?? [];
    return (
        <>
            <div className="wd-stages" style={{ gridTemplateColumns: `repeat(${Math.max(pages.length, 1)}, minmax(0, 160px))` }}
                 role="list" aria-label="Sheets">
                {pages.length ? pages.map((p, i) => {
                    const worst = worstByPage.get(i);
                    const s = worst === "error" ? "FAIL" : worst === "warning" ? "WARNING" : run?.status === "done" ? "PASS" : "RUNNING";
                    return (
                        <div key={i} className="wd-stage" data-s={s} role="listitem" title={`Sheet ${i + 1}: ${p.layer} layer`}>
                            <div className="bar" />
                            <div className="name"><b>{String(i + 1).padStart(2, "0")}</b>{p.layer} sheet</div>
                        </div>
                    );
                }) : (
                    <div className="wd-stage" data-s={busyRun ? "RUNNING" : ""}><div className="bar" /><div className="name">{busyRun ? "Reading the drawing" : "No drawing open"}</div></div>
                )}
            </div>
            <div className="wd-body">
                <aside className="wd-col left">
                    <div className="wd-scroll">
                        <div className="wd-section">
                            <h3 className="wd-h">Check a drawing</h3>
                            <DropSlot label="Drawing PDF" accept=".pdf" files={file} required onFiles={setFile} />
                            <input className="wd-input" placeholder="Customer (optional)" value={customer} onChange={(e) => setCustomer(e.target.value)} />
                            <div className="wd-p" style={{ fontSize: 12, marginBottom: 6 }}>Read with vision</div>
                            <div className="wd-seg">
                                {([["off", "Never"], ["scanned", "Scanned sheets"], ["all", "Every sheet"]] as const).map(([k, t]) => (
                                    <button key={k} aria-pressed={vision === k} onClick={() => setVision(k)}>{t}</button>
                                ))}
                            </div>
                            <button className="wd-btn block" disabled={!file.length || busy} onClick={start}>
                                <Play size={15} /> {busy ? "Uploading…" : "Check drawing"}
                            </button>
                            {error && <div className="wd-error">{error}</div>}
                        </div>
                        <div className="wd-section" style={{ borderBottom: 0, paddingBottom: 6 }}>
                            <h3 className="wd-h" style={{ margin: 0 }}>History <span className="count">{runs.length}</span></h3>
                        </div>
                        {runs.map((r) => (
                            <button key={r.id} className="wd-run" aria-current={r.id === activeId} onClick={() => setActiveId(r.id)}>
                                <span className={`lamp ${lampFor(r)}`} />
                                <span className="t"><b>{r.drawing_number || r.filename}</b><small>{r.customer ? `${r.customer}, ` : ""}{r.status === "done" ? ago(r.created) : r.status}</small></span>
                                <span className="tally">
                                    {!!r.errors && <span className="wd-tally-high">{r.errors}</span>}
                                    {!!r.warnings && <span className="wd-tally-medium">{r.warnings}</span>}
                                </span>
                            </button>
                        ))}
                        {!runs.length && <div className="wd-empty-note">Checked drawings will be listed here.</div>}
                    </div>
                </aside>

                <section className="wd-centre">
                    <div className="wd-view">
                        {run && run.status === "done" && pages.length ? (
                            <div className="wd-pages">
                                {pages.map((_, i) => <Page key={i} run={run} index={i} findings={findings} active={openId} onPick={setOpenId} />)}
                            </div>
                        ) : (
                            <div className="wd-view-empty">
                                {run?.status === "error" ? (<><h2>This drawing could not be read</h2><p>{run.error}</p></>) :
                                 busyRun ? (<><h2>Reading {run!.filename}</h2><p>Text layer first, vision only where the sheet has no text. Rules decide; the reader never does.</p></>) :
                                 (<><h2>Check a customer drawing before you quote it</h2><p>Every missing tolerance, unclear datum and stale revision becomes a question you can send back.</p></>)}
                            </div>
                        )}
                        {run?.status === "done" && (
                            <div className="wd-hud">
                                <span className="wd-chip"><b>{run.drawing_number || run.filename}</b></span>
                                {run.report?.title?.revision && <span className="wd-chip">Rev <b>{run.report.title.revision}</b></span>}
                                {run.report?.title?.material && <span className="wd-chip"><b>{run.report.title.material}</b></span>}
                                <span style={{ flex: 1 }} />
                                <button className="wd-btn ghost small" onClick={() => download(`/drawing/api/runs/${run.id}/files/queries.xlsx`, `${run.filename}.queries.xlsx`)}><Download size={13} /> Query list</button>
                                <button className="wd-btn ghost small" onClick={() => download(`/drawing/api/runs/${run.id}/files/checked.pdf`, `${run.filename}.checked.pdf`)}><Download size={13} /> Marked-up PDF</button>
                                <button className="wd-btn ghost small" aria-label="Delete this drawing" onClick={async () => { await deleteDrawingRun(run.id); setActiveId(null); refresh(); }}><Trash2 size={13} /></button>
                            </div>
                        )}
                    </div>
                </section>

                <aside className="wd-col right">
                    <div className="wd-summary" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                        {(["error", "warning", "info"] as const).map((k) => {
                            const n = findings.filter((f) => f.severity === k).length;
                            return <div key={k} className={`wd-sev ${k === "error" ? "high" : k === "warning" ? "medium" : "info"}${n ? "" : " zero"}`}><b>{n}</b><span>{SEV_WORD[k]}</span></div>;
                        })}
                    </div>
                    <div className="wd-scroll">
                        {(run?.report?.reader_warnings ?? []).length > 0 && (
                            <div className="wd-narr"><ul>{run!.report!.reader_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
                        )}
                        {findings.map((f) => (
                            <div key={f.id} className="wd-finding" aria-expanded={openId === f.id}>
                                <button onClick={() => setOpenId(openId === f.id ? null : f.id)}>
                                    <span className="rail" style={{ background: SEV_COLOR[f.severity] }} />
                                    <span>
                                        <span className="rule">
                                            <strong>{f.title}</strong>
                                            {f.page != null && <span className="wd-tag">sheet {f.page + 1}</span>}
                                            {f.decision && <span className={`wd-tag ${f.decision}`}>{f.decision === "accepted" ? "will ask" : "dismissed"}</span>}
                                        </span>
                                        <span className="msg">{f.message}</span>
                                    </span>
                                </button>
                                {openId === f.id && (
                                    <div className="wd-detail">
                                        <dl className="wd-kv">
                                            <dt>Question</dt><dd style={{ fontFamily: "var(--wd-sans)" }}>{f.query}</dd>
                                            {f.evidence && <><dt>On the sheet</dt><dd>{f.evidence}</dd></>}
                                            <dt>Rule</dt><dd>{f.rule}</dd>
                                            <dt>Read by</dt><dd>{f.confidence}</dd>
                                        </dl>
                                        <div className="wd-actions">
                                            <button className="wd-btn small" onClick={() => decide(f, "accepted")}>Ask the customer</button>
                                            <button className="wd-btn ghost small" onClick={() => decide(f, "rejected")}>Dismiss</button>
                                            {f.decision && <button className="wd-btn ghost small" onClick={() => decide(f, "")}>Undo</button>}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                        {run?.status === "done" && !findings.length && <div className="wd-empty-note">No questions for this drawing.</div>}
                        {!run && <div className="wd-empty-note">Questions appear here, the ones you must ask first.</div>}
                    </div>
                </aside>
            </div>
        </>
    );
}
