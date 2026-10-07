/**
 * BOM lens: every BOM row next to the CAD part it was matched to, how it was
 * matched, and whether the quantities agree. The engineer can pair, unpair or
 * hand a row back to automatic matching; every change re-runs the checks on
 * the server (no geometry is recomputed) and the findings update.
 */
import { useMemo, useState } from 'react';
import {
    clearBomLink, downloadBom, setBomLink, fmtNum,
    type BomPayload, type BomRow,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const METHOD_TITLE: Record<string, string> = {
    exact: 'Part number, name or file name equals the CAD part name',
    fuzzy: 'Near-identical name (rapidfuzz ≥ 90, clear margin)',
    ai: 'Matched by AI from the leftovers — confirm',
    human: 'Paired by an engineer',
    none: 'No CAD part',
};

function Method({ m, c }: { m: BomRow['method']; c: number }) {
    return (
        <span className="mono" title={METHOD_TITLE[m]}
            style={{ fontSize: 10.5, letterSpacing: '.06em', textTransform: 'uppercase', border: m === 'none' ? '1px dashed var(--line-2)' : '1px solid var(--line-2)',
                padding: '1px 5px', color: m === 'none' ? 'var(--muted)' : 'var(--text)', fontWeight: m === 'human' ? 600 : 400 }}>
            {m}{m === 'fuzzy' || m === 'ai' ? ` ${Math.round(c * 100)}` : ''}
        </span>
    );
}

export default function BomLens({ rid, data, onChanged, filename }: {
    rid: string;
    data: BomPayload;
    onChanged: (b: BomPayload) => void;
    filename: string;
}) {
    const [busy, setBusy] = useState<string>('');
    const [error, setError] = useState('');
    const select = useReview((s) => s.select);
    const selection = useReview((s) => s.selection);
    const parts = useMemo(() => new Map(data.parts.map((p) => [p.id, p])), [data.parts]);

    // summed BOM quantity per CAD part (rows naming one part add up)
    const bomQty = useMemo(() => {
        const m = new Map<string, number>();
        for (const r of data.rows) if (r.part_id && r.method !== 'none' && r.quantity !== null) m.set(r.part_id, (m.get(r.part_id) ?? 0) + r.quantity);
        return m;
    }, [data.rows]);

    const act = async (key: string, fn: () => Promise<BomPayload>) => {
        setBusy(key);
        setError('');
        try {
            onChanged(await fn());
        } catch (e) {
            setError(String((e as Error).message));
        } finally {
            setBusy('');
        }
    };

    const matched = data.rows.filter((r) => r.part_id && r.method !== 'none');
    const unmatchedRows = data.rows.filter((r) => !r.part_id || r.method === 'none');
    const unmatchedParts = data.parts.filter((p) => !p.rows.length);
    const qtyOff = data.parts.filter((p) => p.rows.length && bomQty.has(p.id) && Math.abs((bomQty.get(p.id) ?? 0) - p.count) > 1e-6);
    const ai = data.rows.filter((r) => r.method === 'ai');
    const freeParts = data.parts.slice().sort((a, b) => (a.rows.length - b.rows.length) || a.name.localeCompare(b.name));

    const picker = (r: BomRow) => (
        <select
            value={r.part_id && r.method !== 'none' ? r.part_id : ''}
            disabled={!!busy}
            aria-label={`CAD part for BOM row ${r.row}`}
            onChange={(e) => act(r.key, () => setBomLink(rid, r.key, e.target.value || null))}
            style={{ maxWidth: 260 }}
        >
            <option value="">— no CAD part —</option>
            {freeParts.map((p) => (
                <option key={p.id} value={p.id}>{p.name}{p.rows.length ? '' : '  (unmatched)'}</option>
            ))}
        </select>
    );

    if (!data.rows.length) {
        return (
            <div className="rv-page" style={{ background: 'var(--bg)' }}>
                <div className="rv-empty" style={{ marginTop: 60 }}>
                    <b>No BOM in this revision</b>Add a BOM (CSV, XLSX or Markdown table) to the revision to reconcile it with the CAD.
                </div>
            </div>
        );
    }

    return (
        <div className="rv-page" style={{ background: 'var(--bg)' }}>
            <div style={{ position: 'sticky', top: 0, zIndex: 2, background: 'var(--bg)', borderBottom: '1px solid var(--line)', padding: '10px 16px', display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                <span className="label">BOM ↔ CAD</span>
                <span className="mono" style={{ fontSize: 12 }}>
                    {matched.length}/{data.rows.length} rows matched · <b>{qtyOff.length}</b> quantity differences · <b>{unmatchedRows.length}</b> rows without a part · <b>{unmatchedParts.length}</b> parts without a row
                </span>
                {ai.length > 0 && (
                    <button className="btn" disabled={!!busy}
                        onClick={async () => { for (const r of ai) await act(r.key, () => setBomLink(rid, r.key, r.part_id)); }}>
                        Confirm {ai.length} AI matches
                    </button>
                )}
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                    <button className="btn" onClick={() => downloadBom(rid, 'csv', `${filename}.csv`).catch((e) => setError(String(e.message)))}>Export CSV</button>
                    <button className="btn" onClick={() => downloadBom(rid, 'xlsx', `${filename}.xlsx`).catch((e) => setError(String(e.message)))}>Export XLSX</button>
                </span>
            </div>
            {error && <p className="rv-err" style={{ margin: '10px 16px' }}>{error}</p>}
            {data.files.map((f) => (
                <p key={f.file} className="mono muted" style={{ fontSize: 11, margin: '10px 16px 0' }}>
                    {f.file}: header on row {f.header_row} · {f.rows} rows read{f.skipped ? ` · ${f.skipped} note row skipped` : ''} · columns{' '}
                    {Object.entries(f.columns).map(([k, v]) => `${k} = "${v}"`).join(', ')}
                </p>
            ))}

            <div style={{ padding: '6px 16px 40px' }}>
                <table className="rv-table" style={{ marginTop: 10 }}>
                    <thead>
                        <tr>
                            <th className="num">#</th><th>BOM</th><th>Match</th><th>CAD part</th>
                            <th className="num">BOM qty</th><th className="num">CAD qty</th><th></th>
                            <th>Material</th><th>Process</th><th className="num">Unit mass</th><th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {data.rows.map((r) => {
                            const p = r.part_id && r.method !== 'none' ? parts.get(r.part_id) : undefined;
                            const sum = p ? bomQty.get(p.id) ?? 0 : 0;
                            const off = p && r.quantity !== null && Math.abs(sum - p.count) > 1e-6;
                            const sel = selection?.kind === 'part' && p && selection.id === p.id;
                            return (
                                <tr key={r.key} data-click className={sel ? 'is-sel' : undefined}
                                    onClick={(e) => { if ((e.target as HTMLElement).tagName !== 'SELECT' && (e.target as HTMLElement).tagName !== 'BUTTON' && p) select({ kind: 'part', id: p.id }); }}>
                                    <td className="num muted">{r.row}</td>
                                    <td>
                                        <span className="mono" style={{ fontSize: 12 }}>{r.part_number || '—'}</span>
                                        {r.name && r.name !== r.part_number && <div className="muted" style={{ fontSize: 12 }}>{r.name}</div>}
                                    </td>
                                    <td><Method m={r.method} c={r.confidence} /></td>
                                    <td>{picker(r)}</td>
                                    <td className="num">{r.quantity ?? '—'}{p && sum !== r.quantity && r.quantity !== null ? <span className="muted"> (Σ {sum})</span> : ''}</td>
                                    <td className="num">{p ? p.count : '—'}</td>
                                    <td>{p ? <span className={`sev ${off ? 'sev--major' : 'sev--pass'}`} aria-label={off ? 'quantity differs' : 'quantity agrees'} /> : <span className="sev sev--notrun" aria-label="unmatched" />}</td>
                                    <td style={{ fontSize: 12 }} title={r.density_note}>{r.material || '—'}</td>
                                    <td style={{ fontSize: 12 }}>{r.process ?? '—'}</td>
                                    <td className="num" title={p?.mass ? `volume ${fmtNum(p.volume / 1000, 3)} cm³ × ${r.density} kg/m³` : r.density_note}>
                                        {p?.mass ? `${fmtNum(p.mass * 1000, 2)} g` : '—'}
                                    </td>
                                    <td>
                                        {r.method === 'human' && (
                                            <button className="btn btn--ghost" disabled={!!busy} title="Back to automatic matching"
                                                onClick={() => act(r.key, () => clearBomLink(rid, r.key))}>auto</button>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>

                {unmatchedParts.length > 0 && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">CAD parts with no BOM row</span>
                        <table className="rv-table" style={{ marginTop: 6 }}>
                            <tbody>
                                {unmatchedParts.map((p) => (
                                    <tr key={p.id} data-click className={selection?.kind === 'part' && selection.id === p.id ? 'is-sel' : undefined}
                                        onClick={() => select({ kind: 'part', id: p.id }, true)}>
                                        <td><span className="sev sev--major" /> {p.name}</td>
                                        <td className="num">{p.count} in CAD</td>
                                        <td className="muted" style={{ fontSize: 12 }}>Pair it from the BOM row's picker above, or add it to the BOM.</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                )}
            </div>
        </div>
    );
}
