import test from "node:test";
import assert from "node:assert/strict";
import { editableItems, updateItem, updateSubcondition, hasChanges, confirmationBlocker, quoteSegments, allCitations, readingSegments } from "../../src/submission/static/review/state.mjs";

const item = Object.freeze({requirement_id:"R1",title:"조건",classification:"conditional",condition_description:"개인정보 사용",subconditions:[{subcondition_id:"S1",description:"설명"}],included:true,exclusion_reason:null,application_status:"applies",application_reason:"사용함",edited_fields:["title"]});

test("mutation body excludes server metadata and preserves immutable IDs", () => {
  const editable = editableItems([item])[0];
  assert.equal("edited_fields" in editable,false);
  assert.equal(editable.requirement_id,"R1");
  assert.notEqual(editable.subconditions,item.subconditions);
});
test("condition edit resets prior application confirmation without mutating input", () => {
  const changed = updateItem([item],"R1",{condition_description:"새 조건"})[0];
  assert.equal(changed.application_status,"undetermined");
  assert.equal(changed.application_reason,null);
  assert.equal(item.application_status,"applies");
});
test("ordinary title edit preserves application decision", () => {
  const changed = updateItem([item],"R1",{title:"새 제목"})[0];
  assert.equal(changed.application_status,"applies");
  assert.equal(hasChanges([item],[changed]),true);
  assert.equal(hasChanges([item],[{...item,edited_fields:[]}]),false);
});
test("confirmation distinguishes unsaved, undecided, excluded and already confirmed", () => {
  assert.equal(confirmationBlocker({items:[item],dirty:true,busy:false,revision:1,confirmed_revision:null}),"unsaved");
  assert.equal(confirmationBlocker({items:[{...item,application_status:"undetermined"}],dirty:false,busy:false,revision:1,confirmed_revision:null}),"undetermined");
  assert.equal(confirmationBlocker({items:[{...item,included:false}],dirty:false,busy:false,revision:1,confirmed_revision:null}),"empty");
  assert.equal(confirmationBlocker({items:[item],dirty:false,busy:false,revision:1,confirmed_revision:1}),"confirmed");
  assert.equal(confirmationBlocker({items:[item],dirty:false,busy:false,revision:1,confirmed_revision:null}),null);
});
test("quotation offsets use Python Unicode code points including emoji and combining marks", () => {
  assert.deepEqual(quoteSegments("앞😀e\u0301뒤",{start:1,end:4}),["앞","😀e\u0301","뒤"]);
});
test("two subcondition edits before save preserve both current values", () => {
  const original=[{...item,subconditions:[{subcondition_id:"S1",description:"첫째"},{subcondition_id:"S2",description:"둘째"}]}];
  const first=updateSubcondition(original,"R1","S1","첫째 수정");
  const second=updateSubcondition(first,"R1","S2","둘째 수정");
  assert.deepEqual(second[0].subconditions.map((sub)=>sub.description),["첫째 수정","둘째 수정"]);
  assert.equal(original[0].subconditions[0].description,"첫째");
});
test("classification clears irrelevant condition and immutable ID stays unchanged", () => {
  const other={...item,requirement_id:"R2"};
  const changed=updateItem([item,other],"R1",{requirement_id:"bad",classification:"required"});
  assert.equal(changed[0].requirement_id,"R1");
  assert.equal(changed[0].condition_description,null);
  assert.equal(changed[0].application_status,"undetermined");
  assert.equal(changed[1],other);
  assert.equal(confirmationBlocker({items:[item],busy:true}),"busy");
});
test("citations include child and condition sources and remove same-range duplicates", () => {
  const cite={block_id:"b1",char_range:{start:0,end:2},quote:"원문"};
  const second={...cite,char_range:{start:3,end:5}};
  assert.deepEqual(allCitations({citations:[cite],subconditions:[{citations:[cite,second]}],condition:{citations:[second]}}),[cite,second]);
  assert.deepEqual(allCitations({citations:[],subconditions:[],condition:null}),[]);
});
test("Korean auxiliary phrase wrappers preserve exact Unicode text and original spacing",()=>{
  const raw="😀 안내\n자세히 설명해야 합니다.\t분량은 이하여야 합니다. 만들 수 있습니다. e\u0301";
  const parts=readingSegments(raw);
  assert.equal(parts.map((part)=>part.text).join(""),raw);
  assert.deepEqual(parts.filter((part)=>part.keepTogether).map((part)=>part.text),["설명해야 합니다.","이하여야 합니다.","만들 수 있습니다."]);
  const [before,quote,after]=quoteSegments(raw,{start:8,end:19});
  assert.equal([before,quote,after].flatMap(readingSegments).map((part)=>part.text).join(""),raw);
});
test("reading segmentation keeps newlines and avoids oversized unbreakable phrases",()=>{
  const raw="문장은\n합니다. 아주아주아주아주아주아주아주긴단어 합니다.";
  assert.deepEqual(readingSegments(raw),[{text:raw,keepTogether:false}]);
  assert.deepEqual(readingSegments(""),[]);
});
