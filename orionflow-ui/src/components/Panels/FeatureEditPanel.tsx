/**
 * The engineering panel: what you selected, what it can do, what it would cost.
 *
 * Reads top to bottom in the order an engineer needs it:
 *
 *   1. Selection      the face, its feature, its surface — what am I looking at
 *   2. Verification   does this part currently satisfy its contract
 *   3. Dimensions     what this feature owns, and what each number drives
 *   4. Modify         retune a dimension, or apply an operation to the selection
 *   5. Impact         what else moves, before it is committed
 *   6. Dependencies   the feature's place in the build order
 *
 * Sections 4 and 5 are the reason this is not a properties inspector. A
 * parametric design ties dimensions together on purpose; showing the tie before
 * the change is what makes the edit an engineering act rather than typing a
 * number into a box.
 *
 * Every control here is wired to a real endpoint. There is no placeholder.
 */

import { useEffect, useMemo, useRef } from 'react';
import {
    AlertTriangle,
    ArrowRight,
    Box,
    Layers,
    Link2,
    MousePointerClick,
    ShieldAlert,
    ShieldCheck,
    Wrench,
} from 'lucide-react';
import { useEditStore } from '../../store/editStore';
import { useStudioStore } from '../../store/studioStore';
import {
    Badge,
    Button,
    Card,
    Cell,
    Collapsible,
    Empty,
    Meter,
    NumberField,
    PanelKeyframes,
    Row,
    Rows,
    Select,
    Spinner,
    Table,
} from './ui';
import { LABEL, MONO } from './panelTokens';

/** `PartDesign::Pocket` reads as `Pocket`. */
function typeName(type?: string | null): string {
    return (type || '').split('::').pop() || '—';
}

function surfaceName(surface?: string | null): string {
    return (surface || '').split('::').pop()?.replace('Geom', '') || '—';
}

function num(v: number | null | undefined, digits = 2): string {
    return v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);
}

/** The verdict, as a badge that never overstates what was checked. */
function VerdictBadge({
    verdict,
    contractBroken,
}: {
    verdict?: string | null;
    contractBroken?: boolean;
}) {
    if (contractBroken) {
        return (
            <Badge
                tone="warn"
                title="A feature was added by hand, so the authored assertions no longer describe this geometry."
            >
                <ShieldAlert size={10} /> contract broken
            </Badge>
        );
    }
    if (verdict === 'verified') {
        return (
            <Badge tone="ok">
                <ShieldCheck size={10} /> verified
            </Badge>
        );
    }
    if (verdict === 'refused') return <Badge tone="danger">refused</Badge>;
    if (!verdict) return <Badge tone="neutral">not graded</Badge>;
    return <Badge tone="warn">{verdict}</Badge>;
}

/**
 * What the kernel thinks of the solid, beside what the assertions think.
 *
 * Since 2026-08-05 these two numbers gate the verdict: an invalid shape, or one
 * in disconnected pieces, is refused however well its volume agrees. Before
 * that they were recorded and counted towards nothing, and a shelled enclosure
 * in the benchmark set that was `solids: 14, valid: false` read as a legitimate
 * result for a day because nothing surfaced it.
 *
 * They are still shown rather than folded into the badge, because "refused" on
 * its own does not say which half failed — the assertions or the geometry.
 */
function SolidHealth({ stats }: { stats?: { solids?: number | null; valid?: boolean | null } | null }) {
    if (!stats) return null;
    const solids = stats.solids;
    const valid = stats.valid;
    if (solids == null && valid == null) return null;

    const solidsBad = typeof solids === 'number' && solids !== 1;
    return (
        <>
            {solids != null && (
                <Row
                    label="solids"
                    title={
                        solidsBad
                            ? 'A part should be one solid. More than one means the geometry is in disconnected pieces.'
                            : undefined
                    }
                >
                    {solidsBad ? <Badge tone="danger">{solids}</Badge> : solids}
                </Row>
            )}
            {valid != null && (
                <Row
                    label="kernel check"
                    title={
                        valid
                            ? 'OCC reports the shape as geometrically valid.'
                            : 'OCC reports the shape as invalid. The assertions can still agree — a wrong topology can have a right volume.'
                    }
                >
                    {valid ? (
                        <Badge tone="ok">valid</Badge>
                    ) : (
                        <Badge tone="danger">invalid</Badge>
                    )}
                </Row>
            )}
        </>
    );
}

