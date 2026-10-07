/** ⌘K: jump to any part or instance. Enter selects it everywhere and frames it. */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ModelGraph } from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

interface Item {
    kind: 'part' | 'instance';
    id: string;
    name: string;
    path: string;
}

export default function CommandPalette({ graph, onClose, onPick }: { graph: ModelGraph; onClose: () => void; onPick?: () => void }) {
    const [q, setQ] = useState('');
    const [cursor, setCursor] = useState(0);
    const select = useReview((s) => s.select);
    const input = useRef<HTMLInputElement>(null);
    const list = useRef<HTMLUListElement>(null);

    const items = useMemo<Item[]>(() => {
        const count = new Map<string, number>();
        for (const i of graph.instances) count.set(i.part_id, (count.get(i.part_id) ?? 0) + 1);
        return [
            ...graph.parts.map((p) => ({ kind: 'part' as const, id: p.id, name: p.name, path: `×${count.get(p.id) ?? 0}` })),
            ...graph.instances.map((i) => ({ kind: 'instance' as const, id: i.id, name: i.name, path: `${i.id} · ${i.path}` })),
        ];
    }, [graph]);

    const shown = useMemo(() => {
        const t = q.trim().toLowerCase();
        if (!t) return items.slice(0, 60);
        return items.filter((it) => it.name.toLowerCase().includes(t) || it.id.toLowerCase() === t).slice(0, 60);
    }, [items, q]);

    useEffect(() => input.current?.focus(), []);
    useEffect(() => setCursor(0), [q]);
    useEffect(() => {
        list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    }, [cursor]);

    const choose = (it: Item | undefined) => {
        if (!it) return;
        select({ kind: it.kind, id: it.id }, true);
        onPick?.();
        onClose();
    };

    return (
        <div className="rv-palette-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
            <div className="rv-palette" role="dialog" aria-label="Search">
                <input
                    ref={input}
                    value={q}
                    placeholder="Jump to a part or instance"
                    aria-label="Search parts and instances"
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Escape') onClose();
                        else if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, shown.length - 1)); }
                        else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
                        else if (e.key === 'Enter') choose(shown[cursor]);
                    }}
                />
                <ul ref={list} role="listbox">
                    {shown.map((it, k) => (
                        <li key={`${it.kind}:${it.id}`} role="option" aria-selected={k === cursor}
                            onMouseEnter={() => setCursor(k)} onMouseDown={() => choose(it)}>
                            <span className="kind">{it.kind}</span>
                            <span>{it.name}</span>
                            <span className="path">{it.path}</span>
                        </li>
                    ))}
                    {!shown.length && <li className="muted">Nothing matches.</li>}
                </ul>
            </div>
        </div>
    );
}
