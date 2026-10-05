/**
 * The inspection workspace: the six steps on the left, the drawing (and model)
 * in the centre, the Form 3 table / findings / forms / sign-off on the right.
 * Selecting a row, a balloon or a finding selects the same characteristic
 * everywhere: its balloon, its row, and the model faces its CAD value came from.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Download, Maximize2, Minus, Plus, X } from "lucide-react";
import { AppBar } from "../../components/Inspect/common";
import DrawingView from "../../components/Inspect/DrawingView";
import ModelPane from "../../components/Inspect/ModelPane";
import { useBlobUrl, usePoll } from "../../lib/watchdog";
import { CAD_WORD, TOL_SOURCE, fmt, limits, revStatus, short, when } from "../../lib/inspect";
import { download } from "../../services/watchdogApi";
import {
    decideFinding, editCharacteristic, fileUrl, getRevision, pageUrl, signRevision, updateForm1,
    type Characteristic, type CharStatus, type Decision, type Finding, type Revision,
} from "../../services/faiApi";
import "../../styles/inspect.css";

type View = "drawing" | "model" | "split";
type Panel = "chars" | "findings" | "accuracy" | "forms" | "sign";

const DECISION_WORD: Record<string, string> = { accepted: "accepted", rejected: "rejected", ignored: "ignored" };

export default function Workspace() {
    const { rid = "" } = useParams();
    const navigate = useNavigate();
    const [rev, setRev] = useState<Revision | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [view, setView] = useState<View>("drawing");
    const [panel, setPanel] = useState<Panel>("chars");
    const [sel, setSel] = useState<number | null>(null);
    const [fsel, setFsel] = useState<string | null>(null);
    const [zoom, setZoom] = useState(1);
    const [onlyOpen, setOnlyOpen] = useState(false);

    const load = useCallback(() => getRevision(rid).then((r) => {
        setRev(r);
        document.title = `${r.project?.part_number ?? "Inspection"} rev ${r.label || ""} — OrionFlow Inspect`;
    }).catch((e) => setError(e.message)), [rid]);
    useEffect(() => { setRev(null); setSel(null); setFsel(null); load(); }, [load]);
    const busy = !!rev && ["queued", "running"].includes(rev.status);
    usePoll(load, 1500, busy);

    const res = rev?.result?.status === "done" ? rev.result : null;
    const chars = useMemo(() => res?.characteristics ?? [], [res]);
    const findings = useMemo(() => res?.findings ?? [], [res]);
    const flagged = useMemo(() => new Set(findings.filter((f) => f.char_no && !f.decision).map((f) => f.char_no as number)), [findings]);
    const selected = chars.find((c) => c.no === sel) ?? null;
    const finding = findings.find((f) => f.id === fsel) ?? null;
    const signed = !!rev?.signoff;
    const glb = useBlobUrl(res?.has_glb ? fileUrl(rid, "model.glb") : null, "Loading the model");
    const highlight = finding?.cad_nodes?.length ? finding.cad_nodes : selected?.cad_nodes ?? [];

    function patchChar(c: Characteristic) {
        setRev((r) => r && r.result ? { ...r, result: { ...r.result, characteristics: r.result.characteristics.map((x) => (x.no === c.no ? c : x)) } } : r);
    }
    function patchFinding(f: Finding) {
        setRev((r) => r && r.result ? { ...r, result: { ...r.result, findings: r.result.findings.map((x) => (x.id === f.id ? f : x)) } } : r);
    }

    async function edit(no: number, fields: Partial<Characteristic>) {
        try {
            patchChar(await editCharacteristic(rid, no, fields));
            getRevision(rid).then((r) => setRev((cur) => (cur ? { ...cur, readiness: r.readiness, events: r.events } : r)));
        } catch (e) { setError((e as Error).message); }
    }
    async function decide(f: Finding, d: Decision, forCustomer = false) {
        try {
            patchFinding(await decideFinding(rid, f.id, d, d === "accepted" ? "query raised with the customer" : "", forCustomer));
            getRevision(rid).then((r) => setRev((cur) => (cur ? { ...cur, readiness: r.readiness } : r)));
        } catch (e) { setError((e as Error).message); }
    }

    const selectChar = (no: number) => { setSel(no); setFsel(null); if (panel !== "chars" && panel !== "findings") setPanel("chars"); };
    const selectFinding = (f: Finding) => { setFsel(f.id); if (f.char_no) setSel(f.char_no); };

    const counts = {
        critical: findings.filter((f) => f.severity === "critical" && !f.decision).length,
        major: findings.filter((f) => f.severity === "major" && !f.decision).length,
        minor: findings.filter((f) => f.severity === "minor" && !f.decision).length,
        pass: chars.filter((c) => c.status === "pass" || c.status === "accepted").length,
        open: chars.filter((c) => c.inspect && c.status === "open").length,
        fail: chars.filter((c) => c.status === "fail").length,
    };
    const steps = res?.steps ?? rev?.progress ?? [];
    const st = revStatus(rev);

    const crumbs = rev?.project ? (
        <><Link to={`/p/${rev.project.id}`}>{rev.project.part_number || "Project"}</Link><span className="sep">/</span><b>Rev {rev.label || "—"}</b>
            <span className={`in-status ${st.cls}`} style={{ marginLeft: 6 }}>{st.word}</span></>
    ) : <b>Inspection</b>;

    return (
        <div className="in in-ws">
            <AppBar crumbs={crumbs} right={<>
                {rev?.previous && res && <button className="in-btn line sm" onClick={() => navigate(`/compare/${rev.project_id}?a=${rev.previous!.id}&b=${rid}`)}>Compare with rev {rev.previous.label || "previous"}</button>}
                {res && <button className="in-btn sm" onClick={() => setPanel("sign")}>{signed ? "Signed — exports" : "Sign & export"}</button>}
            </>} />
            <div className="in-ws-body">
                {/* ---------------------------------------------------------- steps */}
                <aside className="in-col left">
                    <div className="in-scroll">
                        <ol className="in-steps">
                            {steps.map((s, i) => (
                                <li key={s.id} className="in-step" data-s={s.status}>
                                    <span className="n">{i + 1}</span>
                                    <div>
                                        <b>{s.name}</b>
                                        <small>{s.status === "running" ? "working…" : s.detail || (s.status === "waiting" ? "waiting for you" : s.status === "done" ? `done${s.duration_s ? ` in ${s.duration_s}s` : ""}` : s.status)}</small>
                                        {s.id === "review" && res && !signed && <button className="in-btn line sm" onClick={() => setPanel(counts.critical ? "findings" : "chars")}>Review</button>}
                                        {s.id === "export" && res && <button className="in-btn line sm" onClick={() => setPanel("sign")}>{signed ? "Download" : "Sign"}</button>}
                                    </div>
                                </li>
                            ))}
                        </ol>
                        {rev && (
                            <div className="in-files">
                                <h3>Inputs</h3>
                                <div className="in-file"><b>{rev.drawing_name}</b><span>sha256 {short(rev.drawing_sha)}</span></div>
                                {rev.step_name && <div className="in-file"><b>{rev.step_name}</b><span>sha256 {short(rev.step_sha)}</span></div>}
                                {rev.bom_name && <div className="in-file"><b>{rev.bom_name}</b><span>sha256 {short(rev.bom_sha)}</span></div>}
                                {rev.drawing_changed === false && <p className="sub" style={{ fontSize: 12 }}>Same drawing file as rev {rev.previous?.label}.</p>}
                                {res && (
                                    <p className="sub" style={{ fontSize: 12, marginTop: 10 }}>
                                        General tolerance: {res.general_tolerance.applied_class
                                            ? `ISO 2768-${res.general_tolerance.applied_class} (${res.general_tolerance.applied_source === "general_note" ? "drawing note" : "selected at upload"})`
                                            : res.general_tolerance.applied_source === "general_profile"
                                                ? "general profile note (untoleranced sizes)"
                                                : "none stated"}
                                        {res.general_tolerance.units && <><br />Units: {res.general_tolerance.units === "in" ? "inches" : "millimetres"}{res.general_tolerance.units_stated === false ? " (inferred)" : ""}</>}
                                    </p>
                                )}
                                {(res?.warnings ?? []).map((w, i) => <p key={i} className="sub" style={{ fontSize: 12 }}>□ {w}</p>)}
                            </div>
                        )}
                    </div>
                </aside>

                {/* ---------------------------------------------------------- viewer */}
                <section className="in-col">
                    <div className="in-tabs" role="tablist" aria-label="View">
                        {([["drawing", "Drawing"], ["model", "3D model"], ["split", "Side by side"]] as const).map(([k, t]) => (
                            <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}>{t}</button>
                        ))}
                        <span className="spacer" />
                        {view !== "model" && (
                            <div className="tools">
                                <button className="in-btn quiet sm" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))}><Minus size={14} /></button>
                                <span className="mono" style={{ fontSize: 11, width: 40, textAlign: "center" }}>{Math.round(zoom * 100)}%</span>
                                <button className="in-btn quiet sm" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))}><Plus size={14} /></button>
                                <button className="in-btn quiet sm" aria-label="Fit to width" onClick={() => setZoom(1)}><Maximize2 size={13} /></button>
                            </div>
                        )}
                    </div>
                    <div className="in-viewer">
                        {!res ? (
                            <div className="in-overlay-note">
                                {error ? <span>■ {error}</span> : rev?.status === "error" ? <span>■ This revision could not be checked: {rev.error}</span>
                                    : busy ? <span>Reading the drawing and measuring the model…</span> : <span>Loading…</span>}
                            </div>
                        ) : (
                            <ViewerBody view={view} rid={rid} res={res} chars={chars} sel={sel} flagged={flagged} zoom={zoom}
                                        glbUrl={glb.url} glbError={glb.error} highlight={highlight} selected={selected}
                                        focusBox={finding && finding.page !== null ? { page: finding.page, bbox: finding.bbox } : null}
                                        onSelect={selectChar} />
                        )}
                    </div>
                </section>

                {/* ---------------------------------------------------------- right */}
                <aside className="in-col right">
                    <div className="in-tabs" role="tablist" aria-label="Panel">
                        <button role="tab" aria-selected={panel === "chars"} onClick={() => setPanel("chars")}>Characteristics {chars.length || ""}</button>
                        <button role="tab" aria-selected={panel === "findings"} onClick={() => setPanel("findings")}>Findings {findings.filter((f) => !f.decision).length || ""}</button>
                        {res?.accuracy && <button role="tab" aria-selected={panel === "accuracy"} onClick={() => setPanel("accuracy")}>Accuracy</button>}
                        <button role="tab" aria-selected={panel === "forms"} onClick={() => setPanel("forms")}>Forms 1 &amp; 2</button>
                        <button role="tab" aria-selected={panel === "sign"} onClick={() => setPanel("sign")}>Sign</button>
                    </div>
                    {res && (
                        <div className="in-counts" aria-label="Summary">
                            <span title="Critical findings open"><i className="sev critical" /> <b>{counts.critical}</b> critical</span>
                            <span title="Major findings open"><i className="sev major" /> <b>{counts.major}</b> major</span>
                            <span title="Minor findings open"><i className="sev minor" /> <b>{counts.minor}</b> minor</span>
                            <span style={{ marginLeft: "auto" }} title="Characteristics with a passing result"><i className="sev ok" /> <b>{counts.pass}</b> / {chars.filter((c) => c.inspect).length} passed</span>
                        </div>
                    )}
                    <div className="in-scroll" key={panel}>
                        {res && panel === "chars" && (
                            <CharTable chars={onlyOpen ? chars.filter((c) => c.inspect && c.status === "open") : chars} sel={sel} flagged={flagged}
                                       signed={signed} onSelect={selectChar} onEdit={edit} onlyOpen={onlyOpen} setOnlyOpen={setOnlyOpen} />
                        )}
                        {res && panel === "findings" && (
                            findings.length === 0 ? <p className="sub" style={{ padding: 14 }}>No findings: the drawing reads cleanly and agrees with every input given.</p> :
                                findings.map((f) => (
                                    <button key={f.id} className={`in-finding${f.decision ? " decided" : ""}`} aria-selected={fsel === f.id} onClick={() => selectFinding(f)}>
                                        <i className={`sev ${f.severity}`} aria-label={f.severity} />
                                        <span><b>{f.title}</b><span className="msg">{f.message}</span></span>
                                        <span className="dec">{f.decision ? DECISION_WORD[f.decision] : f.char_no ? `#${f.char_no}` : ""}</span>
                                    </button>
                                ))
                        )}
                        {res && panel === "accuracy" && res.accuracy && <AccuracyPanel acc={res.accuracy} onSelect={selectChar} vision={res.vision} />}
                        {res && panel === "forms" && <Forms rev={rev!} />}
                        {res && panel === "sign" && <SignPanel rev={rev!} onDone={load} onError={setError} />}
                    </div>
                    {finding && panel === "findings" && (
                        <FindingDrawer rid={rid} f={finding} res={res!} signed={signed} customer={rev?.project?.customer ?? ""}
                                       onClose={() => setFsel(null)} onDecide={decide} onEdit={() => { if (finding.char_no) { setSel(finding.char_no); setPanel("chars"); } }} />
                    )}
                </aside>
            </div>
            <footer className="in-statusbar">
                {res ? <>
                    <span>sheets <b>{res.stats.sheets}</b></span>
                    <span>characteristics <b>{res.stats.characteristics}</b></span>
                    <span>model <b>{res.stats.model === "none" ? "none (deterministic)" : res.stats.model}</b></span>
                    <span>runtime <b>{res.stats.runtime_s}s</b></span>
                    <span>cost <b>${res.stats.cost_usd.toFixed(2)}</b></span>
                    {res.cad && <span>CAD <b>{res.cad.extents.map((v) => fmt(v, 2)).join(" × ")} mm</b></span>}
                    <span style={{ marginLeft: "auto" }}>{res.stats.engine_version}</span>
                    {rev && <span>checked {when(rev.finished)}</span>}
                </> : <span>{busy ? "checking…" : ""}</span>}
            </footer>
            {error && res && (
                <div className="in-scrim" onMouseDown={() => setError(null)} style={{ alignItems: "flex-end", background: "transparent", pointerEvents: "none" }}>
                    <div className="in-error" style={{ background: "#fff", pointerEvents: "auto" }}>{error} <button className="in-btn quiet sm" onClick={() => setError(null)}><X size={12} /></button></div>
                </div>
            )}
        </div>
    );
}

