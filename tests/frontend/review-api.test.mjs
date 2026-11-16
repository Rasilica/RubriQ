import test from "node:test";
import assert from "node:assert/strict";
import {createReviewClient,ReviewError} from "../../src/submission/static/review/api.mjs";

const data={session_id:"session/demo",session_token:"memory-only-token",revision:0,items:[]};
const success=(value=data)=>({ok:true,json:async()=>({success:true,data:value})});

test("create keeps token private and authenticated calls send exact revision and JSON",async()=>{
  const calls=[];
  const client=createReviewClient(async(url,options)=>{calls.push({url,options});return success();});
  const publicData=await client.start();
  assert.equal(publicData.session_token,undefined);
  await client.read(); await client.save(3,[{title:"수정"}]); await client.confirm(4);
  assert.equal(calls[0].url,"/api/review-sessions");
  assert.equal(calls[0].options.headers["X-Review-Token"],undefined);
  assert.deepEqual(JSON.parse(calls[0].options.body),{});
  assert.equal(calls[1].url,"/api/review-sessions/session%2Fdemo");
  assert.equal(calls[1].options.body,undefined);
  assert.equal(calls[2].options.method,"PUT");
  assert.deepEqual(JSON.parse(calls[2].options.body),{expected_revision:3,items:[{title:"수정"}]});
  assert.deepEqual(JSON.parse(calls[3].options.body),{expected_revision:4});
  for(const {options} of calls){
    assert.equal(options.credentials,"omit"); assert.equal(options.cache,"no-store");
    assert.equal(options.headers["X-Review-Request"],"1");
    assert.equal(options.headers["Content-Type"],"application/json");
    assert.ok(options.signal instanceof AbortSignal);
  }
  assert.equal(calls[3].options.headers["X-Review-Token"],data.session_token);
});

test("new session creation does not forward previous session token",async()=>{
  const calls=[];
  const client=createReviewClient(async(url,options)=>{calls.push(options);return success();});
  await client.start(); await client.start();
  assert.equal(calls[1].headers["X-Review-Token"],undefined);
});

test("unstarted client rejects without a request",()=>{
  const client=createReviewClient(()=>assert.fail("network must not be called"));
  assert.throws(()=>client.read(),(error)=>error instanceof ReviewError && error.code === "session_unavailable");
});

test("transport failure and invalid JSON produce safe typed messages",async()=>{
  for(const fetcher of [async()=>{throw new Error("private payload");},async()=>({ok:true,json:async()=>{throw new Error("private payload");}})]){
    await assert.rejects(createReviewClient(fetcher).start(),(error)=>error instanceof ReviewError && !error.message.includes("private payload"));
  }
});

test("null JSON response is rejected as safe typed response error",async()=>{
  await assert.rejects(createReviewClient(async()=>({ok:true,json:async()=>null})).start(),(error)=>error instanceof ReviewError && error.code === "invalid_response");
});

test("server error details are not reflected into display message",async()=>{
  for(const code of ["stale_revision","unknown_server_code",undefined]){
    const fetcher=async()=>({ok:false,json:async()=>({success:false,error:{code,message:"private server contents"}})});
    await assert.rejects(createReviewClient(fetcher).start(),(error)=>error instanceof ReviewError && !error.message.includes("private server contents"));
  }
});
