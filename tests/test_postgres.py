"""PostgreSQL smoke runs only in CI with explicitly supplied temporary CI DB."""
import os
import uuid
import pytest
from sqlalchemy import select
from causaltrace.db import Event, make_engine, session_factory, insert_ignore

@pytest.mark.skipif(not os.getenv('CAUSALTRACE_TEST_POSTGRES'),reason='No isolated Postgres CI database supplied')
def test_postgres_atomic_idempotency():
    engine=make_engine(os.environ['CAUSALTRACE_TEST_POSTGRES'])
    # The isolated database is migrated before this test. Avoid committing even
    # disposable verification rows, so each test is repeatable independently.
    try:
        identifier='ci-'+uuid.uuid4().hex
        item={'event_id':identifier,'service':'auth','timestamp_ns':42,'latency_ms':0.5,'error':False,
              'kind':'test','detail':{}}
        from sqlalchemy.orm import Session
        with engine.connect() as conn:
            tx=conn.begin()
            try:
                with Session(bind=conn, join_transaction_mode='create_savepoint') as session:
                    first=insert_ignore(session,Event,[item],['event_id'])
                    second=insert_ignore(session,Event,[item],['event_id'])
                    session.flush()
                    assert first==1 and second==0
                    assert session.scalar(select(Event).where(Event.event_id==identifier)) is not None
            finally:
                tx.rollback()
        with session_factory(engine)() as session:
            assert session.scalar(select(Event).where(Event.event_id==identifier)) is None
    finally:
        engine.dispose()
