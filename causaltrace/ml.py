"""Reproducible fitted Isolation Forest comparator; does not infer root causes.

Training uses only healthy windows; held-out faults are labeled for evaluation.
The model is strictly experimental until calibrated on real observability data.
"""
from pathlib import Path
import json
import pickle
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_recall_fscore_support

FEATURES=("error_rate","latency_ms","throughput_rps")
MODEL_VERSION="iforest-v1"

def features(rows:list[dict])->np.ndarray:
    return np.asarray([[float(row[k]) for k in FEATURES] for row in rows],dtype=np.float64).reshape(-1,len(FEATURES))

def generate_fixture(seed:int, n:int=160, fault_rate:float=0.25):
    rng=np.random.default_rng(seed)
    rows=[];labels=[]
    for i in range(n):
        fault=rng.random()<fault_rate
        latency=max(5,float(rng.normal(110,12)))
        errors=float(rng.beta(1,80))
        throughput=max(.2,float(rng.normal(8,1.0)))
        category=i%4
        if fault:
            if category==0: latency+=rng.uniform(180,450)
            elif category==1: errors=min(1.,errors+rng.uniform(.45,.85))
            elif category==2: throughput*=rng.uniform(.04,.2)
            else: latency+=rng.uniform(100,200);errors+=.35
        rows.append({"service":"evaluation-fixture","start":i*5,"requests":max(1,int(throughput*5)),
                     "error_rate":errors,"latency_ms":latency,"throughput_rps":throughput})
        labels.append(int(fault))
    return rows,labels

def train(rows:list[dict],seed:int=42,contamination:float=.03):
    model=IsolationForest(n_estimators=150,random_state=seed,contamination=contamination,n_jobs=1)
    model.fit(features(rows))
    return model

def predict(model,rows:list[dict]):
    return (model.predict(features(rows))==-1).astype(int).tolist()

def evaluate():
    train_rows,_=generate_fixture(seed=1001,n=500,fault_rate=0)
    validation_rows,val_truth=generate_fixture(seed=2002,n=200,fault_rate=.25)
    test_rows,test_truth=generate_fixture(seed=3003,n=200,fault_rate=.25)
    model=train(train_rows)
    best=(None,-1)
    # Validation-only threshold selection. Use decision_function (higher = more normal).
    val=model.decision_function(features(validation_rows))
    for threshold in [-.12,-.09,-.06,-.03,0,.03,.06]:
        guess=(val<threshold).astype(int)
        precision,recall,f1,_=precision_recall_fscore_support(val_truth,guess,average="binary",zero_division=0)
        if f1>best[1]: best=(threshold,float(f1))
    scores=model.decision_function(features(test_rows))
    pred=(scores<best[0]).astype(int).tolist()
    from .analytics import detection_scores
    result=detection_scores(test_truth,pred)
    result.update({"model":MODEL_VERSION,"test_seed":3003,"train_seed":1001,
                   "validation_seed":2002,"selected_threshold":best[0],
                   "data_origin":"reproducible synthetic mathematical fixture, NOT real fault injections"})
    return model,result

def save(model,path:Path,metadata:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    # pickle is inherently unsafe to untrusted files: models must be generated in-process.
    with path.open("wb") as f:pickle.dump(model,f)
    path.with_suffix(".json").write_text(json.dumps(metadata,indent=2))

def load_trusted(path:Path):
    with path.open("rb") as f:return pickle.load(f)
