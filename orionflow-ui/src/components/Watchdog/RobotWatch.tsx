/**
 * Robot watch: is the robot model physically possible, and does it simulate?
 * Check an uploaded URDF/MJCF, or compile a reference robot from its spec and
 * see every gate it had to pass.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Play, Trash2 } from "lucide-react";
import ModelView, { type ModelFocus } from "./ModelView";
import { DropSlot } from "./parts";
import { SEV_COLOR, ago, useBlobUrl, usePoll } from "../../lib/watchdog";
import {
    createRobotRun,
    deleteRobotRun,
    getRobotRun,
    listRobotRuns,
    type RobotFinding,
    type RobotRun,
} from "../../services/watchdogApi";

const GATE_WORD: Record<string, string> = {
    geometry: "Geometry builds", inertia: "Inertia is physical", interference: "No parts collide",
    actuators: "Servos can hold the load", robocheck: "Loads and simulates cleanly", stands: "Stands on its own",
};

function lampFor(r: RobotRun) {
    if (r.status === "queued" || r.status === "running") return "busy";
    if (r.status === "error") return "failed";
    if (r.accepted === false || r.summary?.errors) return "high";
    if (r.summary?.warnings) return "medium";
    return "clear";
}

export default function RobotWatch({ available, reason }: { available: boolean; reason: string | null }) {
    const [runs, setRuns] = useState<RobotRun[]>([]);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [run, setRun] = useState<RobotRun | null>(null);
    const [mode, setMode] = useState<"check" | "compile">("check");
    const [robotFile, setRobotFile] = useState<File[]>([]);
    const [meshes, setMeshes] = useState<File[]>([]);
    const [target, setTarget] = useState<"arm" | "quadruped">("quadruped");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [openKey, setOpenKey] = useState<string | null>(null);
    const [picked, setPicked] = useState<string | null>(null);
    const [links, setLinks] = useState<string[]>([]);

    const refresh = useCallback(() => listRobotRuns().then(setRuns).catch((e) => setError(e.message)), []);
    useEffect(() => { if (available) refresh(); }, [available, refresh]);
    useEffect(() => { if (!activeId && runs.length) setActiveId(runs[0].id); }, [runs, activeId]);

    const load = useCallback(async (id: string) => {
        const r = await getRobotRun(id);
        setRun(r);
        setRuns((l) => l.map((x) => (x.id === id ? { ...x, ...r, report: undefined } : x)));
    }, []);
    useEffect(() => { setRun(null); setOpenKey(null); setLinks([]); if (activeId) load(activeId).catch((e) => setError(e.message)); }, [activeId, load]);
    const running = !!run && (run.status === "queued" || run.status === "running");
    usePoll(() => activeId && load(activeId).catch(() => undefined), 2000, running);

    const glb = useBlobUrl(run?.has_glb ? `/api/v1/watchdog/robot/runs/${run.id}/files/model.glb` : null, "Loading the robot");

    const findings = useMemo(() => {
        const out: (RobotFinding & { key: string; fmt: string })[] = [];
        for (const [fmt, c] of Object.entries(run?.report?.robocheck ?? {})) {
            c.findings.forEach((f, i) => out.push({ ...f, fmt, key: `${fmt}:${i}` }));
        }
        const order = { error: 0, warning: 1, info: 2 } as const;
        return out.sort((a, b) => order[a.severity] - order[b.severity]);
    }, [run?.report?.robocheck]);
    const open = findings.find((f) => f.key === openKey) ?? null;

    const focus: ModelFocus | null = useMemo(() => {
        if (!open?.where) return null;
        const hit = links.filter((l) => open.where.split(/[\s,/:]+/).includes(l) || open.where === l);
        return hit.length ? { nodes: hit, color: SEV_COLOR[open.severity] } : null;
    }, [open, links]);

    async function start() {
        setBusy(true);
        setError(null);
        try {
            const r = await createRobotRun(mode === "check"
                ? { mode, file: robotFile[0], meshes }
                : { mode, target, label: target === "arm" ? "Two-link arm from spec" : "Quadruped from spec" });
            setRobotFile([]);
            setMeshes([]);
            await refresh();
            setActiveId(r.id);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }

    if (!available) {
        return <div className="wd-view-empty" style={{ position: "relative", gridRow: "2 / 4" }}><h2>Robot checks are not available on this server</h2><p>{reason}</p></div>;
    }

    const gates = Object.entries(run?.report?.gates ?? {});
    const checks = Object.values(run?.report?.robocheck ?? {});
    const strip: [string, string, string][] = gates.length
        ? gates.map(([k, g]) => [k, GATE_WORD[k] ?? k, g.passed ? "PASS" : "FAIL"])
        : checks.length
            ? checks.flatMap((c) => [
                [`${c.format}-load`, `${c.format.toUpperCase()} loads in MuJoCo`, c.loaded ? "PASS" : "FAIL"],
                [`${c.format}-err`, `${c.errors} physics errors`, c.errors ? "FAIL" : "PASS"],
                [`${c.format}-warn`, `${c.warnings} plausibility warnings`, c.warnings ? "WARNING" : "PASS"],
            ] as [string, string, string][])
            : [["idle", running ? "Simulating" : "No robot open", running ? "RUNNING" : ""]];

    const total = run?.report?.total_mass_kg;
    return (
        <>
            <div className="wd-stages" style={{ gridTemplateColumns: `repeat(${strip.length}, minmax(0, 1fr))` }} role="list" aria-label="Robot gates">
                {strip.map(([k, label, s]) => (
                    <div key={k} className="wd-stage" data-s={s} role="listitem"><div className="bar" /><div className="name">{label}</div></div>
                ))}
            </div>
            <div className="wd-body">
                <aside className="wd-col left">
                    <div className="wd-scroll">
                        <div className="wd-section">
                            <h3 className="wd-h">Robot model</h3>
                            <div className="wd-seg">
                                <button aria-pressed={mode === "check"} onClick={() => setMode("check")}>Check my model</button>
                                <button aria-pressed={mode === "compile"} onClick={() => setMode("compile")}>Compile from spec</button>
                            </div>
                            {mode === "check" ? (
                                <>
                                    <DropSlot label="URDF or MJCF" accept=".urdf,.xml" files={robotFile} required onFiles={setRobotFile} />
                                    <DropSlot label="Meshes" hint="STL, OBJ, DAE — the files the model references" accept=".stl,.obj,.dae,.ply,.glb" many files={meshes} onFiles={setMeshes} />
                                </>
                            ) : (
                                <>
                                    <p className="wd-p">Build a robot from its spec: exact solids, inertia from geometry, URDF and MJCF, then every gate.</p>
                                    <div className="wd-seg">
                                        <button aria-pressed={target === "quadruped"} onClick={() => setTarget("quadruped")}>Quadruped</button>
                                        <button aria-pressed={target === "arm"} onClick={() => setTarget("arm")}>Two-link arm</button>
                                    </div>
                                </>
                            )}
                            <button className="wd-btn block" disabled={busy || (mode === "check" && !robotFile.length)} onClick={start}>
                                <Play size={15} /> {busy ? "Starting…" : mode === "check" ? "Check robot" : "Compile and check"}
                            </button>
                            {error && <div className="wd-error">{error}</div>}
                        </div>
                        <div className="wd-section" style={{ borderBottom: 0, paddingBottom: 6 }}>
                            <h3 className="wd-h" style={{ margin: 0 }}>History <span className="count">{runs.length}</span></h3>
                        </div>
                        {runs.map((r) => (
                            <button key={r.id} className="wd-run" aria-current={r.id === activeId} onClick={() => setActiveId(r.id)}>
                                <span className={`lamp ${lampFor(r)}`} />
                                <span className="t"><b>{r.label}</b><small>{r.status === "done" ? ago(r.created) : r.status}</small></span>
                                <span className="tally">
                                    {!!r.summary?.errors && <span className="wd-tally-high">{r.summary.errors}</span>}
                                    {!!r.summary?.warnings && <span className="wd-tally-medium">{r.summary.warnings}</span>}
                                </span>
                            </button>
                        ))}
                        {!runs.length && <div className="wd-empty-note">Robot checks will be listed here.</div>}
                    </div>
                </aside>

                <section className="wd-centre">
                    <div className="wd-view">
                        {glb.url ? (
                            <ModelView url={glb.url} focus={focus} selected={picked} onPick={setPicked} onNodes={setLinks} />
                        ) : (
                            <div className="wd-view-empty">
                                {run?.status === "error" ? (<><h2>This robot run did not finish</h2><p>{run.error}</p></>) :
                                 running ? (<><h2>Checking {run!.label}</h2><p>Compiling in MuJoCo and letting it settle on a floor.</p></>) :
                                 run?.status === "done" ? (<><Bot size={30} color="#6fb4ff" /><p>{run.report?.view?.error ?? "No visual geometry could be drawn — upload the meshes the model references."}</p></>) :
                                 (<><h2>Will this robot simulate the way it was built?</h2><p>Upload a URDF or MJCF with its meshes, or compile a reference robot from its spec.</p></>)}
                            </div>
                        )}
                        {run?.status === "done" && (
                            <div className="wd-hud">
                                <span className="wd-chip"><b>{run.report?.robot ?? run.label}</b></span>
                                {run.accepted != null && <span className="wd-chip" style={{ color: run.accepted ? "var(--wd-pass)" : "var(--wd-high)" }}><b style={{ color: "inherit" }}>{run.accepted ? "Accepted" : "Rejected"}</b></span>}
                                {total != null && <span className="wd-chip"><b>{(total * 1000).toFixed(0)}</b> g</span>}
                                {links.length > 0 && <span className="wd-chip"><b>{links.length}</b> links</span>}
                                {picked && <span className="wd-chip">Link <b>{picked}</b>{run.report?.links?.[picked] ? `, ${(run.report.links[picked].mass_kg * 1000).toFixed(1)} g` : ""}</span>}
                                <span style={{ flex: 1 }} />
                                <button className="wd-btn ghost small" aria-label="Delete this robot run" onClick={async () => { await deleteRobotRun(run.id); setActiveId(null); refresh(); }}><Trash2 size={13} /></button>
                            </div>
                        )}
                        {(run?.report?.view?.missing_meshes?.length ?? 0) > 0 && (
                            <div className="wd-legend"><span className="wd-chip">{run!.report!.view!.missing_meshes!.length} referenced meshes were not uploaded and are not drawn</span></div>
                        )}
                    </div>
                </section>

                <aside className="wd-col right">
                    <div className="wd-scroll">
                        {gates.length > 0 && (
                            <div className="wd-section">
                                <h3 className="wd-h">Gates</h3>
                                <div className="wd-gates">
                                    {gates.map(([k, g]) => (
                                        <div key={k} className={`wd-gate ${g.passed ? "pass" : "fail"}`}><i /><span>{GATE_WORD[k] ?? k}</span><small className="wd-muted">{g.passed ? "passed" : "failed"}</small></div>
                                    ))}
                                </div>
                            </div>
                        )}
                        {checks.length > 0 && (
                            <div className="wd-section">
                                <h3 className="wd-h">Physics check</h3>
                                {checks.map((c) => (
                                    <p key={c.format} className="wd-p">{c.source}: {c.loaded ? "loads in MuJoCo" : "does not load"}, {c.errors} errors, {c.warnings} warnings.</p>
                                ))}
                            </div>
                        )}
                        {findings.map((f) => (
                            <div key={f.key} className="wd-finding" aria-expanded={openKey === f.key}>
                                <button onClick={() => setOpenKey(openKey === f.key ? null : f.key)}>
                                    <span className="rail" style={{ background: SEV_COLOR[f.severity] }} />
                                    <span>
                                        <span className="rule"><code>{f.code}</code>{f.where && <span className="wd-tag">{f.where}</span>}</span>
                                        <span className="msg">{f.message}</span>
                                    </span>
                                </button>
                            </div>
                        ))}
                        {run?.status === "done" && !findings.length && <div className="wd-empty-note">No physics problems found.</div>}
                        {!run && <div className="wd-empty-note">Gates and physics findings appear here.</div>}
                    </div>
                </aside>
            </div>
        </>
    );
}
