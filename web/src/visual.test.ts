import {describe,it,expect} from 'vitest'
import {percent,timelineRows} from './api'
describe('metric formatting',()=>{it('expresses rates as percentages',()=>expect(percent(.25)).toBe('25.0%'))})

describe('chronological trend rendering',()=>{it('sorts stored windows by start time, not grouped service',()=>{
 const rows=[
  {service:'payment',start:20,requests:1,error_rate:1,latency_ms:20,throughput_rps:.2},
  {service:'auth',start:10,requests:1,error_rate:0,latency_ms:5,throughput_rps:.2},
  {service:'payment',start:5,requests:1,error_rate:0,latency_ms:4,throughput_rps:.2}]
 expect(timelineRows(rows).map(r=>r.start)).toEqual([5,10,20])
 expect(rows.map(r=>r.start)).toEqual([20,10,5]) // no mutation
})})
