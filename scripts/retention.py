"""Schedule externally (cron/K8s CronJob) to avoid runaway internal work."""
import os
import httpx
if __name__=="__main__":
    response=httpx.post("http://127.0.0.1:8000/api/admin/retention",
                        headers={"x-api-key":os.environ["CAUSALTRACE_API_KEY"]},timeout=30)
    response.raise_for_status()
    print(response.json())
