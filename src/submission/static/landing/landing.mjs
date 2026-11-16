import {initMotion} from '../brand-assets/motion.mjs';

const features = {
  structure: ['원본 구조', '문서가 어떻게 읽혔는지 확인하세요.', '읽은 문단과 표의 위치를 보고 읽지 못한 영역은 경고로 살펴봐요.'],
  evidence: ['실제 PDF 대조', '선택한 문구의 근거를 찾아보세요.', '문구가 확인된 페이지만 연결해요. 여러 후보나 찾지 못한 문구는 따로 구분하고, 추정 좌표는 만들지 않아요.'],
  library: ['문서 보관', '준비한 모습 그대로 다시 열어요.', '직접 저장한 원본과 구조, PDF를 목록에서 다시 열어요. 저장 당시의 환경과 현재 환경도 함께 보여줘요.'],
};
const doc = document;
initMotion(doc);
for (const button of doc.querySelectorAll('[data-feature]')) {
  button.addEventListener('click', () => {
    const content = features[button.dataset.feature];
    if (!content) return;
    for (const candidate of doc.querySelectorAll('[data-feature]')) candidate.setAttribute('aria-pressed', String(candidate === button));
    ['feature-kicker','feature-title','feature-description'].forEach((id,index) => {doc.getElementById(id).textContent = content[index];});
  });
}
const toggle = doc.querySelector('[data-demo-toggle]');
const demo = doc.querySelector('[data-motion-loop]');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
function reflectReduced() {
  toggle.hidden = reduced.matches;
}
reflectReduced();
reduced.addEventListener('change', reflectReduced);
toggle.addEventListener('click', () => {
  const paused = demo.dataset.motionPaused !== 'true';
  demo.dataset.motionPaused = String(paused);
  toggle.setAttribute('aria-pressed', String(paused));
  toggle.textContent = paused ? '시연 움직임 다시 재생' : '시연 움직임 일시정지';
  doc.dispatchEvent(new Event('motionstatechange'));
});
