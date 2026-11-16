export const KIND_LABELS = Object.freeze({required:"필수",optional:"선택",conditional:"조건부"});

export function editableItems(items) {
  return items.map((item) => ({
    requirement_id:item.requirement_id, title:item.title, classification:item.classification,
    condition_description:item.condition_description,
    subconditions:item.subconditions.map((sub) => ({subcondition_id:sub.subcondition_id,description:sub.description})),
    included:item.included, exclusion_reason:item.exclusion_reason,
    application_status:item.application_status, application_reason:item.application_reason,
  }));
}

export function updateItem(items, id, patch) {
  return items.map((item) => {
    if (item.requirement_id !== id) return item;
    const merged = {...item,...patch,requirement_id:item.requirement_id};
    const updated = merged.classification === "conditional" ? merged : {...merged,condition_description:null};
    if (updated.classification !== item.classification || updated.condition_description !== item.condition_description) {
      return {...updated,application_status:"undetermined",application_reason:null};
    }
    return updated;
  });
}

export function updateSubcondition(items, id, subconditionId, description) {
  return items.map((item) => item.requirement_id !== id ? item : {
    ...item,
    subconditions:item.subconditions.map((sub) => sub.subcondition_id === subconditionId ? {...sub,description} : sub),
  });
}

export function hasChanges(saved, working) {
  return JSON.stringify(editableItems(saved)) !== JSON.stringify(editableItems(working));
}

export function confirmationBlocker({items,dirty,busy,revision,confirmed_revision}) {
  if (busy) return "busy";
  if (dirty) return "unsaved";
  const included = items.filter((item) => item.included);
  if (!included.length) return "empty";
  if (included.some((item) => item.classification === "conditional" && item.application_status === "undetermined")) return "undetermined";
  if (confirmed_revision === revision) return "confirmed";
  return null;
}

export function quoteSegments(raw, range) {
  const points = Array.from(raw);
  return [points.slice(0,range.start).join(""),points.slice(range.start,range.end).join(""),points.slice(range.end).join("")];
}

export function allCitations(original) {
  return [...original.citations,...original.subconditions.flatMap((sub) => sub.citations),...(original.condition?.citations ?? [])]
    .filter((cite,index,all) => all.findIndex((other) => other.block_id === cite.block_id && other.char_range.start === cite.char_range.start && other.char_range.end === cite.char_range.end) === index);
}

export function readingSegments(text) {
  const pattern=/[가-힣]+[ \t]+(?:수[ \t]+)?(?:합니다|있습니다|없습니다|됩니다|했습니다|않습니다)[.!?…]?/gu;
  const matches=[...text.matchAll(pattern)].filter((match)=>Array.from(match[0]).length <= 14);
  let cursor=0;
  const parts=matches.flatMap((match)=>{
    const before=text.slice(cursor,match.index);
    cursor=match.index+match[0].length;
    return [...(before ? [{text:before,keepTogether:false}] : []),{text:match[0],keepTogether:true}];
  });
  return [...parts,...(cursor < text.length ? [{text:text.slice(cursor),keepTogether:false}] : [])];
}
