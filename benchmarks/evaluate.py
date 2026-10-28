"""Offline seeded metric ML and graph ranking ABM evaluation.

Explicit synthetic fault scenarios are used solely for regression/evaluation,
NOT claims of actual microservice lab intervention accuracy.
"""
import json
from collections import defaultdict
from pathlib import Path
import random
from causaltrace.analytics import ranking_scores, rank_causes
from causaltrace.ml import evaluate

GRAPH=[("gateway","auth"),("gateway","catalog"),("gateway","checkout"),
       ("checkout","payment"),("checkout","inventory"),("checkout","notification"),
       ("payment","database"),("inventory","database"),("catalog","cache")]
SERVICES=sorted({s for pair in GRAPH for s in pair})
EDGES=[{"source":a,"target":b} for a,b in GRAPH]

def scenarios(seed:int=3003,cases:int=80):
    rng=random.Random(seed)
    result=[]
    for index in range(cases):
        target=SERVICES[index%len(SERVICES)]
        # Ground-truth is intentionally separate from feature ranking.
        # Synthetic fault propagation proceeds backwards to callers.
        impacted={target};changes=True
        while changes:
            old=len(impacted)
            impacted|={a for a,b in GRAPH if b in impacted}
            changes=len(impacted)>old
        onset=1_780_000_000.+index*600
        anomalies=[]
        for s in sorted(impacted):
            start=onset+(0 if s==target else rng.randint(5,25))
            anomalies.append({"service":s,"start":start,"score":rng.uniform(3.5,9),"metric":"error_rate"})
        # unrelated noise in a few scenarios exposes model weaknesses
        if rng.random()<.20:
            other=rng.choice(SERVICES)
            if other not in impacted:
                anomalies.append({"service":other,"start":onset-rng.randint(1,15),"score":rng.uniform(3.6,6)})
        deployments=[{"service":target,"timestamp":onset-60}] if rng.random()<.5 else []
        result.append((target,anomalies,deployments))
    return result

def evaluate_ranking():
    cases=scenarios()
    results={}
    for mode in ("severity","graph","temporal","full"):
        ranks=[[r["service"] for r in rank_causes(a,EDGES,d,mode=mode)] for _,a,d in cases]
        results[mode]=ranking_scores([t for t,_,_ in cases],ranks)
    by_fault_category=defaultdict(list)
    for truth,anomalies,deployments in cases:
        ranking=[r["service"] for r in rank_causes(anomalies,EDGES,deployments)]
        by_fault_category[truth].append(1 if ranking and ranking[0]==truth else 0)
    return {"ablation":results,"by_target_top1":{k:sum(v)/len(v) for k,v in by_fault_category.items()},
            "cases":len(cases),"test_seed":3003,
            "data_origin":"synthetic propagation fixture; NOT instrumented lab observations"}

if __name__=="__main__":
    import argparse
    import os
    parser=argparse.ArgumentParser()
    parser.add_argument("--publish",action="store_true",help="Persist explicitly labeled synthetic fixture results to local API")
    args=parser.parse_args()
    _,ml=evaluate()
    record={"ml_detection":ml,"ranking":evaluate_ranking()}
    path=Path("benchmarks/results.synthetic.json")
    path.write_text(json.dumps(record,indent=2))
    print(json.dumps(record,indent=2))
    if args.publish:
        import httpx
        with httpx.Client(timeout=15) as client:
            response=client.post("http://127.0.0.1:8000/api/benchmarks",
                headers={"x-api-key":os.environ["CAUSALTRACE_API_KEY"]},
                json={"dataset":"seeded-synthetic-fixture-v1","data_origin":"synthetic_fixture","result":record})
            response.raise_for_status()
            print("Stored separately labeled fixture evaluation:",response.json()["id"])
