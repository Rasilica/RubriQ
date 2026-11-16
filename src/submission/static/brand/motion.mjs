const controllers = new WeakMap();

export function motionAllowed({reduced, hidden, visible, paused}) {
  return !reduced && !hidden && visible && !paused;
}

export function initMotion(doc = document) {
  if (controllers.has(doc)) return controllers.get(doc);
  const win = doc.defaultView;
  const media = win.matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new WeakSet();
  const animations = new Set();
  const loops = new Map();
  let disposed = false;
  const style = win.getComputedStyle(doc.documentElement);
  const number = (token, fallback) => parseFloat(style.getPropertyValue(token)) || fallback;
  const duration = number('--motion-reveal', 650);
  const stagger = number('--motion-stagger', 65);
  const distance = number('--motion-distance', 10);
  const blur = number('--motion-blur', 5);
  const ease = style.getPropertyValue('--motion-ease').trim() || 'cubic-bezier(.22,1,.36,1)';

  function reveal(node) {
    if (seen.has(node)) return;
    seen.add(node);
    if (media.matches || typeof node.animate !== 'function') return;
    const parts = node.querySelectorAll('[data-reveal-word]');
    const targets = parts.length ? [...parts] : [node];
    targets.forEach((target, index) => {
      const animation = target.animate([
        {opacity:0.001, transform:`translateY(${distance}px)`, filter:`blur(${blur}px)`},
        {opacity:1, transform:'translateY(0)', filter:'blur(0)'},
      ], {duration, delay:index * stagger, easing:ease, fill:'backwards'});
      animations.add(animation);
      animation.finished.then(() => animations.delete(animation), () => animations.delete(animation));
    });
  }

  function syncLoops() {
    for (const [node, entry] of loops) {
      const allowed = motionAllowed({reduced:media.matches, hidden:doc.hidden,
        visible:entry.visible, paused:node.dataset.motionPaused === 'true'});
      if (media.matches) {
        entry.animations.forEach(animation => animation.cancel());
        entry.animations = [];
      } else if (observer && entry.animations.length === 0) {
        entry.animations = entry.parts.map((part, index) => {
          const animation = part.animate([{opacity:.45},{opacity:1},{opacity:.45}],
            {duration:number('--motion-pulse',1500), delay:index * number('--motion-pulse-stagger',100), iterations:Infinity});
          animation.pause();
          return animation;
        });
      }
      for (const animation of entry.animations) allowed ? animation.play() : animation.pause();
    }
    if (media.matches) for (const animation of animations) animation.cancel();
  }

  const observer = typeof win.IntersectionObserver === 'function' ? new win.IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.target.hasAttribute('data-reveal') && entry.isIntersecting) {
        reveal(entry.target);
        if (!loops.has(entry.target)) observer.unobserve(entry.target);
      }
      if (loops.has(entry.target)) loops.get(entry.target).visible = entry.isIntersecting;
    }
    syncLoops();
  }, {threshold:0.08}) : null;

  function discover(root) {
    const nodes = [...(root.matches?.('[data-reveal],[data-motion-loop]') ? [root] : []),
      ...root.querySelectorAll('[data-reveal],[data-motion-loop]')];
    for (const node of nodes) {
      if (node.hasAttribute('data-motion-loop') && !loops.has(node)) {
        const pulses = [...node.querySelectorAll('[data-pulse]')];
        loops.set(node, {visible:false, animations:[], parts:pulses.filter(part => typeof part.animate === 'function')});
      }
      if (observer) observer.observe(node);
      else if (node.hasAttribute('data-reveal')) reveal(node);
    }
    syncLoops();
  }

  const mutation = new win.MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === 1) discover(node);
    }
    for (const [node, entry] of loops) if (!node.isConnected) {
      entry.animations.forEach(animation => animation.cancel());
      observer?.unobserve(node);
      loops.delete(node);
    }
    syncLoops();
  });
  const onHide = () => dispose(true);
  const onShow = event => {
    if (event.persisted) {
      win.removeEventListener('pageshow', onShow);
      initMotion(doc);
    }
  };
  function dispose(preserveRestore = false) {
    if (disposed) return;
    disposed = true;
    observer?.disconnect();
    mutation.disconnect();
    animations.forEach(animation => animation.cancel());
    for (const entry of loops.values()) entry.animations.forEach(animation => animation.cancel());
    loops.clear();
    doc.removeEventListener('visibilitychange', syncLoops);
    media.removeEventListener('change', syncLoops);
    doc.removeEventListener('motionstatechange', syncLoops);
    win.removeEventListener('pagehide', onHide);
    if (!preserveRestore) win.removeEventListener('pageshow', onShow);
    controllers.delete(doc);
  }
  const controller = {dispose, refresh:syncLoops};
  controllers.set(doc, controller);
  discover(doc);
  mutation.observe(doc.documentElement, {childList:true, subtree:true});
  doc.addEventListener('visibilitychange', syncLoops);
  media.addEventListener('change', syncLoops);
  doc.addEventListener('motionstatechange', syncLoops);
  win.addEventListener('pagehide', onHide);
  win.addEventListener('pageshow', onShow);
  return controller;
}

if (typeof document !== 'undefined') initMotion(document);
