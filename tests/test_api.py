import time
from .conftest import auth

def test_health_readiness(client):
    assert client.get('/health').status_code==200
    assert client.get('/ready').status_code==200
    assert client.get('/api/overview').json()['spans']==0

def test_admin_operations_protected(client):
    assert client.post('/api/incidents',json={'title':'test issue'}).status_code==401
    assert client.post('/api/incidents',json={'title':'test issue'},headers={'x-api-key':'wrong'}).status_code==401

def test_persistent_incident_workflow(client):
    r=client.post('/api/incidents',json={'title':'Checkout degradation'},headers=auth())
    assert r.status_code==201,r.text
    record=r.json();inc=record['id']
    assert client.get(f'/api/incidents/{inc}').json()['title']=='Checkout degradation'
    assert client.post(f'/api/incidents/{inc}/analyze',headers=auth()).status_code==200
    detail=client.get(f'/api/incidents/{inc}').json()
    assert detail['version']==1
    transition=client.patch(f'/api/incidents/{inc}',json={'status':'investigating','version':1},headers=auth())
    assert transition.status_code==200,transition.text
    assert client.patch(f'/api/incidents/{inc}',json={'status':'resolved','version':1},headers=auth()).status_code==409
    assert client.get(f'/api/reports/{inc}').json()['proven_cause'] is None

def test_events_duplicates_and_validation(client):
    event={'event_id':'e1','service':'payment','timestamp':time.time(),'latency_ms':45,'error':True}
    assert client.post('/api/telemetry/events',json={'events':[event]},headers=auth()).json()['accepted']==1
    assert client.post('/api/telemetry/events',json={'events':[event]},headers=auth()).json()['duplicates']==1
    event['timestamp']=1
    assert client.post('/api/telemetry/events',json={'events':[event]},headers=auth()).status_code==422

def test_metrics_dedup(client):
    m={'service':'payment','name':'request_count','timestamp':time.time(),'value':7.0}
    data={'metrics':[m]}
    assert client.post('/api/telemetry/metrics',json=data,headers=auth()).json()['accepted']==1
    assert client.post('/api/telemetry/metrics',json=data,headers=auth()).json()['duplicates']==1
    assert client.get('/api/metrics').json()['items'][0]['value']==7

def test_lab_restricted(client):
    r=client.post('/api/lab/experiments',json={'target':'payment','mode':'error'},headers=auth())
    assert r.status_code==403
    assert client.get('/api/system').json()['lab_enabled'] is False

def test_benchmark_provenance(client):
    data={'dataset':'seeded-isolation-forest','data_origin':'synthetic_fixture','result':{'f1':0.5}}
    r=client.post('/api/benchmarks',json=data,headers=auth())
    assert r.status_code==201,r.text
    records=client.get('/api/benchmarks').json()['items']
    assert records[0]['result']['data_origin']=='synthetic_fixture'
    assert 'not independently attested' in records[0]['result']['verification']
