"""Measured localhost ingestion benchmark. Writes unique events; no fabricated data."""
import argparse
import json
import os
import statistics
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batches',type=int,default=20)
    parser.add_argument('--batch-size',type=int,default=50)
    args=parser.parse_args()
    batches=max(1,min(args.batches,500))
    size=max(1,min(args.batch_size,100))
    secret=os.environ.get('CAUSALTRACE_API_KEY','')
    if len(secret)<16:parser.error('CAUSALTRACE_API_KEY is required')
    total=0;failures=0;times=[]
    start=time.perf_counter()
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=15,trust_env=False) as client:
        for _ in range(batches):
            now=time.time()
            events=[{'event_id':str(uuid.uuid4()),'service':'benchmark-ingestion',
                     'kind':'benchmark','timestamp':now,'latency_ms':0,'error':False}
                    for _ in range(size)]
            begin=time.perf_counter()
            response=client.post('/api/telemetry/events',json={'events':events},headers={'x-api-key':secret})
            elapsed=(time.perf_counter()-begin)*1000
            times.append(elapsed)
            if response.status_code>=400:
                failures+=1
            else:
                total+=response.json()['accepted']
    duration=time.perf_counter()-start
    samples=sorted(times)
    output={'origin':'measured loopback HTTP request timing, unique synthetic input events',
            'created_at':datetime.now(timezone.utc).isoformat(),
            'accepted_events':total,'failed_batches':failures,'attempted_events':batches*size,
            'throughput_events_per_second':total/duration,'p50_batch_latency_ms':statistics.median(samples),
            'p95_batch_latency_ms':samples[min(len(samples)-1,int(.95*(len(samples)-1)))],
            'elapsed_seconds':duration}
    path=Path('benchmarks/results.ingestion.local.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))
    if failures:raise SystemExit(1)
