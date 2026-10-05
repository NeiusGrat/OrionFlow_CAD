/**
 * The drawing, sheet by sheet, with numbered balloons over each characteristic.
 *
 * Balloon positions are the server's (page points), the same ones written into
 * the ballooned PDF export, so the screen and the paper never disagree. Sheets
 * are drawn as images at a fixed DPI and scaled with CSS, so overlay
 * coordinates are simple percentages of the page size.
 */
import { useEffect, useRef } from "react";
import { useBlobUrl } from "../../lib/watchdog";
import { pageUrl, type Characteristic } from "../../services/faiApi";

export interface Mark {
    page: number;
    bbox: number[];
    label: string;
    kind: string;   // css modifier
}

interface Props {
    rid: string;
    pages: { w: number; h: number }[];
    chars?: Characteristic[];
    selected?: number | null;
    flagged?: Set<number>;
    focusBox?: { page: number; bbox: number[] } | null;
    marks?: Mark[];
    zoom: number;
    onSelect?: (no: number) => void;
}

function Sheet({ rid, index, page, chars, selected, flagged, focusBox, marks, zoom, onSelect }: Omit<Props, "pages"> & {
    index: number; page: { w: number; h: number };
}) {
    const img = useBlobUrl(pageUrl(rid, index, 130), "Loading the sheet");
    const ref = useRef<HTMLDivElement>(null);
    const pct = (v: number, of: number) => `${(v / of) * 100}%`;

    // bring the selected balloon into view
    useEffect(() => {
        if (selected == null || !ref.current) return;
        const el = ref.current.querySelector<HTMLElement>(`[data-no="${selected}"]`);
        el?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    }, [selected, img.url]);

    return (
        <div ref={ref} className="in-sheet" style={{ width: `${zoom * 100}%`, aspectRatio: `${page.w} / ${page.h}` }}>
            <span className="sheet-no">Sheet {index + 1}</span>
            {img.url ? <img src={img.url} alt={`Drawing sheet ${index + 1}`} draggable={false} /> :
                <div className="in-overlay-note">{img.error ?? "Loading sheet…"}</div>}
            {img.url && focusBox && focusBox.page === index && focusBox.bbox.length === 4 && (
                <div className="in-callout" style={{
                    left: pct(focusBox.bbox[0] - 3, page.w), top: pct(focusBox.bbox[1] - 3, page.h),
                    width: pct(focusBox.bbox[2] - focusBox.bbox[0] + 6, page.w), height: pct(focusBox.bbox[3] - focusBox.bbox[1] + 6, page.h),
                }} />
            )}
            {img.url && (marks ?? []).filter((m) => m.page === index && m.bbox.length === 4).map((m, i) => (
                <div key={i} className={`in-mark-box ${m.kind}`} style={{
                    left: pct(m.bbox[0] - 3, page.w), top: pct(m.bbox[1] - 3, page.h),
                    width: pct(m.bbox[2] - m.bbox[0] + 6, page.w), height: pct(m.bbox[3] - m.bbox[1] + 6, page.h),
                }}><span>{m.label}</span></div>
            ))}
            {img.url && (chars ?? []).filter((c) => c.page === index && c.balloon.length === 2).map((c) => (
                <button key={c.no} data-no={c.no} className={`in-balloon${flagged?.has(c.no) ? " flag" : ""}`}
                        aria-pressed={selected === c.no} aria-label={`Characteristic ${c.no}: ${c.requirement}`}
                        title={`${c.no}. ${c.requirement}`}
                        style={{ left: pct(c.balloon[0], page.w), top: pct(c.balloon[1], page.h) }}
                        onClick={() => onSelect?.(c.no)}>
                    {c.no}
                </button>
            ))}
        </div>
    );
}

export default function DrawingView(props: Props) {
    return (
        <div className="in-sheets">
            {props.pages.map((p, i) => <Sheet key={i} {...props} index={i} page={p} />)}
        </div>
    );
}
