/**
 * Product tree: the assembly as the STEP file structures it.
 *
 * Two views of the same graph. "Structure" is the file's own tree, one row per
 * placed copy. "Parts" groups copies under their definition with a count, the
 * way a BOM reads (8 × CBSTNR2-5) — selecting a part there selects all of its
 * copies everywhere.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import type { GraphInstance, GraphPart, TreeNode } from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

interface Props {
    tree: TreeNode;
    parts: GraphPart[];
    instances: GraphInstance[];
}

function leaves(n: TreeNode, out: string[] = []): string[] {
    if (n.instance) out.push(n.instance);
    for (const c of n.children) leaves(c, out);
    return out;
}

function matches(n: TreeNode, q: string): boolean {
    if (!q) return true;
    if (n.name.toLowerCase().includes(q)) return true;
    return n.children.some((c) => matches(c, q));
}

export default function ProductTree({ tree, parts, instances }: Props) {
    const [mode, setMode] = useState<'structure' | 'parts'>('parts');
    const [q, setQ] = useState('');
    const [open, setOpen] = useState<Set<string>>(() => new Set([tree.key]));
    const selection = useReview((s) => s.selection);
    const hidden = useReview((s) => s.hidden);
    const select = useReview((s) => s.select);
    const hover = useReview((s) => s.hover);
    const toggleHidden = useReview((s) => s.toggleHidden);
    const listRef = useRef<HTMLDivElement>(null);
    const query = q.trim().toLowerCase();

    const byPart = useMemo(() => {
        const m = new Map<string, string[]>();
        for (const i of instances) m.set(i.part_id, [...(m.get(i.part_id) ?? []), i.id]);
        return m;
    }, [instances]);
    const instById = useMemo(() => new Map(instances.map((i) => [i.id, i])), [instances]);

    // reveal the selection: open its ancestors and scroll it into view
    useEffect(() => {
        if (!selection) return;
        if (selection.kind === 'instance') {
            const inst = instById.get(selection.id);
            if (inst?.parent) {
                const segs = inst.parent.split('/');
                setOpen((o) => {
                    const n = new Set(o);
                    segs.forEach((_, k) => n.add(segs.slice(0, k + 1).join('/')));
                    return n;
                });
            }
            if (mode === 'parts' && inst) setOpen((o) => new Set(o).add(`part:${inst.part_id}`));
        }
        requestAnimationFrame(() => {
            listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
        });
    }, [selection, instById, mode]);

    const isSel = (kind: 'instance' | 'part', id: string) => selection?.kind === kind && selection.id === id;
    const shown = instances.length - hidden.size;

    const eye = (ids: string[]) => {
        const off = ids.length > 0 && ids.every((i) => hidden.has(i));
        return (
            <button
                className="icon-btn"
                data-hidden={off}
                title={off ? 'Show' : 'Hide'}
                aria-label={off ? 'Show' : 'Hide'}
                onClick={(e) => {
                    e.stopPropagation();
                    toggleHidden(ids);
                }}
            >
                {off ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
        );
    };

    const renderNode = (n: TreeNode, depth: number): React.ReactNode => {
        if (!matches(n, query)) return null;
        const pad = { paddingLeft: 6 + depth * 14 };
        if (n.instance) {
            const id = n.instance;
            return (
                <div
                    key={n.key}
                    className={`rv-node${hidden.has(id) ? ' is-hidden' : ''}`}
                    style={pad}
                    role="treeitem"
                    aria-selected={isSel('instance', id)}
                    onClick={() => select({ kind: 'instance', id })}
                    onDoubleClick={() => select({ kind: 'instance', id }, true)}
                    onMouseEnter={() => hover(id)}
                    onMouseLeave={() => hover(null)}
                >
                    <span className="twisty" />
                    <span className="nm" title={n.key}>{n.name}</span>
                    {eye([id])}
                </div>
            );
        }
        const isOpen = open.has(n.key) || !!query;
        const ids = leaves(n);
        return (
            <div key={n.key || 'root'} role="group">
                <div
                    className="rv-node"
                    style={pad}
                    role="treeitem"
                    aria-expanded={isOpen}
                    onClick={() => setOpen((o) => { const s = new Set(o); if (s.has(n.key)) s.delete(n.key); else s.add(n.key); return s; })}
                >
                    <span className="twisty">{isOpen ? '▾' : '▸'}</span>
                    <span className="nm" style={{ fontWeight: 500 }}>{n.name}</span>
                    <span className="ct">{ids.length}</span>
                    {eye(ids)}
                </div>
                {isOpen && n.children.map((c) => renderNode(c, depth + 1))}
            </div>
        );
    };

    const partRows = [...parts]
        .filter((p) => !query || p.name.toLowerCase().includes(query))
        .sort((a, b) => (byPart.get(b.id)?.length ?? 0) - (byPart.get(a.id)?.length ?? 0) || a.name.localeCompare(b.name));

    return (
        <aside className="rv-tree" aria-label="Product tree">
            <div className="rv-panel-head">
                <span className="label">Product</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
                    <button className="btn btn--ghost" aria-pressed={mode === 'parts'} onClick={() => setMode('parts')}
                        style={mode === 'parts' ? { borderColor: 'var(--text)' } : undefined}>Parts</button>
                    <button className="btn btn--ghost" aria-pressed={mode === 'structure'} onClick={() => setMode('structure')}
                        style={mode === 'structure' ? { borderColor: 'var(--text)' } : undefined}>Structure</button>
                </span>
            </div>
            <div className="rv-tree__filter">
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter parts" aria-label="Filter parts" />
            </div>
            <div className="rv-tree__list" ref={listRef} role="tree">
                {mode === 'structure' && renderNode(tree, 0)}
                {mode === 'parts' && partRows.map((p) => {
                    const ids = byPart.get(p.id) ?? [];
                    const key = `part:${p.id}`;
                    const isOpen = open.has(key);
                    return (
                        <div key={p.id} role="group">
                            <div
                                className={`rv-node${ids.every((i) => hidden.has(i)) ? ' is-hidden' : ''}`}
                                style={{ paddingLeft: 6 }}
                                role="treeitem"
                                aria-selected={isSel('part', p.id)}
                                onClick={() => select({ kind: 'part', id: p.id })}
                                onDoubleClick={() => select({ kind: 'part', id: p.id }, true)}
                            >
                                <span
                                    className="twisty"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setOpen((o) => { const s = new Set(o); if (s.has(key)) s.delete(key); else s.add(key); return s; });
                                    }}
                                >
                                    {ids.length > 1 ? (isOpen ? '▾' : '▸') : ''}
                                </span>
                                <span className="nm" title={p.name}>{p.name}</span>
                                <span className="ct">×{ids.length}</span>
                                {eye(ids)}
                            </div>
                            {isOpen && ids.length > 1 && ids.map((id, k) => (
                                <div
                                    key={id}
                                    className={`rv-node${hidden.has(id) ? ' is-hidden' : ''}`}
                                    style={{ paddingLeft: 34 }}
                                    role="treeitem"
                                    aria-selected={isSel('instance', id)}
                                    onClick={() => select({ kind: 'instance', id })}
                                    onDoubleClick={() => select({ kind: 'instance', id }, true)}
                                    onMouseEnter={() => hover(id)}
                                    onMouseLeave={() => hover(null)}
                                >
                                    <span className="nm muted">copy {k + 1}</span>
                                    <span className="ct">{id}</span>
                                    {eye([id])}
                                </div>
                            ))}
                        </div>
                    );
                })}
            </div>
            <div className="rv-tree__foot">
                <span>{shown}/{instances.length} shown</span>
                <span>{parts.length} parts</span>
            </div>
        </aside>
    );
}
