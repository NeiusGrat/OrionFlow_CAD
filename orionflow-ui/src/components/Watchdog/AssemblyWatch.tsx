/**
 * Assembly watch: STEP + BOM + previous revision + URDF + drawings in, every
 * disagreement between them out, each one pointing at the parts it is about.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, FlaskConical, Play, Square, Trash2 } from "lucide-react";
import ModelView, { type ModelFocus } from "./ModelView";
import { DropSlot, StageLine } from "./parts";
import { SEV_COLOR, ago, nodeKey, show, useBlobUrl, usePoll } from "../../lib/watchdog";
import {
    ASSEMBLY_KINDS,
    cancelAnalysis,
    createAnalysis,
    deleteAnalysis,
    download,
    getAnalysis,
    listAnalyses,
    listSamples,
    reviewFinding,
    runSample,
    type AnalysisJob,
    type AssemblyFinding,
    type AssemblyKind,
    type AssemblyReport,
    type Sample,
    type Severity,
} from "../../services/watchdogApi";
import { authedFetch } from "../../services/http";
import { VERIFY } from "../../services/watchdogApi";
import { CAD_COMPONENT_TINTS as TINTS } from "../../lib/cadAppearance";

const PRIMARY: AssemblyKind[] = ["step", "bom", "prev_step", "urdf"];
const EXTRA: AssemblyKind[] = ["prev_bom", "urdf_map", "drawing", "datasheet", "vendor_step"];
const SEVS: Severity[] = ["high", "medium", "low", "info"];
const SEV_WORD: Record<Severity, string> = { high: "High", medium: "Medium", low: "Low", info: "Info" };

const RULE_WORD: Record<string, string> = {
    HOLE_MISALIGNED: "Holes don't line up", HOLE_MISSING: "Mating hole missing", PATTERN_MISMATCH: "Bolt pattern differs",
    FASTENER_SIZE_MISMATCH: "Fastener sizes disagree", BEARING_SEAT: "Bearing seat out of fit", MOTOR_FLANGE: "Motor flange mismatch",
    INTERFERENCE: "Parts interfere", BOM_QTY_MISMATCH: "BOM quantity differs from CAD", IN_CAD_NOT_BOM: "In CAD, not in BOM",
    IN_BOM_NOT_CAD: "In BOM, not in CAD", LOW_CONFIDENCE_MATCH: "Uncertain BOM match", DRAWING_STALE: "Drawing older than the part",
    DRAWING_REV_MISMATCH: "Drawing revision differs", DRAWING_UNMATCHED: "Drawing matches no part",
    DATASHEET_NEEDS_REVIEW: "Datasheet values need review", URDF_MASS_DRIFT: "Robot model mass drifted from CAD",
    URDF_COM_DRIFT: "Robot model centre of mass drifted", JOINT_AXIS_DRIFT: "Joint axis drifted from CAD",
    JOINT_ORIGIN_DRIFT: "Joint origin drifted from CAD", URDF_LINK_UNMAPPED: "Robot link not mapped to CAD",
    URDF_MESH_MISSING: "Robot mesh missing", PART_INVALID: "Invalid solid", UNSUPPORTED_GEOMETRY: "Mesh body, partly checked",
    ASSEMBLY_STRUCTURE_MISSING: "No assembly structure", COMPONENT_UNCONFIRMED: "Component not confirmed",
};

function lampFor(j: AnalysisJob): string {
    if (!j.terminal) return "busy";
    if (j.state !== "SUCCEEDED") return "failed";
    if (j.summary?.high) return "high";
    if (j.summary?.medium) return "medium";
    return "clear";
}

export default function AssemblyWatch({ available, reason }: { available: boolean; reason: string | null }) {
    const [jobs, setJobs] = useState<AnalysisJob[]>([]);
    const [samples, setSamples] = useState<Sample[]>([]);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [job, setJob] = useState<AnalysisJob | null>(null);
    const [report, setReport] = useState<(AssemblyReport & { instances?: { path: string; part: string }[] }) | null>(null);
    const [files, setFiles] = useState<Partial<Record<AssemblyKind, File[]>>>({});
    const [label, setLabel] = useState("");
    const [more, setMore] = useState(false);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [sevFilter, setSevFilter] = useState<Severity | null>(null);
    const [openFp, setOpenFp] = useState<string | null>(null);
    const [partFocus, setPartFocus] = useState<string | null>(null);
    const [picked, setPicked] = useState<string | null>(null);
    const [drawer, setDrawer] = useState<"changes" | "interfaces" | "bom" | "parts" | "assumptions">("changes");

    const refreshList = useCallback(() => {
        listAnalyses().then(setJobs).catch((e) => setError(e.message));
    }, []);

    useEffect(() => {
        if (!available) return;
        refreshList();
        listSamples().then(setSamples).catch(() => undefined);
    }, [available, refreshList]);

    // pick the newest run when nothing is selected
    useEffect(() => {
        if (!activeId && jobs.length) setActiveId(jobs[0].id);
    }, [jobs, activeId]);

    const loadJob = useCallback(async (id: string) => {
        const j = await getAnalysis(id);
        setJob((prev) => (prev && prev.id === id && JSON.stringify(prev) === JSON.stringify(j) ? prev : j));
        setJobs((list) => list.map((x) => (x.id === id ? { ...x, ...j } : x)));
        if (j.terminal && j.downloads?.includes("report.json")) {
            const res = await authedFetch(`${VERIFY}/api/analysis/${id}/files/report.json`);
            if (res.ok) setReport(await res.json());
        }
    }, []);

    useEffect(() => {
        setJob(null);
        setReport(null);
        setOpenFp(null);
        setPartFocus(null);
        setSevFilter(null);
        if (activeId) loadJob(activeId).catch((e) => setError(e.message));
    }, [activeId, loadJob]);

    usePoll(() => activeId && loadJob(activeId).catch(() => undefined), 1500, !!job && !job.terminal);
    usePoll(refreshList, 4000, jobs.some((j) => !j.terminal));

    const glbPath = job?.downloads?.includes("model.glb") ? `${VERIFY}/api/analysis/${job.id}/files/model.glb` : null;
    const glb = useBlobUrl(glbPath, "Loading the 3D model");

    const findings = useMemo(() => {
        const order = { high: 0, medium: 1, low: 2, info: 3 } as const;
        return [...(job?.findings ?? [])].sort((a, b) => order[a.severity] - order[b.severity]);
    }, [job?.findings]);
    const shown = sevFilter ? findings.filter((f) => f.severity === sevFilter) : findings;
    const open = findings.find((f) => f.fingerprint === openFp) ?? null;

    const partOf = useMemo(() => new Map((report?.instances ?? []).map((i) => [nodeKey(i.path), i.part])), [report]);
    const partNames = useMemo(() => [...new Set((report?.instances ?? []).map((i) => i.part))], [report]);

    const focus: ModelFocus | null = useMemo(() => {
        if (open) {
            const nodes = open.instances.length
                ? open.instances
                : (report?.instances ?? []).filter((i) => open.parts.includes(i.part)).map((i) => i.path);
            return { nodes, color: SEV_COLOR[open.severity], marker: open.location };
        }
        if (partFocus) {
            return { nodes: (report?.instances ?? []).filter((i) => i.part === partFocus).map((i) => i.path), color: "#ffffff" };
        }
        return null;
    }, [open, partFocus, report]);

    async function start() {
        setBusy("start");
        setError(null);
        try {
            const j = await createAnalysis(files, label);
            setFiles({});
            setLabel("");
            setJobs((l) => [j, ...l.filter((x) => x.id !== j.id)]);
            setActiveId(j.id);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(null);
        }
    }

    async function sample(id: string) {
        setBusy(`sample:${id}`);
        setError(null);
        try {
            const j = await runSample(id);
            setJobs((l) => [j, ...l.filter((x) => x.id !== j.id)]);
            setActiveId(j.id);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(null);
        }
    }

    async function review(f: AssemblyFinding, verdict: "real" | "not_issue" | "open") {
        if (!job) return;
        try {
            await reviewFinding(job.id, f.fingerprint, verdict);
            setJob({ ...job, findings: job.findings?.map((x) => (x.fingerprint === f.fingerprint ? { ...x, review: verdict } : x)) });
        } catch (e) {
            setError((e as Error).message);
        }
    }

    async function remove() {
        if (!job) return;
        await deleteAnalysis(job.id).catch((e) => setError(e.message));
        setActiveId(null);
        setJobs((l) => l.filter((x) => x.id !== job.id));
    }

    if (!available) {
        return (
            <>
                <StageLine />
                <div className="wd-view-empty" style={{ position: "relative" }}>
                    <h2>The assembly engine is not running on this server</h2>
                    <p>{reason}</p>
                </div>
            </>
        );
    }

    const s = job?.summary ?? {};
    const stats = (job?.stats ?? {}) as Record<string, unknown>;

    return (
        <>
            <StageLine stages={job?.stages} current={job?.stage} running={!!job && !job.terminal} />
            <div className="wd-body">
                {/* ---------------------------------------------------- left */}
                <aside className="wd-col left">
                    <div className="wd-scroll">
                        <div className="wd-section">
                            <h3 className="wd-h">New check</h3>
                            {PRIMARY.map((k) => (
                                <DropSlot key={k} {...ASSEMBLY_KINDS[k]} files={files[k] ?? []}
                                          required={"required" in ASSEMBLY_KINDS[k]}
                                          onFiles={(f) => setFiles((x) => ({ ...x, [k]: f }))} />
                            ))}
                            {more && EXTRA.map((k) => (
                                <DropSlot key={k} {...ASSEMBLY_KINDS[k]} files={files[k] ?? []}
                                          onFiles={(f) => setFiles((x) => ({ ...x, [k]: f }))} />
                            ))}
                            <button className="wd-more" onClick={() => setMore((m) => !m)}>
                                {more ? "Fewer inputs" : "Add drawings, datasheets, vendor parts"}
                            </button>
                            <input className="wd-input" placeholder="Name this check (optional)" value={label}
                                   onChange={(e) => setLabel(e.target.value)} style={{ marginTop: 8 }} />
                            <button className="wd-btn block" disabled={!files.step?.length || busy === "start"} onClick={start}>
                                <Play size={15} /> {busy === "start" ? "Uploading…" : "Run check"}
                            </button>
                            {error && <div className="wd-error">{error}</div>}
                        </div>

                        {samples.length > 0 && (
                            <div className="wd-section">
                                <h3 className="wd-h">No files to hand?</h3>
                                <p className="wd-p">Run a sample robot assembly with known problems seeded in.</p>
                                {samples.map((sm) => (
                                    <button key={sm.id} className="wd-drop" onClick={() => sample(sm.id)} disabled={!!busy}>
                                        <FlaskConical size={16} color="#6fb4ff" />
                                        <div className="k">
                                            <span>{sm.label.replace(/^Sample: /, "")}</span>
                                            <em>{busy === `sample:${sm.id}` ? "Building the assembly…" : sm.about}</em>
                                        </div>
                                    </button>
                                ))}
                            </div>
                        )}

                        <div>
                            <div className="wd-section" style={{ borderBottom: 0, paddingBottom: 6 }}>
                                <h3 className="wd-h" style={{ margin: 0 }}>History <span className="count">{jobs.length}</span></h3>
                            </div>
                            {jobs.map((j) => (
                                <button key={j.id} className="wd-run" aria-current={j.id === activeId} onClick={() => setActiveId(j.id)}>
                                    <span className={`lamp ${lampFor(j)}`} />
                                    <span className="t">
                                        <b>{j.label}</b>
                                        <small>{j.terminal ? (j.state === "SUCCEEDED" ? ago(j.finished_at ?? j.created_at) : j.state.toLowerCase().replace("_", " ")) : (j.stage ?? "queued").replace(/_/g, " ")}</small>
                                    </span>
                                    {j.summary && (
                                        <span className="tally">
                                            {!!j.summary.high && <span className="wd-tally-high">{j.summary.high}</span>}
                                            {!!j.summary.medium && <span className="wd-tally-medium">{j.summary.medium}</span>}
                                            {!!j.summary.low && <span className="wd-tally-low">{j.summary.low}</span>}
                                        </span>
                                    )}
                                </button>
                            ))}
                            {!jobs.length && <div className="wd-empty-note">Your checks will be listed here.</div>}
                        </div>
                    </div>
                </aside>

                {/* ---------------------------------------------------- centre */}
                <section className="wd-centre">
                    <div className="wd-view">
                        {glb.url ? (
                            <ModelView url={glb.url} focus={focus} selected={picked}
                                       onPick={(n) => { setPicked(n); setOpenFp(null); setPartFocus(n ? partOf.get(n) ?? null : null); }} />
                        ) : (
                            <div className="wd-view-empty">
                                {job && !job.terminal ? (
                                    <>
                                        <h2>Checking {job.label}</h2>
                                        <p>Now on {(job.stage ?? "the queue").replace(/_/g, " ")}. Geometry is measured first; nothing is judged by a language model.</p>
                                    </>
                                ) : job && job.state !== "SUCCEEDED" ? (
                                    <>
                                        <h2>This check did not finish</h2>
                                        <p>{job.error || job.failure_code || job.state}</p>
                                    </>
                                ) : job ? (
                                    <p>{glb.error ?? "Loading the 3D model…"}</p>
                                ) : (
                                    <>
                                        <h2>Does your CAD, BOM, drawing and robot model agree?</h2>
                                        <p>Drop an assembly STEP on the left — add the BOM, the previous revision and the URDF to check them against it — or run a sample.</p>
                                    </>
                                )}
                            </div>
                        )}
                        {job && (
                            <div className="wd-hud">
                                <span className="wd-chip"><b>{job.label}</b></span>
                                {stats.parts != null && <span className="wd-chip"><b>{show(stats.parts)}</b> parts</span>}
                                {stats.instances != null && <span className="wd-chip"><b>{show(stats.instances)}</b> instances</span>}
                                {stats.interfaces != null && <span className="wd-chip"><b>{show(stats.interfaces)}</b> interfaces</span>}
                                {stats.runtime_s != null && <span className="wd-chip"><b>{show(stats.runtime_s)}</b> s</span>}
                                <span style={{ flex: 1 }} />
                                {!job.terminal && (
                                    <button className="wd-btn ghost small" onClick={() => cancelAnalysis(job.id).then(() => loadJob(job.id))}>
                                        <Square size={12} /> Stop
                                    </button>
                                )}
                                {job.downloads?.includes("report.pdf") && (
                                    <button className="wd-btn ghost small" onClick={() => download(`${VERIFY}/api/analysis/${job.id}/files/report.pdf`, `${job.label}.pdf`)}>
                                        <Download size={13} /> PDF report
                                    </button>
                                )}
                                {job.terminal && (
                                    <button className="wd-btn ghost small" aria-label="Delete this check" onClick={remove}>
                                        <Trash2 size={13} />
                                    </button>
                                )}
                            </div>
                        )}
                        {glb.url && partNames.length > 0 && (
                            <div className="wd-legend" aria-label="Parts">
                                {partNames.slice(0, 18).map((p) => {
                                    const nodes = (report?.instances ?? []).filter((i) => i.part === p).map((i) => i.path);
                                    return (
                                        <button key={p} aria-pressed={partFocus === p}
                                                onClick={() => { setOpenFp(null); setPartFocus(partFocus === p ? null : p); }}>
                                            <i style={{ background: legendColor(nodes[0], report) }} />{p}
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                    {report && (
                        <div className="wd-drawer">
                            <div className="wd-drawer-tabs" role="tablist">
                                {([["changes", `Changes ${report.changes?.length ?? 0}`], ["interfaces", `Interfaces ${report.interfaces?.length ?? 0}`],
                                   ["bom", "BOM"], ["parts", `Parts ${report.parts?.length ?? 0}`], ["assumptions", "Assumptions"]] as const).map(([k, t]) => (
                                    <button key={k} role="tab" aria-selected={drawer === k} onClick={() => setDrawer(k)}>{t}</button>
                                ))}
                            </div>
                            <div className="wd-scroll"><Drawer tab={drawer} report={report} onPart={(p) => { setOpenFp(null); setPartFocus(p); }} /></div>
                        </div>
                    )}
                </section>

                {/* ---------------------------------------------------- right */}
                <aside className="wd-col right">
                    <div className="wd-summary">
                        {SEVS.map((k) => (
                            <button key={k} className={`wd-sev ${k}${s[k] ? "" : " zero"}`} aria-pressed={sevFilter === k}
                                    onClick={() => setSevFilter(sevFilter === k ? null : k)}>
                                <b>{s[k] ?? 0}</b><span>{SEV_WORD[k]}</span>
                            </button>
                        ))}
                    </div>
                    <div className="wd-scroll">
                        {job?.narrative && (
                            <div className="wd-narr">
                                <p>{job.narrative.summary}</p>
                                {job.narrative.points.length > 0 && (
                                    <ul>{job.narrative.points.map((p, i) => <li key={i}>{p.text}</li>)}</ul>
                                )}
                                <div className="src">
                                    {job.narrative.status === "llm" ? "Written by the language model from the findings below; every point cites one." : "Summary computed from the findings; no language model configured."}
                                </div>
                            </div>
                        )}
                        {shown.map((f) => (
                            <div key={f.fingerprint} className="wd-finding" aria-expanded={openFp === f.fingerprint}>
                                <button onClick={() => { setPartFocus(null); setOpenFp(openFp === f.fingerprint ? null : f.fingerprint); }}>
                                    <span className="rail" style={{ background: SEV_COLOR[f.severity] }} />
                                    <span>
                                        <span className="rule">
                                            <strong>{RULE_WORD[f.rule_id] ?? f.rule_id}</strong>
                                            {f.change_status && f.change_status !== "unchanged" && <span className={`wd-tag ${f.change_status}`}>{f.change_status}</span>}
                                            {f.review && f.review !== "open" && <span className={`wd-tag ${f.review}`}>{f.review === "real" ? "confirmed" : "not an issue"}</span>}
                                        </span>
                                        <span className="msg">{f.message}</span>
                                    </span>
                                </button>
                                {openFp === f.fingerprint && (
                                    <div className="wd-detail">
                                        <dl className="wd-kv">
                                            <dt>Rule</dt><dd>{f.rule_id}</dd>
                                            {Object.entries(f.measured ?? {}).map(([k, v]) => [<dt key={`m${k}`}>Measured {k.replace(/_/g, " ")}</dt>, <dd key={`mv${k}`}>{show(v)}</dd>])}
                                            {Object.entries(f.expected ?? {}).map(([k, v]) => [<dt key={`e${k}`}>Expected {k.replace(/_/g, " ")}</dt>, <dd key={`ev${k}`}>{show(v)}</dd>])}
                                            {f.method && <><dt>Method</dt><dd>{f.method}</dd></>}
                                            <dt>Evidence from</dt><dd>{f.source}</dd>
                                            {f.parts.length > 0 && <><dt>Parts</dt><dd>{f.parts.join(", ")}</dd></>}
                                            {f.location && <><dt>At (mm)</dt><dd>{show(f.location)}</dd></>}
                                        </dl>
                                        <div className="wd-actions">
                                            <button className="wd-btn small" onClick={() => review(f, "real")}>Confirm issue</button>
                                            <button className="wd-btn ghost small" onClick={() => review(f, "not_issue")}>Not an issue</button>
                                            {f.review && f.review !== "open" && <button className="wd-btn ghost small" onClick={() => review(f, "open")}>Reopen</button>}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                        {job?.terminal && job.state === "SUCCEEDED" && !findings.length && (
                            <div className="wd-empty-note">No disagreements found. Every check that had inputs passed.</div>
                        )}
                        {!job && <div className="wd-empty-note">Findings appear here, worst first, each with the measurement behind it.</div>}
                    </div>
                </aside>
            </div>
        </>
    );
}

/** Legend swatch: the same colour the viewer gives the node (sorted-name index). */
function legendColor(node: string | undefined, report: { instances?: { path: string }[] } | null): string {
    if (!node || !report?.instances) return "#8a9bb4";
    const names = [...new Set(report.instances.map((i) => nodeKey(i.path)))].sort();
    return TINTS[names.indexOf(nodeKey(node)) % TINTS.length];
}
function Drawer({ tab, report, onPart }: { tab: string; report: AssemblyReport; onPart: (p: string) => void }) {
    if (tab === "changes") {
        if (!report.changes?.length) return <div className="wd-empty-note">No previous revision was given, or nothing changed.</div>;
        return (
            <table className="wd-table">
                <thead><tr><th>Part</th><th>Change</th><th>What changed</th><th>Look at</th></tr></thead>
                <tbody>{report.changes.map((c, i) => (
                    <tr key={i} className={c.interface_changed ? "hot" : ""} onClick={() => onPart(c.part)} style={{ cursor: "pointer" }}>
                        <td>{c.part}</td><td>{c.status}{c.interface_changed ? " · mating features" : ""}</td>
                        <td>{c.details.slice(0, 3).join("; ")}</td><td>{c.neighbours.join(", ") || "—"}</td>
                    </tr>
                ))}</tbody>
            </table>
        );
    }
    if (tab === "interfaces") {
        return (
            <table className="wd-table">
                <thead><tr><th>Between</th><th>And</th><th className="num">Contact planes</th><th className="num">Gap mm</th></tr></thead>
                <tbody>{(report.interfaces ?? []).map((x, i) => (
                    <tr key={i}><td>{x.a}</td><td>{x.b}</td><td className="num">{x.planes}</td><td className="num">{x.distance_mm ?? (x.exact ? "0" : "adjacent")}</td></tr>
                ))}</tbody>
            </table>
        );
    }
    if (tab === "bom") {
        const rows = (report.bom as { rows?: Record<string, unknown>[] })?.rows ?? [];
        const matches = (report.bom as { matches?: { row: number; part: string; how: string }[] })?.matches ?? [];
        if (!rows.length) return <div className="wd-empty-note">No BOM was given.</div>;
        const m = new Map(matches.map((x) => [x.row, x]));
        return (
            <table className="wd-table">
                <thead><tr><th>Part number</th><th>Name</th><th>Rev</th><th className="num">Qty</th><th>Matched CAD part</th><th>How</th></tr></thead>
                <tbody>{rows.map((r, i) => (
                    <tr key={i}><td>{show(r.part_number)}</td><td>{show(r.name)}</td><td>{show(r.revision)}</td><td className="num">{show(r.quantity)}</td>
                        <td>{m.get(i)?.part ?? <span className="wd-tally-medium">unmatched</span>}</td><td>{m.get(i)?.how ?? "—"}</td></tr>
                ))}</tbody>
            </table>
        );
    }
    if (tab === "parts") {
        return (
            <table className="wd-table">
                <thead><tr><th>Part</th><th className="num">Count</th><th className="num">Holes</th><th className="num">Volume mm³</th><th>Recognised as</th></tr></thead>
                <tbody>{(report.parts ?? []).map((p, i) => (
                    <tr key={i} onClick={() => onPart(p.part)} style={{ cursor: "pointer" }}>
                        <td>{p.part}</td><td className="num">{p.count}</td><td className="num">{p.holes}</td>
                        <td className="num">{Math.round(p.volume_mm3).toLocaleString()}</td><td>{p.component ?? (p.geometry_type === "MESH" ? "mesh body" : "—")}</td>
                    </tr>
                ))}</tbody>
            </table>
        );
    }
    return (
        <ul style={{ margin: 0, padding: "10px 16px 14px 32px", color: "var(--wd-sub)" }}>
            {(report.assumptions ?? []).map((a, i) => <li key={i} style={{ margin: "3px 0" }}>{a}</li>)}
        </ul>
    );
}
