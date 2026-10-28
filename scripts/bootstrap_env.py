"""Local-only .env bootstrap. Never overwrite user-managed credentials."""
from pathlib import Path
import os
import secrets

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'.env'
if DEST.exists():
    print('.env already exists; no changes made')
else:
    lines=['# Locally generated secrets. DO NOT COMMIT this file.',
           'CAUSALTRACE_API_KEY='+secrets.token_urlsafe(36),
           'DB_PASSWORD='+secrets.token_urlsafe(36),
           'RETENTION_DAYS=7',
           'INGEST_MAX_EVENTS=500',
           'INGEST_MAX_BYTES=1048576',
           'CAUSALTRACE_PROTECT_READS=1']
    fd=os.open(DEST,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        stream.write('\n'.join(lines)+'\n')
    print('Generated local-only .env (secrets not printed)')
