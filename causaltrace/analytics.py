"""Bounded trace reconstruction, metric windows, statistical baselines and evidence ranking.

Every result is observational. Graph edges are caller -> callee. No fault labels in ranking.
"""
from collections import defaultdict
from itertools import islice
import re
from statistics import median
import math
import networkx as nx


def reconstruct(spans: list[dict]) -> dict:
    """Build a bounded, cycle-aware trace DAG with conservative duration bounds.

    Distributed wall-clock timestamps are not a safe basis for ordering events
    across hosts. Parent IDs establish relationships; accumulated span durations
    are explicitly an *upper-bound estimate*, not measured critical-path wall time.
    """
    unique={s["span_id"]:s for s in spans}
    graph=nx.DiGraph()
    graph.add_nodes_from(unique)
    roots=[]
    missing=[]
    cyclic=False
    for sid,span in unique.items():
        parent=span.get("parent_span_id")
        if parent==sid:
            cyclic=True
            roots.append(sid)
        elif parent in unique:
            graph.add_edge(parent,sid)
        else:
            roots.append(sid)
            if parent:
                missing.append(sid)
    # A malformed trace must not cause infinite recursion or an empty path.
    while not nx.is_directed_acyclic_graph(graph):
        cyclic=True
        cycle=nx.find_cycle(graph)
        first=sorted(cycle,key=lambda edge:(edge[0],edge[1]))[0]
        graph.remove_edge(*first[:2])
    if unique and not roots:
        roots=[sid for sid in sorted(unique) if graph.in_degree(sid)==0]
    durations={sid:max(0.,(s["end_ns"]-s["start_ns"])/1e6) for sid,s in unique.items()}
    longest=dict(durations)
    previous:dict[str,str]={}
    for sid in nx.topological_sort(graph):
        for child in graph.successors(sid):
            candidate=longest[sid]+durations[child]
            if candidate>longest[child]:
                longest[child]=candidate
                previous[child]=sid
    cp=0.
    cp_ids=[]
    if longest:
        last=max(sorted(longest),key=lambda k:longest[k])
        cp=longest[last]
        while last not in cp_ids:
            cp_ids.append(last)
            if last not in previous:
                break
            last=previous[last]
        cp_ids.reverse()
    start=min((s["start_ns"] for s in unique.values()),default=0)
    end=max((s["end_ns"] for s in unique.values()),default=0)
    return {"spans":sorted(unique.values(),key=lambda s:(s["start_ns"],s["span_id"])),
            "missing_parent_span_ids":sorted(missing),"root_span_ids":sorted(set(roots)),
            "wall_duration_ms":max(0,(end-start)/1e6),
            "critical_path_upper_bound_ms":round(cp,3),"critical_path_span_ids":cp_ids,
            "cyclic_parent_graph":cyclic,
            "warning":"Summed span durations are an upper bound when spans overlap or clocks skew"}


def extract_edges(spans: list[dict]) -> list[dict]:
    """Recover directly observed server edges and explicitly inferred client targets.

    If the remote server's span is missing, the outbound client's server.address
    is evidence of an *attempted* call, not confirmation that the peer received
    it. Never label those edges as directly observed.
    """
    by_id = {s["span_id"]: s for s in spans}
    linked_clients = {s.get("parent_span_id") for s in spans if
                      (s.get("parent_span_id") in by_id and
                       by_id[s["parent_span_id"]]["service"] != s["service"])}
    edges = []
    for s in spans:
        parent = by_id.get(s.get("parent_span_id"))
        if parent and parent["service"] != s["service"]:
            edges.append({"source": parent["service"], "target": s["service"],
                          "timestamp_ns": s["start_ns"], "trace_id": s["trace_id"],
                          "latency_ms": max(0, (s["end_ns"]-s["start_ns"])/1_000_000),
                          "error": bool(s["error"]), "provenance": "span-parent"})
        elif (s["span_id"] not in linked_clients and
              s.get("attributes",{}).get("span.kind") == "client"):
            remote = s.get("attributes",{}).get("server.address", "")
            if (isinstance(remote,str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,99}",remote)
                    and remote != s["service"]):
                edges.append({"source": s["service"], "target": remote,
                              "timestamp_ns": s["start_ns"], "trace_id": s["trace_id"],
                              "latency_ms": max(0, (s["end_ns"]-s["start_ns"])/1_000_000),
                              "error": bool(s["error"]), "provenance": "client-target-unconfirmed"})
    return edges


