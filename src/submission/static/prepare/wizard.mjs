// The preparation flow as ordered steps. Each finished stage unlocks only the next one.
export const STEPS=Object.freeze([
  {id:1,label:'문서 올리기',help:'안내문과 보고서를 올려 읽을 준비를 합니다.'},
  {id:2,label:'읽은 내용 확인',help:'두 문서를 제대로 읽었는지 원문과 PDF로 확인합니다.'},
  {id:3,label:'요구사항 뽑기',help:'AI가 안내문에서 지켜야 할 요구사항을 뽑습니다.'},
  {id:4,label:'요구사항 확정',help:'뽑힌 요구사항을 직접 고치고 검사 기준으로 확정합니다.'},
  {id:5,label:'보고서 검사',help:'확정한 기준으로 AI가 보고서를 검사합니다.'},
  {id:6,label:'결과·보관',help:'항목별 결과와 근거를 확인하고 문서를 보관합니다.'},
]);

const DEMO_HELP={3:'미리 저장한 예시 요구사항을 보여줍니다.',5:'확정한 기준으로 미리 저장한 예시 결과를 보여줍니다.'};
export const stepHelp=(step,demo)=>(demo&&DEMO_HELP[step])||STEPS[step-1].help;
export const pageTitle=step=>`${STEPS[step-1].label} | RubriQ`;

export function reachableStep(progress){
  if(!progress?.prepared)return 1;
  if(!progress.draft)return 3;
  if(!progress.confirmed)return 4;
  return progress.checked?6:5;
}

export function clampStep(step,progress){
  if(!Number.isInteger(step)||step<1)return 1;
  return Math.min(step,reachableStep(progress));
}
