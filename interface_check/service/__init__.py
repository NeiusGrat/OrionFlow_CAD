"""The analysis platform around the engine: stateless API, job store, object
storage, resource-aware dispatch and isolated workers.

    api        HTTP: auth, upload init, job creation, status, results (no geometry)
    db         job store (SQLAlchemy Core: SQLite locally, Supabase Postgres hosted)
    storage    object storage (local directory, or any S3 API incl. Supabase Storage)
    jobs       job states, admission control, retry / escalation policy, pump
    worker     one job in an isolated child process under a memory + time watchdog
    dispatch   where a job runs: a local thread pool, or a Modal function per tier
"""
