"""Small bounded local-only performance probe; writes measured data if run."""
import argparse
import os
import json
import statistics
import time
import httpx

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:8000")
    parser.add_argument("--repeats",type=int,default=50)
    a=parser.parse_args()
    if a.url not in {"http://127.0.0.1:8000","http://localhost:8000"}:
        parser.error("Probe is restricted to localhost")
    data=[]
    with httpx.Client(timeout=15,trust_env=False,headers={'x-api-key':os.environ.get('CAUSALTRACE_API_KEY','')}) as client:
        for _ in range(max(1,min(500,a.repeats))):
            t=time.perf_counter()
            res=client.get(a.url+"/api/services");res.raise_for_status()
            data.append((time.perf_counter()-t)*1000)
    arr=sorted(data)
    print(json.dumps({"route":"/api/services","samples":len(arr),"p50_ms":statistics.median(arr),
                     "p95_ms":arr[min(len(arr)-1,int(len(arr)*.95))],"data_origin":"actual HTTP timing"},indent=2))
