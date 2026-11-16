import test from "node:test";
import assert from "node:assert/strict";
import {createResultsClient,ResultsError} from "../../src/submission/static/results/api.mjs";
test("client uses finite API URLs with no credentials or cache",async()=>{
  const calls=[];const client=createResultsClient(async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>({success:true,data:{cases:[]}})};});
  assert.deepEqual(await client.list(),{cases:[]});await client.detail("normal");
  assert.equal(calls[0].url,"/api/result-demos");assert.equal(calls[1].url,"/api/result-demos/normal");
  assert.equal(calls[1].options.credentials,"omit");assert.equal(calls[1].options.cache,"no-store");
  assert.throws(()=>client.detail("../private"),ResultsError);
});
test("network, invalid JSON, null and server errors become safe messages",async()=>{
  const fetchers=[async()=>{throw new Error("secret");},async()=>({ok:true,json:async()=>{throw new Error("secret");}}),async()=>({ok:true,json:async()=>null}),async()=>({ok:false,json:async()=>({success:false,error:{code:"result_not_found",message:"secret"}})}),async()=>({ok:false,json:async()=>({success:false,error:{code:"unknown"}})})];
  for(const fetcher of fetchers) await assert.rejects(createResultsClient(fetcher).list(),(error)=>error instanceof ResultsError && !error.message.includes("secret"));
});
test("rate limited request stays a typed retryable error",async()=>{
  const client=createResultsClient(async()=>({ok:false,json:async()=>({success:false,error:{code:"result_rate_limited"}})}));
  await assert.rejects(client.list(),(error)=>error instanceof ResultsError && error.code === "result_rate_limited");
});

test("finite structure examples can be requested",async()=>{
  const calls=[];
  const client=createResultsClient(async(url)=>{calls.push(url);return {ok:true,json:async()=>({success:true,data:{}})};});
  await client.detail("docx_structure");await client.detail("hwpx_structure");
  assert.deepEqual(calls,["/api/result-demos/docx_structure","/api/result-demos/hwpx_structure"]);
});
