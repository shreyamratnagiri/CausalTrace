"""Train a real IsolationForest and persist a clearly labeled experimental artifact."""
import argparse
import json
from pathlib import Path
from causaltrace.ml import evaluate,save

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="artifacts/iforest.pkl")
    args=parser.parse_args()
    model,metrics=evaluate()
    save(model,Path(args.output),metrics)
    print(json.dumps(metrics,indent=2))
