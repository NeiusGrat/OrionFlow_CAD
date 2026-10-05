/**
 * Assembly check, in Inspect's paper-and-ink: an assembly STEP (+ previous
 * revision, BOM, URDF) in; interfaces, hole patterns, fasteners, clearances and
 * the BOM checked against each other, every finding with its measurement.
 * The engine is interface_check (VITE_VERIFY_URL in production).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Download } from "lucide-react";
import { AppBar, Drop } from "../../components/Inspect/common";
import ModelPane from "../../components/Inspect/ModelPane";
import { useBlobUrl, usePoll } from "../../lib/watchdog";
import { when } from "../../lib/inspect";
import { authedFetch } from "../../services/http";
import {
    VERIFY, createAnalysis, download, getAnalysis, listAnalyses, reviewFinding,
    type AnalysisJob, type AssemblyFinding,
} from "../../services/watchdogApi";
import "../../styles/inspect.css";

const SEV = { high: "critical", medium: "major", low: "minor", info: "none" } as const;
const RULE_WORD: Record<string, string> = {
    HOLE_MISALIGNED: "Holes do not line up", HOLE_MISSING: "Mating hole missing", PATTERN_MISMATCH: "Hole pattern does not match",
    FASTENER_SIZE_MISMATCH: "Fastener sizes disagree", BEARING_SEAT: "Bearing seat out of fit", MOTOR_FLANGE: "Motor flange mismatch",
    INTERFERENCE: "Parts interfere", BOM_QTY_MISMATCH: "BOM quantity differs from CAD", IN_CAD_NOT_BOM: "In CAD, not on the BOM",
    IN_BOM_NOT_CAD: "On the BOM, not in CAD", URDF_MASS_DRIFT: "Robot model mass drifted", URDF_COM_DRIFT: "Robot model centre of mass drifted",
    JOINT_AXIS_DRIFT: "Joint axis drifted", JOINT_ORIGIN_DRIFT: "Joint origin drifted", PART_INVALID: "Invalid solid",
    UNSUPPORTED_GEOMETRY: "Mesh body, partly checked", DRAWING_STALE: "Drawing older than the part",
};

function status(j: AnalysisJob): { word: string; cls: string } {
    if (!j.terminal) return { word: "Checking", cls: "checking" };
    if (j.state !== "SUCCEEDED") return { word: "Failed", cls: "failed" };
    if (j.summary?.high) return { word: `${j.summary.high} critical`, cls: "review" };
    return { word: "Clear", cls: "signed" };
}

export default function AssemblyPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [jobs, setJobs] = useState<AnalysisJob[] | null>(null);
    const [job, setJob] = useState<AnalysisJob | null>(null);
    const [instances, setInstances] = useState<{ path: string; part: string }[]>([]);
    const [step, setStep] = useState<File | null>(null);
    const [prev, setPrev] = useState<File | null>(null);
    const [bom, setBom] = useState<File | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [sel, setSel] = useState<string | null>(null);

    const loadList = useCallback(() => listAnalyses().then(setJobs).catch((e) => setError(e.message)), []);
    useEffect(() => { document.title = "Assembly check — OrionFlow Inspect"; loadList(); }, [loadList]);

    const loadJob = useCallback(async (jid: string) => {
        const j = await getAnalysis(jid);
        setJob(j);
        if (j.terminal && j.downloads?.includes("report.json")) {
            const r = await authedFetch(`${VERIFY}/api/analysis/${jid}/files/report.json`);
            if (r.ok) setInstances(((await r.json()).instances ?? []) as { path: string; part: string }[]);
        }
    }, []);
    useEffect(() => { setJob(null); setInstances([]); setSel(null); if (id) loadJob(id).catch((e) => setError(e.message)); }, [id, loadJob]);
    usePoll(() => id && loadJob(id).catch(() => undefined), 2000, !!job && !job.terminal);
    usePoll(loadList, 4000, !!jobs?.some((j) => !j.terminal));

    const glb = useBlobUrl(job?.downloads?.includes("model.glb") ? `${VERIFY}/api/analysis/${job.id}/files/model.glb` : null, "Loading the model");
    const findings = useMemo(() => {
        const order = { high: 0, medium: 1, low: 2, info: 3 } as const;
        return [...(job?.findings ?? [])].sort((a, b) => order[a.severity] - order[b.severity]);
    }, [job?.findings]);
    const finding = findings.find((f) => f.fingerprint === sel) ?? null;
    const highlight = finding
        ? (finding.instances.length ? finding.instances : instances.filter((i) => finding.parts.includes(i.part)).map((i) => i.path))
        : [];

    async function run() {
        if (!step) return;
        setBusy(true);
        setError(null);
        try {
            const j = await createAnalysis({ step: [step], ...(prev ? { prev_step: [prev] } : {}), ...(bom ? { bom: [bom] } : {}) }, step.name);
            setStep(null); setPrev(null); setBom(null);
            await loadList();
            navigate(`/assembly/${j.id}`);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }

    async function review(f: AssemblyFinding, verdict: "real" | "not_issue" | "open") {
        if (!job) return;
        try {
            await reviewFinding(job.id, f.fingerprint, verdict);
            setJob({ ...job, findings: job.findings?.map((x) => (x.fingerprint === f.fingerprint ? { ...x, review: verdict } : x)) });
        } catch (e) { setError((e as Error).message); }
    }

    const stats = (job?.stats ?? {}) as Record<string, number>;
    return (
        <div className="in in-ws">
            <AppBar crumbs={<><Link to="/assembly">Assembly check</Link>{job && <><span className="sep">/</span><b>{job.label}</b></>}</>} />
            <div className="in-ws-body">
                <aside className="in-col left">
                    <div className="in-scroll">
                        <div className="in-files">
                            <h3>New assembly check</h3>
                            <Drop label="Assembly" hint="STEP with every part placed" accept=".step,.stp" file={step} required onFile={setStep} />
                            <Drop label="Previous revision" hint="STEP, to see what changed" accept=".step,.stp" file={prev} onFile={setPrev} />
                            <Drop label="BOM" hint="CSV" accept=".csv,.tsv,.txt" file={bom} onFile={setBom} />
                            <button className="in-btn block" disabled={!step || busy} onClick={run}>{busy ? "Uploading…" : "Check assembly"}</button>
                            {error && <div className="in-error">{error}</div>}
                        </div>
                        <div className="in-files">
                            <h3>History</h3>
                            {(jobs ?? []).map((j) => {
                                const st = status(j);
                                return (
                                    <Link key={j.id} to={`/assembly/${j.id}`} className="in-file" style={{ textDecoration: "none", background: j.id === id ? "var(--wash)" : undefined }}>
                                        <b>{j.label}</b>
                                        <span><span className={`in-status ${st.cls}`}>{st.word}</span> {when(Date.parse(j.created_at) / 1000)}</span>
                                    </Link>
                                );
                            })}
                            {jobs?.length === 0 && <p className="sub" style={{ fontSize: 12 }}>No assemblies checked yet.</p>}
                        </div>
                    </div>
                </aside>

                <section className="in-col">
                    <div className="in-tabs"><button aria-selected="true">3D model</button><span className="spacer" />
                        {job?.downloads?.includes("report.pdf") && (
                            <div className="tools"><button className="in-btn line sm" onClick={() => download(`${VERIFY}/api/analysis/${job.id}/files/report.pdf`, `${job.label}.pdf`)}><Download size={13} /> PDF report</button></div>
                        )}
                    </div>
                    <div className="in-viewer">
                        {glb.url ? (
                            <>
                                <ModelPane url={glb.url} highlight={highlight} />
                                <div className="in-3d-legend">{finding ? <><b>{RULE_WORD[finding.rule_id] ?? finding.rule_id}</b><div className="sub">{finding.parts.join(", ")}</div></> : <span className="sub">Select a finding to show the parts it is about.</span>}</div>
                            </>
                        ) : (
                            <div className="in-overlay-note">
                                {!id ? "Upload an assembly STEP. Every interface between parts is found and measured: hole patterns, fastener sizes, bearing seats, clearances and, with a BOM, quantities."
                                    : job && !job.terminal ? `Checking: ${(job.stage ?? "queued").replace(/_/g, " ")}…`
                                    : job && job.state !== "SUCCEEDED" ? `■ ${job.error || job.failure_code || job.state}` : glb.error ?? "Loading…"}
                            </div>
                        )}
                    </div>
                </section>

                <aside className="in-col right">
                    <div className="in-tabs"><button aria-selected="true">Findings {findings.length || ""}</button></div>
                    {job?.summary && (
                        <div className="in-counts">
                            <span><i className="sev critical" /> <b>{job.summary.high ?? 0}</b> critical</span>
                            <span><i className="sev major" /> <b>{job.summary.medium ?? 0}</b> major</span>
                            <span><i className="sev minor" /> <b>{job.summary.low ?? 0}</b> minor</span>
                            <span style={{ marginLeft: "auto" }} className="mono">{stats.parts ?? "–"} parts, {stats.interfaces ?? "–"} interfaces</span>
                        </div>
                    )}
                    <div className="in-scroll">
                        {findings.map((f) => (
                            <div key={f.fingerprint}>
                                <button className={`in-finding${f.review && f.review !== "open" ? " decided" : ""}`} aria-selected={sel === f.fingerprint} onClick={() => setSel(sel === f.fingerprint ? null : f.fingerprint)}>
                                    <i className={`sev ${SEV[f.severity]}`} aria-label={f.severity} />
                                    <span><b>{RULE_WORD[f.rule_id] ?? f.rule_id}</b><span className="msg">{f.message}</span></span>
                                    <span className="dec">{f.review && f.review !== "open" ? (f.review === "real" ? "confirmed" : "not an issue") : f.change_status ?? ""}</span>
                                </button>
                                {sel === f.fingerprint && (
                                    <div className="in-drawer" style={{ maxHeight: "none" }}>
                                        <div className="body">
                                            <dl className="in-kv">
                                                <dt>Rule</dt><dd className="mono">{f.rule_id}</dd>
                                                {Object.entries(f.measured ?? {}).map(([k, v]) => [<dt key={`m${k}`}>Measured {k.replace(/_/g, " ")}</dt>, <dd key={`v${k}`} className="mono">{JSON.stringify(v)}</dd>])}
                                                {Object.entries(f.expected ?? {}).map(([k, v]) => [<dt key={`e${k}`}>Expected {k.replace(/_/g, " ")}</dt>, <dd key={`x${k}`} className="mono">{JSON.stringify(v)}</dd>])}
                                                {f.method && <><dt>Method</dt><dd>{f.method}</dd></>}
                                            </dl>
                                            <div className="in-actions">
                                                <button className="in-btn sm" onClick={() => review(f, "real")}>Confirm</button>
                                                <button className="in-btn line sm" onClick={() => review(f, "not_issue")}>Not an issue</button>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                        {job?.terminal && job.state === "SUCCEEDED" && findings.length === 0 && <p className="sub" style={{ padding: 14 }}>✓ No disagreements: every interface measured agrees.</p>}
                    </div>
                </aside>
            </div>
            <footer className="in-statusbar">
                {job?.stats ? <><span>runtime <b>{String(stats.runtime_s ?? "")}s</b></span><span>engine <b>{String((job.stats as Record<string, unknown>).engine_version ?? "")}</b></span><span>model <b>none (deterministic)</b></span></> : <span />}
            </footer>
        </div>
    );
}
