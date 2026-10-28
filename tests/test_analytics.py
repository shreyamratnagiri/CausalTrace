from causaltrace.analytics import aggregate,reconstruct,extract_edges,rank_causes,robust_anomalies,threshold_anomalies,ranking_scores

def span(service,sid,parent=None,start=100,end=200,trace='a'*32,error=False):
    return dict(service=service,span_id=sid,parent_span_id=parent,start_ns=start,end_ns=end,
                trace_id=trace,error=error,attributes={'span.kind':'server'},operation='test')

def test_missing_and_out_of_order_parent():
    children=[span('payment','2','1',200,800),span('checkout','1',None,100,900)]
    reconstructed=reconstruct(children)
    assert reconstructed['missing_parent_span_ids']==[]
    assert reconstructed['critical_path_span_ids']==['1','2']
    assert [(e['source'],e['target']) for e in extract_edges(children)]==[('checkout','payment')]
    orphan=reconstruct([children[0]])
    assert orphan['missing_parent_span_ids']==['2']

def test_window_aggregation_excludes_client_spans():
    source=[span('checkout','1',start=5_000_000_000,end=5_001_000_000)]
    client={**source[0],'span_id':'2','attributes':{'span.kind':'client'}}
    assert aggregate(source+[client])[0]['requests']==1

def test_anomaly_detection():
    rows=[dict(service='payment',start=i*5,requests=20,error_rate=0,latency_ms=100,throughput_rps=4) for i in range(10)]
    rows.append(dict(service='payment',start=50,requests=20,error_rate=.8,latency_ms=700,throughput_rps=4))
    assert {'latency_ms','error_rate'} <= {a['metric'] for a in robust_anomalies(rows)}
    assert len(threshold_anomalies(rows))==2

def test_ranking_prefers_causal_dependency_with_temporal_evidence():
    anomalies=[{'service':'gateway','start':110,'score':8},
               {'service':'checkout','start':105,'score':8},
               {'service':'payment','start':100,'score':8}]
    edges=[{'source':'gateway','target':'checkout'},{'source':'checkout','target':'payment'}]
    ranks=rank_causes(anomalies,edges)
    assert ranks[0]['service']=='payment'
    assert ranks[0]['evidence'] and isinstance(ranks[0]['contradictions'],list)
    assert len(rank_causes(anomalies,edges,mode='severity'))==3

def test_ranking_metrics_and_cases():
    result=ranking_scores(['a','b'],[['b','a'],['b','a']])
    assert result['top1']==.5 and result['mrr']==.75
