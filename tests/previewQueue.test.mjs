import test from 'node:test'
import assert from 'node:assert/strict'
import {createPreviewQueue} from '../web/src/previewQueue.js'
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
const tick=()=>new Promise(resolve=>setImmediate(resolve))
test('rapid edits are serialized and only the newest preview is shown',async()=>{
 const calls=[],applied=[],errors=[],states=[]
 const queue=createPreviewQueue({request:data=>{const job=deferred();calls.push({data,...job});return job.promise},apply:r=>applied.push(r),fail:e=>errors.push(e),loading:v=>states.push(v)})
 const first={theme:'Editorial'}
 queue.schedule(first,true)
 first.theme='Changed outside queue'
 queue.schedule({theme:'Signature'},true)
 assert.equal(calls.length,1)
 assert.equal(calls[0].data.theme,'Editorial')
 calls[0].resolve('old');await tick()
 assert.equal(calls.length,2);assert.equal(calls[1].data.theme,'Signature');assert.deepEqual(applied,[])
 calls[1].resolve('new');await tick()
 assert.deepEqual(applied,['new']);assert.deepEqual(errors,[]);assert.deepEqual(states,[true,false])
 queue.dispose()
})
test('leaving the editor invalidates an in-flight response',async()=>{
 const job=deferred(),applied=[],errors=[]
 const queue=createPreviewQueue({request:()=>job.promise,apply:r=>applied.push(r),fail:e=>errors.push(e),loading:()=>{}})
 queue.schedule({theme:'Mosaico'},true);queue.cancel();job.reject(Error('old failure'));await tick()
 assert.deepEqual(applied,[]);assert.deepEqual(errors,[]);queue.dispose()
})