def aggregate(spans: list[dict], window_seconds: int = 5) -> list[dict]:
    """Aggregate SERVER spans so each RPC is counted once; exclude CLIENT spans."""
    groups = defaultdict(list)
    for s in spans:
        if s.get("attributes", {}).get("span.kind") == "client":
            continue
        t = s["start_ns"] // (window_seconds * 1_000_000_000)
        groups[(s["service"], int(t))].append(s)
    rows = []
    for (service, bucket), items in sorted(groups.items(), key=lambda x: (x[0][0],x[0][1])):
        durations = sorted(max(0,(x["end_ns"]-x["start_ns"])/1e6) for x in items)
        errors = sum(bool(x["error"]) for x in items)
        rows.append({"service":service,"start":bucket*window_seconds,
                     "requests":len(items),"error_rate":errors/len(items),
                     "latency_ms":durations[len(durations)//2],
                     "throughput_rps":len(items)/window_seconds})
    return rows


def threshold_anomalies(rows: list[dict], max_error_rate=.20, max_latency_ms=500.) -> list[dict]:
    result=[]
    for r in rows:
        for metric, bound in (("error_rate",max_error_rate),("latency_ms",max_latency_ms)):
            if r[metric] > bound:
                result.append({"service":r["service"],"start":r["start"],"metric":metric,
                               "value":r[metric],"baseline":bound,"score":min(20.,r[metric]/max(bound,1e-6)),
                               "detector":"threshold","evidence_count":r["requests"]})
    return result


def robust_anomalies(rows: list[dict], minimum_samples=5, lookback=30, z_threshold=3.5) -> list[dict]:
    groups=defaultdict(list)
    for row in rows: groups[row["service"]].append(row)
    anomalies=[]
    for service,series in groups.items():
        series.sort(key=lambda r:r["start"])
        for i,r in enumerate(series):
            earlier=series[max(0,i-lookback):i]
            if len(earlier)<minimum_samples or r["requests"]<1:
                continue
            for name, floor in (("error_rate",.035),("latency_ms",10.),("throughput_rps",.15)):
                data=[float(x[name]) for x in earlier]
                center=median(data)
                mad=median(abs(x-center) for x in data)
                scale=max(1.4826*mad,floor)
                score=(float(r[name])-center)/scale
                # Throughput down is anomalous; upward bursts also relevant.
                if abs(score)>=z_threshold and (name!="error_rate" or score>0):
                    anomalies.append({"service":service,"start":r["start"],"metric":name,
                                      "value":r[name],"baseline":round(center,4),
                                      "score":round(abs(score),3),"direction":"increase" if score>0 else "decrease",
                                      "detector":"rolling_mad","evidence_count":r["requests"]})
    return sorted(anomalies,key=lambda a:(a["start"],a["service"],a["metric"]))


def graph_topology(edges: list[dict]) -> dict:
    G=nx.DiGraph()
    for e in edges:
        G.add_edge(e["source"],e["target"])
    return {"nodes":sorted(G.nodes), "edges":[{"source":a,"target":b} for a,b in sorted(G.edges)],
            "cycles":list(islice(nx.simple_cycles(G),20))}


def rank_causes(anomalies: list[dict], edges: list[dict], deployments: list[dict] | None = None,
                *, mode: str = "full") -> list[dict]:
    """Graph-temporal evidence score: H=1.6S + 1.2P + .7D + .6L - 1.5C.

    S severity, P affected ancestor propagation, D recent change, L consistent lag,
    C earlier affected ancestor contradictions. Terms normalized for graph size.
    Modes enable reproducible ablations. Scores are not calibrated probabilities.
    """
    if mode not in {"severity", "graph", "temporal", "full"}:
        raise ValueError("Unknown ablation mode")
    earliest: dict[str,float]={}; severity=defaultdict(float)
    for a in anomalies:
        s=a["service"]
        earliest[s]=min(earliest.get(s,math.inf),float(a["start"]))
        severity[s]=max(severity[s],min(float(a["score"])/10,1.0))
    G=nx.DiGraph()
    for e in edges: G.add_edge(e["source"],e["target"])
    deployments=deployments or []
    ranks=[]
    for service in sorted(earliest):
        predecessors=nx.ancestors(G,service) if service in G else set()
        affected=[s for s in predecessors if s in earliest]
        consistent=[s for s in affected if earliest[s]>=earliest[service]]
        contradictory=[s for s in affected if earliest[s]<earliest[service]]
        propagation=len(affected)/max(1,len(G.nodes)-1)
        lag_agreement=len(consistent)/max(1,len(affected))
        contradiction=len(contradictory)/max(1,len(affected))
        changes=[d for d in deployments if d["service"]==service and 0<=earliest[service]-float(d["timestamp"])<=300]
        score=1.6*severity[service]
        if mode in {"graph","temporal","full"}: score+=1.2*propagation
        if mode in {"temporal","full"}: score+=.6*lag_agreement-1.5*contradiction
        if mode=="full": score+=.7*min(1,len(changes))
        ranks.append({"service":service,"score":round(score,4),
                      "evidence":[{"kind":"anomaly","detail":f"Normalized anomaly severity {severity[service]:.3f}"},
                                  {"kind":"topology","detail":f"{len(affected)} affected upstream callers / {len(predecessors)} observed callers"},
                                  {"kind":"temporal","detail":f"{len(consistent)} affected callers observed no earlier than candidate"}]
                      + ([{"kind":"change","detail":f"{len(changes)} deployment(s) within prior 300 seconds"}] if changes else []),
                      "contradictions":[{"kind":"temporal","detail":f"{s} anomaly preceded candidate"} for s in contradictory[:10]],
                      "affected_upstream_services":sorted(affected),"onset":earliest[service],
                      "uncertainty":"Uncalibrated relative ranking; intervention is required for causal support"})
    return sorted(ranks,key=lambda c:(-c["score"],c["service"]))


def detection_scores(truth: list[int], predicted: list[int]) -> dict:
    if len(truth)!=len(predicted): raise ValueError("Mismatched labels")
    tp=sum(a==1 and b==1 for a,b in zip(truth,predicted)); fp=sum(a==0 and b==1 for a,b in zip(truth,predicted))
    fn=sum(a==1 and b==0 for a,b in zip(truth,predicted)); tn=len(truth)-tp-fp-fn
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    return {"precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0,
            "false_alert_rate":fp/(fp+tn) if fp+tn else 0,"samples":len(truth)}


def ranking_scores(ground_truth: list[str], rankings: list[list[str]]) -> dict:
    if len(ground_truth)!=len(rankings):raise ValueError("Mismatched cases")
    if not ground_truth:return {"top1":0,"top3":0,"mrr":0,"cases":0}
    ranks=[(a.index(t)+1 if t in a else math.inf) for t,a in zip(ground_truth,rankings)]
    return {"top1":sum(r==1 for r in ranks)/len(ranks),"top3":sum(r<=3 for r in ranks)/len(ranks),
            "mrr":sum(1/r if math.isfinite(r) else 0 for r in ranks)/len(ranks),"cases":len(ranks)}
