import pytest
from fastapi.testclient import TestClient
from causaltrace.api import create_app
from causaltrace.db import Base
from causaltrace.settings import Settings

KEY="0123456789abcdef0123456789abcdef"

@pytest.fixture()
def client(tmp_path):
    settings=Settings(database_url=f"sqlite:///{tmp_path/'test.db'}",api_key=KEY,
                      retention_days=7,ingest_max_events=500,ingest_max_bytes=1048576,
                      lab_enabled=False,lab_services=("gateway","auth","catalog","inventory","cart","checkout","payment","notification","database","cache"))
    app=create_app(settings)
    Base.metadata.create_all(app.state.ct.engine)
    with TestClient(app) as c:
        yield c

def auth():return {"x-api-key":KEY}
