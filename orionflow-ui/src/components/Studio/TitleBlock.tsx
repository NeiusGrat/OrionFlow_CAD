import { useDesignStore } from "../../store/designStore";
import { useStudioStore } from "../../store/studioStore";
import { useLibraryStore } from "../../store/libraryStore";

/**
 * The status bar as a drawing title block.
 *
 * Every engineering drawing carries one: fielded cells in the corner naming
 * the part, the scale, the units, the revision and who signed it off. This is
 * that block, and every cell is a number the system actually holds — the
 * revision counter is the position in the undo stack, the verdict is the one
 * the verifier returned, the extent is what the kernel measured. Nothing here
 * is decoration standing in for data.
 *
 * Cells appear only when they have something to report. A title block with
 * "VOLUME —" in it teaches the reader to stop looking at the row.
 */

function Cell({ k, v, tone }: { k: string; v: string; tone?: string }) {
    return (
        <div className="of-tb-cell">
            <span className="of-tb-key">{k}</span>
            <span className="of-tb-val" style={tone ? { color: tone } : undefined}>
                {v}
            </span>
        </div>
    );
}

const VERDICT_TONE: Record<string, string> = {
    verified: "var(--st-verify)",
    refused: "var(--st-redline)",
    error: "var(--st-redline)",
};

export default function TitleBlock() {
    const part = useStudioStore((s) => s.part);
    const busy = useStudioStore((s) => s.busy);
    const rebuilding = useStudioStore((s) => s.rebuilding);
    const cursor = useStudioStore((s) => s.cursor);
    const isGenerating = useDesignStore((s) => s.isGenerating);
    const libraryError = useLibraryStore((s) => s.error);
    const activeId = useLibraryStore((s) => s.activeId);
    const designs = useLibraryStore((s) => s.designs);

    const working = busy || rebuilding || isGenerating;
    const verdict = (part?.verification?.verdict || "").toLowerCase();

    const status = working
        ? { text: rebuilding ? "Rebuilding" : "Working", tone: "var(--st-caution)" }
        : libraryError
          ? { text: "Attention", tone: "var(--st-redline)" }
          : { text: "Ready", tone: "var(--st-verify)" };

    const project = designs.find((d) => d.id === activeId);
    const name =
        project?.name ||
        (part?.partClass ? part.partClass.replace(/_/g, " ") : "") ||
        "untitled";

    const bbox = part?.stats?.bbox_mm;
    const volume = part?.stats?.volume_mm3;
    const features = part?.featureTree?.features.length ?? 0;

    return (
        <div className="of-titleblock">
            {/* Live state first — it is the only cell that changes on its own,
                so it reads as an instrument rather than a field. */}
            <div
                className="of-tb-cell"
                style={{ flexDirection: "row", alignItems: "center", gap: "7px", minWidth: "104px" }}
            >
                <span
                    style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        flexShrink: 0,
                        background: status.tone,
                        boxShadow: `0 0 7px ${status.tone}`,
                    }}
                />
                <span style={{ fontSize: "11px", color: "var(--st-graphite)", fontWeight: 500 }}>
                    {status.text}
                </span>
            </div>

            <Cell k="Part" v={name} />
            <Cell k="Units" v="mm" />
            <Cell k="Origin" v="centered" />
            {bbox?.length === 3 && (
                <Cell k="Extent" v={bbox.map((v) => v.toFixed(1)).join(" × ")} />
            )}
            {!!volume && <Cell k="Volume" v={`${(volume / 1000).toFixed(2)} cm³`} />}
            {features > 0 && <Cell k="Features" v={String(features)} />}
            {/* A revision number that means something: it is where the part sits
                in its own build history, so undo genuinely walks it back. */}
            {cursor >= 0 && <Cell k="Rev" v={String(cursor + 1).padStart(2, "0")} />}
            {part?.contractBroken ? (
                <Cell k="Contract" v="hand-edited" tone="var(--st-caution)" />
            ) : (
                verdict && <Cell k="Verdict" v={verdict} tone={VERDICT_TONE[verdict]} />
            )}
            {!!part?.generationTimeMs && (
                <Cell k="Built" v={`${(part.generationTimeMs / 1000).toFixed(1)} s`} />
            )}

            <div style={{ flex: 1, borderRight: "none" }} />

            {libraryError && (
                <div
                    className="of-tb-cell"
                    style={{ borderRight: "none", maxWidth: "38vw", overflow: "hidden" }}
                    title={libraryError}
                >
                    <span className="of-tb-key" style={{ color: "var(--st-redline)" }}>
                        Projects
                    </span>
                    <span className="of-tb-val" style={{ color: "var(--st-redline)" }}>
                        {libraryError}
                    </span>
                </div>
            )}
        </div>
    );
}
