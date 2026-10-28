import {useMemo,useState} from 'react'
import type {Edge,WindowRow} from './api'
import {timelineRows} from './api'
export function Trend({rows,metric,label}:{rows:WindowRow[];metric:'error_rate'|'latency_ms'|'throughput_rps';label:string}){
 const points=timelineRows(rows),max=Math.max(.01,...points.map(r=>r[metric]));
 const positions=points.map((r,i)=>`${24+(i/Math.max(1,points.length-1))*666},${165-r[metric]/max*135}`).join(' ')
 return <section className="panel"><h3>{label}</h3>{!points.length?<p className="muted">No stored telemetry</p>:<svg role="img" aria-label={`${label}: ${points.length} actual aggregate windows`} viewBox="0 0 720 190" className="chart"><line x1="24" y1="165" x2="695" y2="165" stroke="#6b7487"/><polyline points={positions} stroke="#42dbb4" strokeWidth="2.5" fill="none"/><text x="24" y="18" fill="#aabbd3" fontSize="14">Max: {max.toFixed(2)}</text><text x="600" y="183" fill="#aabbd3" fontSize="12">Latest →</text></svg>}</section>
}
export function DependencyMap({edges,onService}:{edges:Edge[];onService:(service:string)=>void}){
 const [selected,setSelected]=useState<string|null>(null)
 const nodes=useMemo(()=>Array.from(new Set(edges.flatMap(e=>[e.source,e.target]))).sort(),[edges])
 const positions=useMemo(()=>{
  const map=new Map<string,{x:number;y:number}>();const n=nodes.length
  nodes.forEach((s,i)=>{const theta=(2*Math.PI*i)/Math.max(1,n)-Math.PI/2;map.set(s,{x:390+270*Math.cos(theta),y:230+165*Math.sin(theta)})})
  return map
 },[nodes])
 return <section className="panel"><h3>Service dependency evidence</h3><p className="muted">Arrows follow caller → callee. Some links may be inferred from an outbound client span when the server span is missing; click a node to inspect service metrics.</p>
 {!nodes.length?<p>No observed span-parent dependency edges yet.</p>:<><svg viewBox="0 0 780 475" role="img" aria-label="Directed dependency graph based on stored traces" className="graph"><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#748dad"/></marker></defs>
 {edges.map((edge,i)=>{const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)return null;return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={edge.error_rate>.2?'#fb8f91':'#748dad'} strokeWidth={Math.min(4,1+Math.log2(1+edge.observations)/3)} markerEnd="url(#arrow)" opacity=".68"/>})}
 {nodes.map(s=>{const p=positions.get(s)!;return <g key={s} className="node" role="button" tabIndex={0} aria-label={`Inspect ${s}`} onClick={()=>{setSelected(s);onService(s)}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(s);onService(s)}}}><circle cx={p.x} cy={p.y} r="40" fill={selected===s?'#1e6064':'#203650'} stroke="#67b6c4" strokeWidth="1.5"/><text x={p.x} y={p.y+4} fill="#e8f3ff" fontSize="12" textAnchor="middle">{s}</text></g>})}</svg><p className="muted">{edges.filter(e=>!e.provenance.includes("client-target-unconfirmed")).length} directly observed and {edges.filter(e=>e.provenance.includes("client-target-unconfirmed")).length} links with unconfirmed client-target evidence; {nodes.length} services. Edges are not proof of causality.</p></>}</section>
}
