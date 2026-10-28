"""Separate an attempted outbound call from an actually observed server span."""
import time

from sqlalchemy import select

from causaltrace.analytics import extract_edges
from causaltrace.api import record_spans
from causaltrace.db import DependencyEdge


def make(service, sid, parent=None, *, kind='server', remote=None, error=False):
    attrs={'span.kind':kind}
    if remote:
        attrs['server.address']=remote
    now=time.time_ns()
    return dict(trace_id='a'*32,span_id=sid,parent_span_id=parent,service=service,
                operation=service+'.request',start_ns=now,end_ns=now+100_000,
                error=error,attributes=attrs)


def test_missing_server_span_yields_inferred_edge():
    root=make('gateway','0'*16)
    call=make('gateway','1'*16,root['span_id'],kind='client',remote='payment',error=True)
    edges=extract_edges([call,root])
    assert len(edges)==1
    assert edges[0]['source']=='gateway' and edges[0]['target']=='payment'
    assert edges[0]['provenance']=='client-target-unconfirmed'
    assert edges[0]['error'] is True


def test_server_span_replaces_inference_when_it_arrives(client):
    root=make('gateway','0'*16)
    call=make('gateway','1'*16,root['span_id'],kind='client',remote='payment',error=True)
    child=make('payment','2'*16,call['span_id'])
    with client.app.state.ct.sessions() as session:
        first=record_spans(session,[root,call]);session.commit()
        assert first['accepted']==2
        edges=session.scalars(select(DependencyEdge)).all()
        assert len(edges)==1 and edges[0].provenance=='client-target-unconfirmed'
        record_spans(session,[child]);session.commit()
        edges=session.scalars(select(DependencyEdge)).all()
        assert len(edges)==1 and edges[0].provenance=='span-parent'


def test_untrusted_network_url_cannot_create_topology_edge():
    root=make('gateway','0'*16)
    call=make('gateway','1'*16,root['span_id'],kind='client',remote='https://external.invalid')
    assert extract_edges([root,call])==[]
