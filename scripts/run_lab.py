"""Launch three real lab fault scenarios through the service API.

Never invokes Docker commands or accepts arbitrary targets. Requires active
Compose stack and API key. Results are preserved in the DB by the API.
"""
import json
import os
import time
import httpx

URL="http://127.0.0.1:8000"
KEY=os.environ["CAUSALTRACE_API_KEY"]
CASES=[("payment","error"),("cache","latency"),("database","db_exhaustion")]

def run():
    outcomes=[]
    with httpx.Client(timeout=15,headers={"x-api-key":KEY}) as client:
        for service,mode in CASES:
            r=client.post(URL+"/api/lab/experiments",json={"target":service,"mode":mode,"duration_seconds":15})
            r.raise_for_status()
            eid=r.json()["id"]
            for _ in range(50):
                time.sleep(2)
                record=client.get(URL+f"/api/lab/experiments/{eid}")
                record.raise_for_status()
                item=record.json()
                if item["status"] in {"completed","failed"}:break
            else:
                client.post(URL+f"/api/lab/experiments/{eid}/stop")
                item={"id":eid,"status":"timed_out"}
            outcomes.append(item)
    print(json.dumps(outcomes,indent=2))
    if any(a["status"]!="completed" for a in outcomes):raise SystemExit(1)

if __name__=="__main__":run()
