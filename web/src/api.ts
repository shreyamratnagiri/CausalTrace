export type WindowRow = {service:string;start:number;requests:number;error_rate:number;latency_ms:number;throughput_rps:number}
export type Edge = {source:string;target:string;observations:number;error_rate:number;latency_ms:number;provenance:string[]}
export type Candidate = {service:string;score:number;onset:number;evidence:{kind:string;detail:string}[];contradictions:{kind:string;detail:string}[];affected_upstream_services:string[];uncertainty:string}
export type Anomaly = {service:string;metric:string;start:number;value:number;score:number;detector:string}
export type Incident = {id:string;title:string;status:string;created_at:string;version:number;affected_services:string[];hypotheses:Candidate[];evidence:Anomaly[]}
export type Experiment = {id:string;target:string;mode:string;status:string;started_at:string;result:Record<string,unknown>}
export type Trace = {trace_id:string;start_ns:number;end_ns:number;spans:number;errors:number}
export type Span = {span_id:string;parent_span_id:string|null;service:string;operation:string;start_ns:number;end_ns:number;error:boolean}
export type Metric = {service:string;name:string;timestamp:number;value:number;unit:string}
export type Service = {id:string;requests:number;error_rate:number;latency_ms:number;window_count:number}
export type Overview = {spans:number;traces:number;services:number;anomalies:number;windows:WindowRow[];edges:Edge[];candidates:Candidate[];scope:string}
let readKey = ''
// In-memory only. Do not persist the operator secret to cookies or localStorage.
export function setReadKey(key:string){readKey=key}
export async function getJSON<T>(path:string):Promise<T> {
 const r=await fetch(path,{headers:{Accept:'application/json',...(readKey?{'x-api-key':readKey}:{})},signal:AbortSignal.timeout(10000)})
 if(!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
 return r.json() as Promise<T>
}
export async function mutateJSON<T>(path:string,method:string,body:unknown,key:string):Promise<T>{
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json','x-api-key':key},body:JSON.stringify(body)})
 if(!r.ok)throw new Error(`${r.status}: ${await r.text()}`)
 return r.json() as Promise<T>
}
export const date=(secs:number)=>new Date(secs*1000).toLocaleString()
export const percent=(number:number)=>(number*100).toFixed(1)+'%'

// The backend groups aggregation rows by service, not global time. Plotting
// the API order as a timeline joins unrelated intervals across services.
export function timelineRows(rows:WindowRow[],limit=80):WindowRow[]{
 return [...rows].sort((a,b)=>a.start-b.start||a.service.localeCompare(b.service)).slice(-limit)
}
