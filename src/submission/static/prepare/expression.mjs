import {unicodeRange} from './state.mjs';

const MAX_TEXT=20000;
const REVISION='2f3d943d08056b612a92e12bfb72ea94dd2acd18';
const bounded=(value,max)=>typeof value==='string'&&value.length>0&&value.length<=max;
const validRange=(range,length)=>Number.isInteger(range?.start)&&Number.isInteger(range?.end)&&range.start>=0&&range.end>range.start&&range.end<=length;
function requireValue(condition){if(!condition)throw new Error('invalid_expression_result');}

export function expressionSelection(text,start,end){
  const range=unicodeRange(text,start,end);
  requireValue(range.end-range.start<=MAX_TEXT);
  return range;
}

export function textareaRange(text,range){
  const points=[...text];requireValue(validRange(range,points.length));
  return {start:points.slice(0,range.start).join('').length,end:points.slice(0,range.end).join('').length};
}

export function validateExpression(value,{block,range,source}){
  const points=[...block.raw_text];
  requireValue(validRange(range,points.length)&&range.end-range.start<=MAX_TEXT);
  requireValue(value?.engine==='im-not-ai-local'&&value.revision===REVISION&&value.scope==='selected_text'&&value.llm_executed===false);
  requireValue(value.source_sha256===source&&/^[a-f0-9]{64}$/u.test(source)&&value.block_id===block.block_id&&value.start===range.start&&value.end===range.end);
  requireValue(Array.isArray(value.findings)&&value.findings.length<=100);
  for(const finding of value.findings){
    requireValue(validRange(finding,points.length)&&finding.start>=range.start&&finding.end<=range.end);
    requireValue(bounded(finding.pattern_id,80)&&bounded(finding.label,200)&&bounded(finding.explanation,2000));
    requireValue(finding.suggestion===null||bounded(finding.suggestion,2000));
    requireValue(finding.original===points.slice(finding.start,finding.end).join(''));
  }
  requireValue(Array.isArray(value.metrics)&&value.metrics.length<=30);
  for(const metric of value.metrics)requireValue(bounded(metric.id,80)&&bounded(metric.label,200)&&Number.isSafeInteger(metric.count)&&metric.count>=0&&metric.count<=MAX_TEXT);
  requireValue(Array.isArray(value.warnings)&&value.warnings.length<=20&&value.warnings.every(warning=>bounded(warning,2000)));
  return value;
}

export function createExpressionCheck({resources,request,onState}){
  return {
    async run(context){
      const operation=resources.begin('expression');onState({status:'running'});
      try{
        const value=await request(context,operation.signal);
        if(!resources.current(operation))return;
        const result=validateExpression(value,context);
        onState({status:'complete',result});
      }catch(error){if(resources.current(operation))onState({status:'error',error});}
    },
  };
}