function ViewerBody({ view, rid, res, chars, sel, flagged, zoom, glbUrl, glbError, highlight, selected, focusBox, onSelect }: {
    view: View; rid: string; res: NonNullable<Revision["result"]>; chars: Characteristic[]; sel: number | null; flagged: Set<number>;
    zoom: number; glbUrl: string | null; glbError: string | null; highlight: string[]; selected: Characteristic | null;
    focusBox: { page: number; bbox: number[] } | null; onSelect: (no: number) => void;
}) {
    const drawing = <DrawingView rid={rid} pages={res.drawing.pages} chars={chars} selected={sel} flagged={flagged} zoom={zoom} focusBox={focusBox} onSelect={onSelect} />;
    const model = !res.has_glb ? (
        <div className="in-overlay-note">No 3D model was uploaded with this revision. Add a STEP file in a new revision to cross-check the drawing against it.</div>
    ) : glbUrl ? (
        <>
            <ModelPane url={glbUrl} highlight={highlight} />
            <div className="in-3d-legend">
                {selected ? <>
                    <b>#{selected.no}</b> {selected.designator}: {selected.cad_value !== null ? <>model <span className="mono">{fmt(selected.cad_value)}</span> ({CAD_WORD[selected.cad_status]})</> : CAD_WORD[selected.cad_status] || "—"}
                    {selected.cad_note && <div className="sub">{selected.cad_note}</div>}
                </> : <span className="sub">Select a characteristic to show the faces its model value came from.</span>}
            </div>
        </>
    ) : <div className="in-overlay-note">{glbError ?? "Loading the model…"}</div>;
    if (view === "drawing") return drawing;
    if (view === "model") return model;
    return <div className="in-split"><div>{drawing}</div><div>{model}</div></div>;
}

