import time
from causaltrace.api import purge
from causaltrace.db import Event
from .conftest import auth

def test_restart_persistence_in_file(client):
    created=client.post('/api/incidents',headers=auth(),json={'title':'Recoverable incident'}).json()
    # Fresh SQLAlchemy session emulates API restart: persisted state not in process memory.
    with client.app.state.ct.sessions() as session:
        assert session.get(__import__('causaltrace.db',fromlist=['Incident']).Incident,created['id']) is not None

def test_retention_removes_old_telemetry_not_incidents(client):
    with client.app.state.ct.sessions() as db:
        db.add(Event(event_id='old',service='auth',timestamp_ns=int((time.time()-10*86400)*1e9)))
        db.commit()
        removed=purge(db,7);db.commit()
        assert removed['events']==1
        assert db.get(Event,'old') is None