export default function FeatureEditPanel() {
    const {
        topology,
        faceMap,
        selectedFace,
        selectedFeature,
        inspection,
        inspecting,
        parameter,
        draft,
        plan,
        planning,
        committing,
        error,
        catalogue,
        operation,
        dimensions,
        proposal,
        proposing,
        chooseParameter,
        setDraft,
        preview,
        commit,
        clear,
        loadCatalogue,
        chooseOperation,
        setDimension,
        previewOperation,
        applyOperation,
    } = useEditStore();

    const part = useStudioStore((s) => s.part);
    const rebuilding = useStudioStore((s) => s.rebuilding);
    const busy = committing || rebuilding;

    useEffect(() => {
        void loadCatalogue();
    }, [loadCatalogue]);

    // Debounced: a preview is a network call, and a user typing "12.5" would
    // otherwise ask about 1, 12, 12. and 12.5 in turn.
    const retuneTimer = useRef<number | null>(null);
    useEffect(() => {
        if (draft == null || !parameter) return;
        if (retuneTimer.current) window.clearTimeout(retuneTimer.current);
        retuneTimer.current = window.setTimeout(() => void preview(), 220);
        return () => {
            if (retuneTimer.current) window.clearTimeout(retuneTimer.current);
        };
    }, [draft, parameter, preview]);

    const opTimer = useRef<number | null>(null);
    useEffect(() => {
        if (!operation) return;
        if (opTimer.current) window.clearTimeout(opTimer.current);
        opTimer.current = window.setTimeout(() => void previewOperation(), 260);
        return () => {
            if (opTimer.current) window.clearTimeout(opTimer.current);
        };
    }, [operation, dimensions, previewOperation]);

    const spec = useMemo(
        () => catalogue?.operations.find((o) => o.kind === operation) ?? null,
        [catalogue, operation],
    );

    const selectedKind: 'edge' | 'face' | null = selectedFace
        ? selectedFace.ref.split('.').pop()?.startsWith('e')
            ? 'edge'
            : 'face'
        : null;

    const featureEntry = selectedFeature
        ? topology?.features?.[selectedFeature]
        : undefined;

    const current = inspection?.parameters.find((p) => p.name === parameter);
    const changed = current != null && draft != null && draft !== current.value;

    const verification = part?.verification as
        | { verdict?: string; checks?: unknown[]; failed?: unknown[] }
        | null
        | undefined;
    const checks = verification?.checks?.length ?? 0;
    const failed = verification?.failed?.length ?? 0;

    // ---- empty states ---------------------------------------------------- //
    if (!topology) {
        return (
            <>
                <PanelKeyframes />
                <Empty icon={<Box size={20} />}>
                    This part was built before face selection existed, so its geometry
                    cannot be traced back to features. Rebuild it to enable editing.
                </Empty>
            </>
        );
    }

    if (!selectedFace) {
        const featureCount = Object.keys(topology.features || {}).length;
        return (
            <>
                <PanelKeyframes />
                <div style={{ padding: 12, display: 'grid', gap: 10 }}>
                    <Card title="Model">
                        <Rows>
                            <Row label="faces">{topology.counts?.faces ?? '—'}</Row>
                            <Row label="edges">{topology.counts?.edges ?? '—'}</Row>
                            <Row label="features">{featureCount}</Row>
                            <Row label="attribution">{topology.attribution ?? '—'}</Row>
                            {faceMap && faceMap.unassigned > 0 && (
                                <Row
                                    label="unmapped"
                                    title="Triangles that matched no CAD face. Those areas will not respond to a click."
                                >
                                    {faceMap.unassigned}
                                </Row>
                            )}
                        </Rows>
                    </Card>
                    <Empty icon={<MousePointerClick size={20} />}>
                        Click any face or edge in the viewport to see which feature made
                        it, what it can change, and what changing it would affect.
                    </Empty>
                </div>
            </>
        );
    }

    return (
        <div style={{ padding: 12, display: 'grid', gap: 10 }}>
            <PanelKeyframes />

            {/* ---- 1. selection ------------------------------------------ */}
            <Card
                title="Selection"
                right={
                    <button
                        onClick={clear}
                        style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--studio-text-dim)',
                            cursor: 'pointer',
                            fontSize: 11,
                            fontFamily: 'inherit',
                        }}
                    >
                        clear
                    </button>
                }
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'baseline',
                        gap: 8,
                        marginBottom: 8,
                    }}
                >
                    <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>
                        {selectedFeature || 'unattributed'}
                    </h3>
                    <Badge tone="info">{typeName(featureEntry?.type)}</Badge>
                    {selectedKind && <Badge tone="neutral">{selectedKind}</Badge>}
                </div>
                <Rows>
                    <Row label="ref">{selectedFace.stable || selectedFace.ref}</Row>
                    <Row label="surface">
                        {surfaceName(selectedFace.surface)}
                        {selectedFace.radius != null && ` · r${selectedFace.radius}`}
                    </Row>
                    {selectedFace.area != null && (
                        <Row label="area">{num(selectedFace.area)} mm²</Row>
                    )}
                    {selectedFace.center && (
                        <Row label="centre">
                            {selectedFace.center.map((c) => num(c, 1)).join(', ')}
                        </Row>
                    )}
                </Rows>
            </Card>

            {/* ---- 2. verification --------------------------------------- */}
            <Card
                title="Verification"
                right={
                    <VerdictBadge
                        verdict={verification?.verdict}
                        contractBroken={part?.contractBroken}
                    />
                }
            >
                {checks > 0 ? (
                    <>
                        <Meter
                            value={(checks - failed) / checks}
                            tone={failed ? 'danger' : 'ok'}
                        />
                        <div style={{ marginTop: 8 }}>
                            <Rows>
                                <Row label="checks passed">
                                    {checks - failed} / {checks}
                                </Row>
                                {part?.stats?.volume_mm3 != null && (
                                    <Row label="volume">
                                        {num(part.stats.volume_mm3, 1)} mm³
                                    </Row>
                                )}
                                <SolidHealth stats={part?.stats} />
                            </Rows>
                        </div>
                    </>
                ) : (
                    <p style={{ fontSize: 11, color: 'var(--studio-text-dim)', margin: 0 }}>
                        This part carries no assertions, so nothing was checked. The
                        geometry built; that is all the verdict can claim.
                    </p>
                )}
                {part?.contractBroken && (
                    <div
                        style={{
                            marginTop: 8,
                            display: 'flex',
                            gap: 6,
                            fontSize: 11,
                            lineHeight: 1.5,
                            color: 'var(--studio-text-dim)',
                        }}
                    >
                        <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
                        <span>
                            A feature was added by hand. The assertions above describe the
                            design before that change, so they are not a grade of this part.
                        </span>
                    </div>
                )}
            </Card>

            {inspecting && (
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11 }}>
                    <Spinner /> reading feature…
                </div>
            )}

            {/* ---- 3. dimensions ----------------------------------------- */}
            {inspection && (
                <Card title="Dimensions">
                    <Table head={['Name', 'Value', 'Driven by', '']} empty="none">
                        {inspection.parameters.map((p) => (
                            <tr
                                key={p.name}
                                onClick={() => p.direct && chooseParameter(p.name)}
                                style={{
                                    cursor: p.direct ? 'pointer' : 'default',
                                    background:
                                        p.name === parameter
                                            ? 'rgba(124,151,214,0.10)'
                                            : undefined,
                                }}
                            >
                                <Cell>{p.name}</Cell>
                                <Cell align="right">{p.value}</Cell>
                                <Cell dim={!p.direct}>
                                    {p.direct ? p.variable : p.expression}
                                </Cell>
                                <Cell>
                                    {!p.direct && <Badge tone="neutral">computed</Badge>}
                                    {p.direct && p.shared_with.length > 0 && (
                                        <Badge
                                            tone="info"
                                            title={`also drives ${p.shared_with.join(', ')}`}
                                        >
                                            <Link2 size={9} /> {p.shared_with.length}
                                        </Badge>
                                    )}
                                </Cell>
                            </tr>
                        ))}
                    </Table>
                    {!inspection.editable && (
                        <p
                            style={{
                                fontSize: 11,
                                marginTop: 8,
                                color: 'var(--studio-text-dim)',
                                lineHeight: 1.5,
                            }}
                        >
                            This feature owns no dimension of its own — every number it uses
                            is computed from another feature's.
                        </p>
                    )}
                </Card>
            )}

            {/* ---- 4a. retune -------------------------------------------- */}
            {current?.direct && (
                <Card title={`Retune · ${current.name}`}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <input
                            type="range"
                            min={Math.max(current.value * 0.1, 0.01)}
                            max={current.value * 3 || 1}
                            step={Math.max(current.value / 200, 0.01)}
                            value={draft ?? current.value}
                            disabled={busy}
                            onChange={(e) => setDraft(Number(e.target.value))}
                            style={{ flex: 1 }}
                        />
                        <div style={{ width: 108 }}>
                            <NumberField
                                value={draft ?? current.value}
                                onChange={setDraft}
                                unit="mm"
                                disabled={busy}
                            />
                        </div>
                    </div>
                    <div style={{ marginTop: 10 }}>
                        <Button
                            tone="primary"
                            full
                            busy={busy}
                            disabled={!changed}
                            onClick={() => void commit()}
                        >
                            {busy ? 'Rebuilding…' : changed ? 'Apply and rebuild' : 'No change'}
                        </Button>
                    </div>
                </Card>
            )}

            {/* ---- 5a. retune impact ------------------------------------- */}
            {changed && (
                <Card
                    title="Effect of this change"
                    right={planning ? <Spinner /> : undefined}
                >
                    {plan ? (
                        <>
                            <Rows>
                                <Row label={plan.variable}>
                                    {plan.before}
                                    <ArrowRight
                                        size={9}
                                        style={{ margin: '0 4px', verticalAlign: 'middle' }}
                                    />
                                    {plan.after}
                                </Row>
                            </Rows>

                            <div style={{ marginTop: 10 }}>
                                <span style={LABEL}>Moves with it</span>
                                <div style={{ marginTop: 4 }}>
                                    <Table
                                        head={['Path', 'Before', 'After']}
                                        empty="Nothing else in the design depends on it."
                                    >
                                        {plan.also_moves.map((m) => (
                                            <tr key={m.path}>
                                                <Cell>{m.path}</Cell>
                                                <Cell align="right" dim>
                                                    {m.before}
                                                </Cell>
                                                <Cell align="right">{m.after}</Cell>
                                            </tr>
                                        ))}
                                    </Table>
                                </div>
                            </div>

                            {plan.assertions_moved.length > 0 && (
                                <div style={{ marginTop: 10 }}>
                                    <span style={LABEL}>Checks that follow</span>
                                    <div style={{ marginTop: 4 }}>
                                        <Table head={['Assertion', 'Before', 'After']}>
                                            {plan.assertions_moved.map((m) => (
                                                <tr key={m.path}>
                                                    <Cell>{m.path}</Cell>
                                                    <Cell align="right" dim>
                                                        {num(m.before, 1)}
                                                    </Cell>
                                                    <Cell align="right">{num(m.after, 1)}</Cell>
                                                </tr>
                                            ))}
                                        </Table>
                                    </div>
                                </div>
                            )}

                            {plan.contract_preserved && (
                                <div
                                    style={{
                                        marginTop: 10,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 6,
                                        fontSize: 11,
                                        color: '#6E9E6E',
                                    }}
                                >
                                    <ShieldCheck size={12} />
                                    Contract preserved — the part will be re-checked against it.
                                </div>
                            )}
                        </>
                    ) : (
                        !planning && (
                            <p style={{ fontSize: 11, color: 'var(--studio-text-dim)', margin: 0 }}>
                                Adjust a value to see what it would affect.
                            </p>
                        )
                    )}
                </Card>
            )}

            {/* ---- 4b. workbench operations ------------------------------ */}
            {catalogue && (
                <Card title="Apply operation" right={<Wrench size={12} />}>
                    <Select
                        value={operation}
                        onChange={chooseOperation}
                        placeholder="Choose an operation…"
                        disabled={busy}
                        options={[
                            ...catalogue.operations.map((o) => ({
                                value: o.kind,
                                label:
                                    o.target === selectedKind
                                        ? o.kind
                                        : `${o.kind} — needs a${o.target === 'edge' ? 'n edge' : ' face'}`,
                                disabled: o.target !== selectedKind,
                            })),
                            ...catalogue.planned.map((p) => ({
                                value: `planned:${p.kind}`,
                                label: `${p.kind} — ${p.reason}`,
                                disabled: true,
                            })),
                        ]}
                    />

                    {spec && (
                        <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
                            <p
                                style={{
                                    fontSize: 11,
                                    color: 'var(--studio-text-dim)',
                                    margin: 0,
                                    lineHeight: 1.5,
                                }}
                            >
                                {spec.blurb}
                            </p>
                            {spec.dimensions.map((d) => (
                                <div key={d.name}>
                                    <span style={LABEL}>{d.label}</span>
                                    <div style={{ marginTop: 4 }}>
                                        <NumberField
                                            value={dimensions[d.name] ?? d.default}
                                            onChange={(v) => setDimension(d.name, v)}
                                            unit={d.unit}
                                            min={d.min}
                                            max={d.max}
                                            disabled={busy}
                                        />
                                    </div>
                                </div>
                            ))}
                            <Button
                                tone="primary"
                                full
                                busy={busy}
                                disabled={!proposal}
                                onClick={() => void applyOperation()}
                            >
                                {busy ? 'Rebuilding…' : `Apply ${spec.kind}`}
                            </Button>
                        </div>
                    )}
                </Card>
            )}

            {/* ---- 5b. operation impact ---------------------------------- */}
            {operation && (proposal || proposing) && (
                <Card
                    title="This operation would"
                    right={proposing ? <Spinner /> : undefined}
                >
                    {proposal && (
                        <>
                            <Rows>
                                <Row label="adds">{proposal.kind}</Row>
                                <Row label="on">{proposal.on_feature ?? '—'}</Row>
                                <Row label="selector" title={proposal.selector}>
                                    {proposal.selector}
                                </Row>
                                {Object.entries(proposal.variables).map(([k, v]) => (
                                    <Row key={k} label={`new variable ${k}`}>
                                        {v}
                                    </Row>
                                ))}
                            </Rows>
                            <div
                                style={{
                                    marginTop: 10,
                                    display: 'flex',
                                    gap: 6,
                                    fontSize: 11,
                                    lineHeight: 1.5,
                                    color: '#C39B4E',
                                }}
                            >
                                <ShieldAlert size={12} style={{ flexShrink: 0, marginTop: 1 }} />
                                <span>
                                    Adding a feature changes the template, so the authored
                                    assertions will no longer describe this part. The result
                                    will be marked contract broken.
                                </span>
                            </div>
                        </>
                    )}
                </Card>
            )}

            {/* ---- 6. dependencies --------------------------------------- */}
            {featureEntry && (
                <Collapsible
                    title="Dependencies"
                    right={<Layers size={12} />}
                    defaultOpen={false}
                >
                    <Rows>
                        <Row label="build index">{featureEntry.build_index ?? '—'}</Row>
                        <Row label="faces owned">{featureEntry.faces?.length ?? 0}</Row>
                        <Row label="edges owned">{featureEntry.edges?.length ?? 0}</Row>
                    </Rows>
                    {selectedFace.lineage && selectedFace.lineage.length > 1 && (
                        <div style={{ marginTop: 10 }}>
                            <span style={LABEL}>This face descends from</span>
                            <div
                                style={{
                                    marginTop: 5,
                                    fontFamily: MONO,
                                    fontSize: 11,
                                    lineHeight: 1.7,
                                }}
                            >
                                {selectedFace.lineage.map((step, i) => (
                                    <span key={step}>
                                        {i > 0 && (
                                            <ArrowRight
                                                size={9}
                                                style={{
                                                    margin: '0 4px',
                                                    verticalAlign: 'middle',
                                                    opacity: 0.5,
                                                }}
                                            />
                                        )}
                                        <span
                                            style={{
                                                color:
                                                    step === selectedFeature
                                                        ? 'var(--studio-accent, #7C97D6)'
                                                        : undefined,
                                            }}
                                        >
                                            {step}
                                        </span>
                                    </span>
                                ))}
                            </div>
                            <p
                                style={{
                                    fontSize: 10,
                                    color: 'var(--studio-text-dim)',
                                    marginTop: 6,
                                    lineHeight: 1.5,
                                }}
                            >
                                Authorship is the highlighted feature. The rest is the chain it
                                was derived through — a fillet's face descends from the edge
                                that was rounded, and from whatever made that edge.
                            </p>
                        </div>
                    )}
                </Collapsible>
            )}

            {error && (
                <div
                    style={{
                        display: 'flex',
                        gap: 6,
                        fontSize: 11,
                        lineHeight: 1.5,
                        color: '#C0705F',
                        padding: '8px 10px',
                        border: '1px solid rgba(192,112,95,0.35)',
                        borderRadius: 6,
                        background: 'rgba(192,112,95,0.10)',
                    }}
                >
                    <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
                    <span>{error}</span>
                </div>
            )}
        </div>
    );
}
