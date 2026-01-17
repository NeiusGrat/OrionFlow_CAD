import { MessageSquare, Zap } from 'lucide-react';

export default function AIDirectorSection() {
    return (
        <section style={{
            padding: '120px 48px',
            position: 'relative',
            background: 'linear-gradient(180deg, transparent 0%, rgba(59, 130, 246, 0.02) 50%, transparent 100%)',
        }}>
            <div style={{
                maxWidth: '1280px',
                margin: '0 auto',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '80px',
                alignItems: 'center',
            }}>
                {/* Left - Text content */}
                <div>
                    <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        background: 'rgba(59, 130, 246, 0.1)',
                        padding: '8px 16px',
                        borderRadius: '100px',
                        marginBottom: '24px',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                    }}>
                        <Zap size={14} color="#60a5fa" />
                        <span style={{ color: '#93c5fd', fontSize: '13px', fontWeight: 500 }}>AI-Powered</span>
                    </div>

                    <h2 style={{
                        fontSize: '44px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '20px',
                        lineHeight: 1.1,
                    }}>
                        AI Director
                    </h2>

                    <p style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                        lineHeight: 1.7,
                        marginBottom: '20px',
                    }}>
                        Describe precise topological edits. OrionFlow understands engineering intent and modifies parametric history — not meshes.
                    </p>

                    <p style={{
                        fontSize: '15px',
                        color: '#64748b',
                        lineHeight: 1.6,
                    }}>
                        Our AI interprets natural language commands and translates them into precise CAD operations, maintaining full parametric integrity throughout.
                    </p>
                </div>

                {/* Right - Chat UI mock */}
                <div style={{
                    background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.9) 0%, rgba(3, 7, 18, 0.95) 100%)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '20px',
                    overflow: 'hidden',
                    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.5)',
                }}>
                    {/* Header */}
                    <div style={{
                        padding: '16px 20px',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <MessageSquare size={18} color="#60a5fa" />
                            <span style={{ color: '#e2e8f0', fontWeight: 600, fontSize: '14px' }}>AI Director Chat</span>
                        </div>
                        <span style={{
                            color: '#64748b',
                            fontSize: '12px',
                            fontFamily: 'var(--font-mono)',
                        }}>
                            motor_mount_v4.step
                        </span>
                    </div>

                    {/* Chat messages */}
                    <div style={{ padding: '20px' }}>
                        {/* User message */}
                        <div style={{
                            background: 'rgba(59, 130, 246, 0.12)',
                            border: '1px solid rgba(59, 130, 246, 0.2)',
                            borderRadius: '12px',
                            padding: '14px 16px',
                            marginBottom: '16px',
                        }}>
                            <div style={{ color: '#60a5fa', fontSize: '11px', fontWeight: 600, marginBottom: '6px' }}>You</div>
                            <div style={{ color: '#e2e8f0', fontSize: '14px', lineHeight: 1.5 }}>
                                Increase the bore diameter to 12mm and add a circular pattern of 6 holes equally spaced.
                            </div>
                        </div>

                        {/* AI response */}
                        <div style={{
                            background: 'rgba(3, 7, 18, 0.6)',
                            border: '1px solid rgba(255, 255, 255, 0.06)',
                            borderRadius: '12px',
                            padding: '14px 16px',
                        }}>
                            <div style={{ color: '#22c55e', fontSize: '11px', fontWeight: 600, marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div style={{
                                    width: '6px',
                                    height: '6px',
                                    borderRadius: '50%',
                                    background: '#22c55e',
                                }} />
                                OrionFlow
                            </div>

                            {/* Status lines */}
                            <div style={{ marginBottom: '12px' }}>
                                <div style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>
                                    ✓ Analyzing topology...
                                </div>
                                <div style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>
                                    ✓ Updating feature graph...
                                </div>
                                <div style={{ color: '#60a5fa', fontSize: '13px', fontFamily: 'var(--font-mono)' }}>
                                    → Regenerating geometry...
                                </div>
                            </div>

                            {/* Updated params */}
                            <div style={{
                                background: 'rgba(15, 23, 42, 0.8)',
                                borderRadius: '8px',
                                padding: '12px',
                                display: 'flex',
                                flexWrap: 'wrap',
                                gap: '8px',
                            }}>
                                <span style={{
                                    background: 'rgba(34, 197, 94, 0.15)',
                                    color: '#86efac',
                                    padding: '4px 10px',
                                    borderRadius: '6px',
                                    fontSize: '12px',
                                    fontFamily: 'var(--font-mono)',
                                    border: '1px solid rgba(34, 197, 94, 0.2)',
                                }}>
                                    bore_dia: 12mm
                                </span>
                                <span style={{
                                    background: 'rgba(34, 197, 94, 0.15)',
                                    color: '#86efac',
                                    padding: '4px 10px',
                                    borderRadius: '6px',
                                    fontSize: '12px',
                                    fontFamily: 'var(--font-mono)',
                                    border: '1px solid rgba(34, 197, 94, 0.2)',
                                }}>
                                    pattern_count: 6
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
