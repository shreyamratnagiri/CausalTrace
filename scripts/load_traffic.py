"""Bounded local-only traffic against the test e-commerce gateway."""
import argparse
import json
import time
import httpx

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--requests",type=int,default=160)
    parser.add_argument("--interval",type=float,default=.3)
    args=parser.parse_args()
    count=max(1,min(2000,args.requests))
    interval=max(.05,min(10,args.interval))
    success=0
    with httpx.Client(timeout=8,trust_env=False) as client:
        for _ in range(count):
            try:success+=int(client.get("http://127.0.0.1:8100/checkout").status_code==200)
            except httpx.HTTPError:pass
            time.sleep(interval)
    print(json.dumps({"endpoint":"localhost isolated gateway","attempts":count,"success":success,"failed":count-success}))