function CharTable({ chars, sel, flagged, signed, onSelect, onEdit, onlyOpen, setOnlyOpen }: {
    chars: Characteristic[]; sel: number | null; flagged: Set<number>; signed: boolean; onSelect: (no: number) => void;
    onEdit: (no: number, f: Partial<Characteristic>) => void; onlyOpen: boolean; setOnlyOpen: (v: boolean) => void;
}) {
    useEffect(() => {
        if (sel == null) return;
        document.querySelector(`tr[data-no="${sel}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, [sel]);
    return (
        <>
            <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--rule)", display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
                    <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Only characteristics still to inspect
                </label>
                <span className="mute" style={{ marginLeft: "auto" }}>Enter a result; pass or fail is computed from the limits.</span>
            </div>
            <table className="in-table in-chars">
                <thead><tr><th>#</th><th>Zone</th><th>Requirement</th><th>Limits</th><th>Source</th><th>CAD</th><th>Result</th><th>Status</th></tr></thead>
                <tbody>
                    {chars.map((c) => (
                        <tr key={c.no} data-no={c.no} aria-selected={sel === c.no} onClick={() => onSelect(c.no)} className="link">
                            <td><span className="in-num-balloon">{c.no}</span></td>
                            <td className="mono">{c.zone || `S${c.page + 1}`}</td>
                            <td>
                                <span className="req">{flagged.has(c.no) && <i className="sev critical" aria-label="has an open finding" style={{ marginRight: 4 }} />}{c.requirement}</span>
                                <span className="why mono">{c.designator}{c.tol_note ? `, ${c.tol_note}` : ""}</span>
                            </td>
                            <td className="mono" style={{ whiteSpace: "nowrap" }}>{limits(c) || (c.inspect ? <span className="mute">—</span> : <span className="mute">{c.type === "Basic" ? "basic" : "ref"}</span>)}</td>
                            <td><span className={`src${["selected_class", "none"].includes(c.tol_source) ? " weak" : ""}`}>{TOL_SOURCE[c.tol_source] ?? c.tol_source}{c.confidence !== "vector" ? `, ${c.confidence}` : ""}</span></td>
                            <td className="mono" style={{ whiteSpace: "nowrap" }} title={c.cad_note}>
                                {c.cad_status === "deviates" ? <><i className="sev critical" /> {fmt(c.cad_value)}</> :
                                 c.cad_status === "agrees" ? <><i className="sev ok" /> {fmt(c.cad_value)}</> :
                                 c.cad_status === "count" ? <><i className="sev major" /> {c.cad_count}X</> :
                                 c.cad_status === "not_found" ? <><i className="sev minor" /> none</> : <span className="mute">{CAD_WORD[c.cad_status] ?? ""}</span>}
                            </td>
                            <td onClick={(e) => e.stopPropagation()} style={{ minWidth: 86 }}>
                                {c.inspect ? (
                                    <input className="in-input cell" defaultValue={c.result} key={`${c.no}-${c.result}`} disabled={signed}
                                           aria-label={`Result for characteristic ${c.no}`} placeholder="—"
                                           onBlur={(e) => e.target.value !== c.result && onEdit(c.no, { result: e.target.value })}
                                           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
                                ) : <span className="mute">—</span>}
                            </td>
                            <td onClick={(e) => e.stopPropagation()}>
                                {c.inspect ? (
                                    <>
                                        <select className="in-select cell" value={c.status} disabled={signed} aria-label={`Status for characteristic ${c.no}`}
                                                onChange={(e) => onEdit(c.no, { status: e.target.value as CharStatus })}>
                                            <option value="open">open</option><option value="pass">pass</option><option value="fail">fail</option>
                                            <option value="accepted">accepted</option><option value="waived">waived</option>
                                        </select>
                                        {c.status === "fail" && (
                                            <input className="in-input cell" defaultValue={c.nc_number} key={`nc-${c.no}-${c.nc_number}`} disabled={signed}
                                                   placeholder="NCR no." aria-label={`Nonconformance number for ${c.no}`}
                                                   onBlur={(e) => e.target.value !== c.nc_number && onEdit(c.no, { nc_number: e.target.value })} />
                                        )}
                                    </>
                                ) : null}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
}

function Crop({ rid, page, bbox, pw }: { rid: string; page: number; bbox: number[]; pw: number }) {
    const img = useBlobUrl(pageUrl(rid, page, 130), "Loading the sheet");
    if (!img.url || bbox.length !== 4) return null;
    const pad = 28;
    const h = 120;
    const scale = h / (bbox[3] - bbox[1] + 2 * pad);          // css px per point
    return (
        <div className="in-crop" role="img" aria-label="Where this is on the drawing" style={{
            backgroundImage: `url(${img.url})`, backgroundSize: `${pw * scale}px auto`,
            backgroundPosition: `${-(bbox[0] - pad) * scale}px ${-(bbox[1] - pad) * scale}px`,
        }} />
    );
}

function FindingDrawer({ rid, f, res, signed, customer, onClose, onDecide, onEdit }: {
    rid: string; f: Finding; res: NonNullable<Revision["result"]>; signed: boolean; customer: string;
    onClose: () => void; onDecide: (f: Finding, d: Decision, forCustomer?: boolean) => void; onEdit: () => void;
}) {
    const page = f.page !== null ? res.drawing.pages[f.page] : null;
    return (
        <div className="in-drawer" aria-label="Finding detail">
            <header><i className={`sev ${f.severity}`} /><h3>{f.title}</h3>
                <span className="in-badge faint">{f.severity}</span>
                <button className="in-btn quiet sm" onClick={onClose} aria-label="Close"><X size={14} /></button></header>
            <div className="body">
                {page && f.page !== null && <Crop rid={rid} page={f.page} bbox={f.bbox} pw={page.w} />}
                {(f.drawing_value || f.cad_value) && (
                    <div className="in-vs">
                        <div><small>{f.kind === "bom" ? "Drawing" : "Drawing value"}</small><b>{f.drawing_value || "—"}</b></div>
                        <div><small>{f.kind === "bom" ? "BOM / PO" : f.kind === "cad" ? "CAD measured" : "Found"}</small><b>{f.cad_value || "—"}</b></div>
                    </div>
                )}
                <p style={{ margin: "0 0 10px" }}>{f.message}</p>
                <dl className="in-kv">
                    <dt>Rule</dt><dd className="mono">{f.rule}</dd>
                    {f.char_no && <><dt>Characteristic</dt><dd>#{f.char_no}</dd></>}
                    {f.query && <><dt>Query to customer</dt><dd>{f.query}</dd></>}
                    {f.decision && <><dt>Decision</dt><dd>{f.decision}{f.note ? `, ${f.note}` : ""}</dd></>}
                </dl>
                {!signed && (
                    <div className="in-actions">
                        <button className="in-btn sm" onClick={() => onDecide(f, "accepted")}>Accept</button>
                        {f.char_no && <button className="in-btn line sm" onClick={onEdit}>Edit characteristic</button>}
                        <button className="in-btn line sm" onClick={() => onDecide(f, "rejected")}>Reject</button>
                        <button className="in-btn line sm" disabled={!customer} title={customer ? "" : "Set the project's customer first"}
                                onClick={() => onDecide(f, "ignored", true)}>Ignore for {customer || "this customer"}</button>
                        {f.decision && <button className="in-btn quiet sm" onClick={() => onDecide(f, "")}>Reopen</button>}
                    </div>
                )}
            </div>
        </div>
    );
}

function pct(v: number | null) {
    return v === null ? "–" : `${Math.round(v * 100)}%`;
}

/** The drawing reader scored against the model's own semantic PMI (STEP AP242). */
function AccuracyPanel({ acc, onSelect, vision }: { acc: NonNullable<Revision["result"]>["accuracy"] & object; onSelect: (no: number) => void; vision: NonNullable<Revision["result"]>["vision"] }) {
    const GLYPH = { matched: "ok", partial: "major", missed: "critical" } as const;
    return (
        <div>
            <div style={{ padding: 14, borderBottom: "1px solid var(--rule)" }}>
                <p className="sub" style={{ margin: "0 0 10px", fontSize: 12 }}>
                    Every dimension and tolerance stored as semantic PMI in <span className="mono">{acc.key_source}</span> is the answer key.
                    Each one is looked for among the characteristics read from the drawing{vision ? `, with ${vision.model} reading sheets that have no text` : " (text layer only, no reading model)"}.
                </p>
                <div className="in-vs" style={{ gridTemplateColumns: "1fr 1fr 1fr", marginBottom: 0 }}>
                    <div><small>Read exactly</small><b>{pct(acc.recall)}</b><small>{acc.matched} of {acc.total}</small></div>
                    <div><small>Read, detail differs</small><b>{pct(acc.recall_with_partial)}</b><small>+{acc.partial} partial</small></div>
                    <div><small>Precision</small><b>{pct(acc.precision)}</b><small>{acc.extra.length} not in the key</small></div>
                </div>
            </div>
            <table className="in-table in-chars">
                <thead><tr><th></th><th>In the model (answer key)</th><th>Read from the drawing</th><th>#</th></tr></thead>
                <tbody>
                    {acc.rows.map((r, i) => (
                        <tr key={i} className={r.char_no ? "link" : ""} onClick={() => r.char_no && onSelect(r.char_no)}>
                            <td><i className={`sev ${GLYPH[r.status]}`} aria-label={r.status} /></td>
                            <td className="mono">{r.key}</td>
                            <td className="mono">{r.read || <span className="mute">not read</span>}</td>
                            <td>{r.char_no ? <span className="in-num-balloon">{r.char_no}</span> : null}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <p className="sub" style={{ padding: "8px 14px", fontSize: 12 }}>✓ value and tolerance read; □ value read, tolerance or symbol differs; ■ not read</p>
        </div>
    );
}

const F1_EDITABLE: [string, string][] = [
    ["serial_number", "Serial number"], ["fai_report_number", "FAI report number"], ["po_number", "PO number"],
    ["organization", "Organization name"], ["supplier_code", "Supplier code"], ["process_reference", "Manufacturing process reference"],
    ["fai_type", "Detail or assembly FAI"], ["reason", "Reason for FAI"], ["additional_changes", "Additional changes"],
];

function Forms({ rev }: { rev: Revision }) {
    const res = rev.result!;
    const f1 = res.forms.form1;
    return (
        <div>
            <h3 className="in-side-h" style={{ padding: "12px 14px 0" }}>Form 1 — Part number accountability</h3>
            <table className="in-table" style={{ margin: "8px 0 0" }}>
                <tbody>
                    {Object.entries(f1).filter(([k]) => !k.startsWith("signed")).map(([k, v]) => (
                        <tr key={k}><td className="sub" style={{ width: "42%" }}>{k.replace(/_/g, " ").replace(/^./, (s) => s.toUpperCase())}</td><td>{v || <span className="mute">—</span>}</td></tr>
                    ))}
                </tbody>
            </table>
            <h3 className="in-side-h" style={{ padding: "18px 14px 0" }}>Form 2 — Product accountability</h3>
            <table className="in-table" style={{ marginTop: 8 }}>
                <thead><tr><th>Type</th><th>Material or process</th><th>Specification</th><th>Read from</th></tr></thead>
                <tbody>
                    {res.forms.form2.length ? res.forms.form2.map((r, i) => (
                        <tr key={i}><td>{r.type}</td><td>{r.name}</td><td className="mono">{r.specification || "—"}</td><td className="sub">{r.source}</td></tr>
                    )) : <tr><td colSpan={4} className="sub">No materials or special processes stated on the drawing.</td></tr>}
                    <tr><td>Functional test</td><td colSpan={3} className="sub">None identified on the drawing</td></tr>
                </tbody>
            </table>
            <p className="sub" style={{ padding: "8px 14px", fontSize: 12 }}>Certificates, supplier codes and approvals are added on the Sign tab or in the exported workbook.</p>
        </div>
    );
}

function SignPanel({ rev, onDone, onError }: { rev: Revision; onDone: () => void; onError: (s: string) => void }) {
    const res = rev.result!;
    const ready = rev.readiness;
    const [f1, setF1] = useState<Record<string, string>>(() => Object.fromEntries(F1_EDITABLE.map(([k]) => [k, res.forms.form1[k] ?? ""])));
    const [name, setName] = useState("");
    const [role, setRole] = useState("Quality engineer");
    const [busy, setBusy] = useState(false);
    const signed = rev.signoff;
    const stem = `${rev.project?.part_number || "FAI"}_rev${rev.label || ""}`;

    async function saveF1() {
        try { await updateForm1(rev.id, f1); onDone(); } catch (e) { onError((e as Error).message); }
    }
    async function sign() {
        setBusy(true);
        try { await updateForm1(rev.id, f1); await signRevision(rev.id, name, role); onDone(); }
        catch (e) { onError((e as Error).message); }
        finally { setBusy(false); }
    }
    const exports = (
        <div className="in-actions">
            <button className="in-btn line sm" onClick={() => download(fileUrl(rev.id, "fai.xlsx"), `${stem}_AS9102.xlsx`)}><Download size={13} /> Forms 1–3 (Excel)</button>
            <button className="in-btn line sm" onClick={() => download(fileUrl(rev.id, "fai.pdf"), `${stem}_AS9102.pdf`)}><Download size={13} /> Forms 1–3 (PDF)</button>
            <button className="in-btn line sm" onClick={() => download(fileUrl(rev.id, "ballooned.pdf"), `${stem}_ballooned.pdf`)}><Download size={13} /> Ballooned drawing</button>
        </div>
    );
    if (signed) {
        return (
            <div className="in-sign">
                <div className="stamp">
                    SIGNED {signed.at}<br />{signed.name}, {signed.role}<br />{signed.fai_scope}
                    {signed.open_characteristics.length > 0 && <><br />Not inspected: #{signed.open_characteristics.join(", #")}</>}
                </div>
                <p className="sub">This revision is frozen. Changes need a new revision.</p>
                {exports}
            </div>
        );
    }
    return (
        <div>
            <div className="in-sign">
                <h3>Before you sign</h3>
                <ul>
                    <li>{ready?.undecided_critical.length ? <>■ {ready.undecided_critical.length} critical finding(s) need a decision</> : <>✓ every critical finding is decided</>}</li>
                    <li>{ready?.failed_without_nc.length ? <>■ failed characteristic(s) #{ready.failed_without_nc.join(", #")} need a nonconformance number</> : <>✓ every failure has a nonconformance number</>}</li>
                    <li>{ready?.open_characteristics.length ? <>□ {ready.open_characteristics.length} characteristic(s) have no result: signing records a partial FAI</> : <>✓ every characteristic has a result: full FAI</>}</li>
                </ul>
                <div className="in-row">
                    <label className="in-field"><span>Signed by</span><input className="in-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" /></label>
                    <label className="in-field"><span>Role</span><input className="in-input" value={role} onChange={(e) => setRole(e.target.value)} /></label>
                </div>
                <button className="in-btn block" disabled={!ready?.can_sign || !name.trim() || busy} onClick={sign}>{busy ? "Signing…" : "Sign and freeze this revision"}</button>
            </div>
            <h3 className="in-side-h" style={{ padding: "4px 14px 0" }}>Form 1 details</h3>
            <div className="in-form1">
                {F1_EDITABLE.map(([k, label]) => (
                    <label key={k} className="in-field"><span>{label}</span>
                        <input className="in-input" value={f1[k]} onChange={(e) => setF1({ ...f1, [k]: e.target.value })} onBlur={saveF1} /></label>
                ))}
            </div>
            <div style={{ padding: "0 14px 16px" }}>
                <h3 className="in-side-h">Draft exports</h3>
                <p className="sub" style={{ fontSize: 12, marginTop: 0 }}>Stamped DRAFT until signed.</p>
                {exports}
            </div>
        </div>
    );
}
