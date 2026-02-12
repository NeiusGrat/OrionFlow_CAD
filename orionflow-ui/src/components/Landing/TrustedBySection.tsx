export default function TrustedBySection() {
    const companies = [
        { name: 'Stanford', width: 100 },
        { name: 'MIT', width: 60 },
        { name: 'NASA', width: 80 },
        { name: 'SpaceX', width: 90 },
        { name: 'Tesla', width: 80 },
        { name: 'Lockheed', width: 100 },
    ];

    return (
        <section style={{
            padding: '60px 48px',
            position: 'relative',
            borderTop: '1px solid rgba(255, 255, 255, 0.04)',
            borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
            background: 'linear-gradient(180deg, rgba(15, 23, 42, 0.3) 0%, transparent 100%)',
        }}>
            <div style={{
                maxWidth: '1280px',
                margin: '0 auto',
                textAlign: 'center',
            }}>
                <p style={{
                    color: '#64748b',
                    fontSize: '13px',
                    fontWeight: 500,
                    textTransform: 'uppercase',
                    letterSpacing: '0.15em',
                    marginBottom: '32px',
                }}>
                    Trusted by engineers at
                </p>

                <div style={{
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    gap: '64px',
                    flexWrap: 'wrap',
                }}>
                    {companies.map((company, i) => (
                        <div
                            key={i}
                            style={{
                                color: '#475569',
                                fontSize: '18px',
                                fontWeight: 700,
                                letterSpacing: '0.05em',
                                textTransform: 'uppercase',
                                opacity: 0.6,
                                transition: 'opacity 0.3s ease',
                                cursor: 'default',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.opacity = '1';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.opacity = '0.6';
                            }}
                        >
                            {company.name}
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
