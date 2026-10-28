"""Integration checks against a migrated, isolated PostgreSQL schema.

These intentionally fail rather than substitute SQLite when supplied a real
PostgreSQL connection URL. Tests never commit permanent user data.
"""
import os
import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from causaltrace.db import Incident, Span, Timeline, Experiment, make_engine, session_factory

pytestmark = pytest.mark.skipif(
    not os.environ.get('CAUSALTRACE_TEST_POSTGRES'),
    reason='Requires migrated isolated PostgreSQL via CAUSALTRACE_TEST_POSTGRES',
)


def test_postgres_migrations_contain_critical_indexes():
    engine = make_engine(os.environ['CAUSALTRACE_TEST_POSTGRES'])
    try:
        inspector = inspect(engine)
        assert inspector.has_table('alembic_version'), 'Migrations were not applied'
        assert {'spans', 'timeline', 'experiments', 'incidents', 'dependency_edges'} <= set(inspector.get_table_names())
        span_indexes = {i['name'] for i in inspector.get_indexes('spans')}
        assert {'ix_spans_service_start', 'ix_spans_trace_start'} <= span_indexes
        foreign = inspector.get_foreign_keys('timeline')
        assert any('incident_id' in item['constrained_columns'] and
                   item['referred_table'] == 'incidents' for item in foreign)
    finally:
        engine.dispose()


def test_postgres_foreign_keys_rollback_and_restart_persistence():
    engine = make_engine(os.environ['CAUSALTRACE_TEST_POSTGRES'])
    incident_id = str(uuid.uuid4())
    trace_id = uuid.uuid4().hex
    try:
        # The transaction is deliberately rolled back even on a successful
        # query, so this test does not pollute an existing test database.
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                from sqlalchemy.orm import Session
                with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                    session.add(Incident(id=incident_id, title='temporary integration incident'))
                    session.flush()
                    session.add(Timeline(incident_id=incident_id,actor='test',action='created',detail={}))
                    session.add(Experiment(id=incident_id,target='payment',mode='error',status='running'))
                    session.add(Span(trace_id=trace_id,span_id='0'*16,service='gateway',
                                     operation='test',start_ns=1,end_ns=2,error=False,attributes={}))
                    session.flush()
                    assert session.get(Incident,incident_id) is not None
                    assert session.get(Experiment,incident_id) is not None
                    assert session.scalar(select(Span).where(Span.trace_id==trace_id)) is not None
                # A new SQL transaction/session must not see an uncommitted
                # test incident after rollback (recovery/idempotency invariant).
            finally:
                tx.rollback()
        with session_factory(engine)() as session:
            assert session.get(Incident,incident_id) is None
            assert session.get(Experiment,incident_id) is None
            assert session.scalar(select(Span).where(Span.trace_id==trace_id)) is None
        # Foreign-key rejection in a fresh transaction.
        with session_factory(engine)() as session:
            session.add(Timeline(incident_id=str(uuid.uuid4()),actor='test',action='invalid',detail={}))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()
