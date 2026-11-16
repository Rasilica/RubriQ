import {unicodeRange} from './state.mjs';

const bounded=(value,max)=>typeof value==='string'&&value.trim().length>0&&[...value].length<=max;
function requireValue(condition){if(!condition)throw new Error('invalid_ollama_result');}

export function ollamaSelection(text,start,end){
  const range=unicodeRange(text,start,end);
  requireValue(range.end-range.start<=4000);
  return range;
}

export function validateOllamaModels(value){
  requireValue(value?.provider==='ollama'&&Array.isArray(value.models)&&value.models.length<=100);
  const names=value.models.map(model=>{requireValue(bounded(model?.name,200));return model.name;});
  requireValue(new Set(names).size===names.length);
  return names.map(name=>({name}));
}

export function validateOllamaRewrite(value,{block,range,source,model}){
  const points=[...block.raw_text];
  requireValue(Number.isInteger(range?.start)&&Number.isInteger(range?.end)&&range.start>=0&&range.end>range.start&&range.end<=points.length&&range.end-range.start<=4000);
  requireValue(bounded(model,200)&&value?.provider==='ollama'&&value.model===model&&value.llm_executed===true);
  requireValue(/^[a-f0-9]{64}$/u.test(source)&&value.source_sha256===source&&value.block_id===block.block_id&&value.start===range.start&&value.end===range.end);
  requireValue(value.original===points.slice(range.start,range.end).join('')&&bounded(value.suggestion,8000));
  return value;
}

export function createOllamaRequest({resources,key,request,validate,onState}){
  return {
    async run(context){
      const operation=resources.begin(key);onState({status:'running'});
      try{
        const value=await request(context,operation.signal);
        if(!resources.current(operation))return;
        onState({status:'complete',result:validate(value,context)});
      }catch(error){if(resources.current(operation))onState({status:'error',error});}
    },
  };
}
