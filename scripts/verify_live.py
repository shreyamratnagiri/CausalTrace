"""Host-side, non-synthetic acceptance checks against the isolated running lab.

Only loopback HTTP addresses. Disallowed statuses fail the suite, including
unverified recovery, missing traces and missing telemetry-based rankings.
"""
import argparse
import json
import os
import sys
import time
import platform
import subprocess
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from datetime import datetime, timezone
import httpx

BASE='http://127.0.0.1:8000'
LAB='http://127.0.0.1:8100'
SCENARIOS=(('payment','error'),('cache','latency'),('database','db_exhaustion'))


def run(timeout:float):
    key=os.environ.get('CAUSALTRACE_API_KEY','')
    if len(key)<16:
        raise RuntimeError('Export CAUSALTRACE_API_KEY from local .env before running tests')
    try:
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],
            stderr=subprocess.DEVNULL,timeout=3,text=True).strip()
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
        source_revision=None
    manifest=Path('SOURCE_MANIFEST.sha256')
    source_manifest_sha256=sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
    versions={}
    for package in ('fastapi','sqlalchemy','opentelemetry-sdk','scikit-learn','httpx'):
        try:versions[package]=metadata.version(package)
        except metadata.PackageNotFoundError:versions[package]=None
    report={'schema':'causaltrace-lab-e2e-v3','origin':'actual isolated Compose traffic',
            'started_at':datetime.now(timezone.utc).isoformat(),'scenarios':[],
            'reproducibility':{'source_revision':os.getenv('GITHUB_SHA') or source_revision,
                               'source_manifest_sha256':source_manifest_sha256,
                               'dependencies':versions,
                               'python':platform.python_version(),'os':platform.system(),
                               'architecture':platform.machine(),
                               'experiment_configs':[{'target':target,'mode':mode,
                                                      'duration_seconds':18,'delay_ms':700,
                                                      'probability':1,'seed':42}
                                                     for target,mode in SCENARIOS]}}
    with httpx.Client(timeout=8,trust_env=False,headers={'x-api-key':key}) as client:
        def get(path,lab=False):
            r=client.get((LAB if lab else BASE)+path);r.raise_for_status();return r.json()
        def post(path,payload):
            r=client.post(BASE+path,json=payload,headers={'x-api-key':key});r.raise_for_status();return r.json()
        try:
            deadline=time.monotonic()+90
            while True:
                try:
                    if get('/ready')['status']=='ready' and get('/health',lab=True)['status']=='ok':
                        break
                except (httpx.HTTPError,AssertionError,KeyError):
                    pass
                if time.monotonic()>=deadline:
                    raise RuntimeError('API/gateway not healthy within 90 seconds of Compose start')
                time.sleep(2)
            baseline=[]
            for _ in range(5):
                begin=time.perf_counter()
                r=client.get(LAB+'/checkout')
                baseline.append({'status':r.status_code,'elapsed_ms':(time.perf_counter()-begin)*1000})
            assert all(r['status']==200 for r in baseline),'Healthy checkout precondition failed'
            report['baseline']=baseline
            for target,mode in SCENARIOS:
                item=post('/api/lab/experiments',{'target':target,'mode':mode,
                    'duration_seconds':18,'delay_ms':700,'probability':1})
                ident=item['id']
                deadline=time.monotonic()+timeout
                while time.monotonic()<deadline:
                    record=get('/api/lab/experiments/'+ident)
                    if record['status'] in {'completed','failed','cancelled'}:
                        break
                    time.sleep(2)
                else:
                    post('/api/lab/experiments/'+ident+'/stop',{})
                    raise RuntimeError(f'Experiment {ident} did not complete within {timeout}s')
                report['scenarios'].append(record)
                if record['status']!='completed':
                    raise RuntimeError(f'Experiment {ident} ended {record["status"]}: {record.get("result")}')
                result=record.get('result') or {}
                if not result.get('cleanup_verified') or not result.get('recorded_windows'):
                    raise RuntimeError(f'Cleanup or real telemetry missing for experiment {ident}')
                if not result.get('detection',{}).get('anomaly_count'):
                    raise RuntimeError(f'No observed anomaly evidence during {target}/{mode} fault')
                if not result.get('ranking') or len(set(result['ranking']))!=len(result['ranking']):
                    raise RuntimeError(f'Root-cause ranking missing or duplicates candidates for {ident}')
                # A valid ranking can miss the intervention target. Retain the
                # negative finding in scored live accuracy, rather than treating
                # a model error as an infrastructure failure or hiding the run.
                if not result.get('root_cause_evidence'):
                    raise RuntimeError(f'Missing ranked hypothesis evidence for {ident}')
                if not result.get('recovery_verified'):
                    raise RuntimeError(f'Recovery status not verified for {ident}')
                if not result.get('recorded_dependency_edges'):
                    raise RuntimeError(f'No observed cross-service trace edges for experiment {ident}')
                if not result.get('fault') or not result.get('recovery'):
                    raise RuntimeError(f'Missing fault/recovery requests for {ident}')
                if not all(x['http_status']==200 for x in result['recovery']):
                    raise RuntimeError(f'Service did not return to healthy checkout after experiment {ident}')
            traces=get('/api/traces')['items']
            if not traces or not any(t['spans']>=3 for t in traces):
                raise RuntimeError('No multi-service traces persisted')
            multi_service=False
            for summary in traces[:30]:
                if summary['spans']<3:
                    continue
                detail=get('/api/traces/'+summary['trace_id'])
                if len({span['service'] for span in detail['spans']})>=3:
                    multi_service=True
                    break
            if not multi_service:
                raise RuntimeError('No single trace demonstrated cross-service trace propagation')
            topology=get('/api/topology')['edges']
            if not any(e['source']=='gateway' for e in topology):
                raise RuntimeError('No persisted gateway dependency edges')
            detected=post('/api/incidents/detect',{})
            incident=get('/api/incidents/'+detected['id'])
            if not incident['evidence'] or not incident['hypotheses']:
                raise RuntimeError('Auto-detected incident lacks real evidence and ranked hypotheses')
            exported=get('/api/reports/'+detected['id'])
            if not exported.get('incident') or exported['incident']['id']!=detected['id']:
                raise RuntimeError('Evidence report could not be exported')
            report['incident_id']=detected['id']
            report['observed_traces']=len(traces)
            report['observed_topology_links']=len(topology)
            from benchmarks.live_evaluate import evaluate_live
            report['evaluation']=evaluate_live(report['scenarios'])
            report['completed_at']=datetime.now(timezone.utc).isoformat()
            # Persist measured experiment scores for the actual dashboard.
            # A failed benchmark persistence step is a release-test failure;
            # silently writing a local JSON file would leave the product's
            # benchmark page disconnected from its backend.
            stored=post('/api/benchmarks',{'dataset':'isolated-lab-'+report['started_at'],
                                          'data_origin':'isolated_lab',
                                          'result':{'evaluation':report['evaluation'],
                                                    'reproducibility':report['reproducibility'],
                                                    'experiment_ids':[r['id'] for r in report['scenarios']]}})
            report['benchmark_record_id']=stored['id']
            persisted=get('/api/benchmarks')['items']
            if not any(b.get('id')==stored['id'] for b in persisted):
                raise RuntimeError('Measured live benchmark was not persisted for the dashboard')
            report['status']='passed'
        finally:
            Path('benchmarks').mkdir(exist_ok=True)
            Path('benchmarks/results.live.local.json').write_text(json.dumps(report,indent=2,default=str))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--timeout',type=int,default=130)
    args=parser.parse_args()
    try:
        result=run(args.timeout)
        print(json.dumps({'status':result['status'],'scenarios':[(x['target'],x['mode'],x['status']) for x in result['scenarios']]},indent=2))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)}),file=sys.stderr)
        sys.exit(1)
