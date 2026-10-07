/**
 * Contacts drawer under the viewer: every touching pair with its type and the
 * measured minimum distance. Clicking a row selects the contact (both parts),
 * frames it, and the Inspector shows the fit.
 */
import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { GraphContact, GraphInstance } from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const TYPES = ['all', 'cylindrical', 'coaxial-hole', 'planar', 'point'] as const;

export default function ContactsDrawer({ contacts, instances }: { contacts: GraphContact[]; instances: Map<string, GraphInstance> }) {
    const [open, setOpen] = useState(false);
    const [type, setType] = useState<(typeof TYPES)[number]>('all');
    const selection = useReview((s) => s.selection);
    const select = useReview((s) => s.select);
    const setShowContacts = useReview((s) => s.setShowContacts);

    // rows touching the selected instance/part first, so the drawer follows the selection
    const rows = useMemo(() => {
        const sel = new Set<string>();
        if (selection?.kind === 'instance') sel.add(selection.id);
        if (selection?.kind === 'part') for (const i of instances.values()) if (i.part_id === selection.id) sel.add(i.id);
        const list = contacts.filter((c) => type === 'all' || c.type === type);
        if (!sel.size) return list;
        return [...list.filter((c) => sel.has(c.a) || sel.has(c.b)), ...list.filter((c) => !(sel.has(c.a) || sel.has(c.b)))];
    }, [contacts, type, selection, instances]);

    const name = (id: string) => instances.get(id)?.name ?? id;
    const counts = useMemo(() => {
        const m: Record<string, number> = {};
        for (const c of contacts) m[c.type] = (m[c.type] ?? 0) + 1;
        return m;
    }, [contacts]);

    return (
        <section style={{ borderTop: '1px solid var(--line)', background: 'var(--bg)', flex: 'none', display: 'flex', flexDirection: 'column', height: open ? 300 : 36, overflow: 'hidden' }}>
            <div className="rv-panel-head" style={{ cursor: 'pointer', position: 'static' }} onClick={() => { setOpen(!open); if (!open) setShowContacts(true); }}>
                <span className="label">Contacts</span>
                <span className="mono muted" style={{ fontSize: 11 }}>
                    {contacts.length} pairs · {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(' · ')}
                </span>
                <span style={{ marginLeft: 'auto' }}>{open ? <ChevronDown size={15} /> : <ChevronUp size={15} />}</span>
            </div>
            {open && (
                <>
                    <div style={{ display: 'flex', gap: 2, padding: '6px 8px', borderBottom: '1px solid var(--line)' }}>
                        {TYPES.map((t) => (
                            <button key={t} className="btn btn--ghost" aria-pressed={type === t} onClick={() => setType(t)}
                                style={type === t ? { borderColor: 'var(--text)' } : undefined}>
                                {t}{t !== 'all' && counts[t] ? ` ${counts[t]}` : ''}
                            </button>
                        ))}
                    </div>
                    <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
                        <table className="rv-table">
                            <thead>
                                <tr><th>Part A</th><th>Part B</th><th>Type</th><th>Detail</th><th className="num">Min distance</th></tr>
                            </thead>
                            <tbody>
                                {rows.map((c) => {
                                    const f = c.fits[0];
                                    const active = selection?.kind === 'contact' && selection.id === c.id;
                                    return (
                                        <tr key={c.id} data-click className={active ? 'is-sel' : undefined}
                                            onClick={() => select({ kind: 'contact', id: c.id }, true)}>
                                            <td>{name(c.a)}</td>
                                            <td>{name(c.b)}</td>
                                            <td className="mono" style={{ fontSize: 11 }}>{c.kinds.join(' + ')}</td>
                                            <td className="mono" style={{ fontSize: 11 }}>
                                                {f ? `Ø${f.hole_diameter.toFixed(2)} hole / Ø${f.shaft_diameter.toFixed(2)} shaft · ${f.clearance.toFixed(2)} clr`
                                                    : c.coaxial_holes[0] ? `Ø${c.coaxial_holes[0].diameter_a.toFixed(2)} ↔ Ø${c.coaxial_holes[0].diameter_b.toFixed(2)} coaxial`
                                                    : c.planes.length ? `${c.planes.length} plane${c.planes.length > 1 ? 's' : ''}` : ''}
                                            </td>
                                            <td className="num" title="exact BRepExtrema distance">{c.min_distance === null ? 'box only' : `${c.min_distance.toFixed(3)} mm`}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </section>
    );
}
