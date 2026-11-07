(() => {
  const viewport = document.getElementById('screenshot-viewport');
  const track = document.getElementById('screenshot-track');
  const group = document.getElementById('screenshot-group');
  const toggle = document.getElementById('screenshot-toggle');
  if (!viewport || !track || !group || !toggle) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  let hovered = false;
  let dragging = false;
  let visible = !('IntersectionObserver' in window);
  let frame = null;
  let previousTime = null;
  let position = 0;
  let lastScrollLeft = 0;
  let distance = 0;
  let resumeTimer;

  function moving() {
    return !paused && !hovered && !dragging && !reducedMotion.matches && visible &&
      !document.hidden && !viewport.contains(document.activeElement);
  }

  function tick(time) {
    frame = null;
    if (!moving() || !distance) { previousTime = null; return; }
    // Keep subpixel precision without fighting manual swipes or keyboard scroll.
    if (Math.abs(viewport.scrollLeft - lastScrollLeft) > 1) position = viewport.scrollLeft;
    if (previousTime !== null) position += Math.min(time - previousTime, 50) * 0.028;
    previousTime = time;
    position %= distance;
    viewport.scrollLeft = position;
    lastScrollLeft = viewport.scrollLeft;
    frame = requestAnimationFrame(tick);
  }

  function update() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    previousTime = null;
    position = viewport.scrollLeft;
    lastScrollLeft = viewport.scrollLeft;
    if (moving()) frame = requestAnimationFrame(tick);
  }

  function layout() {
    distance = group.getBoundingClientRect().width;
    const copies = reducedMotion.matches ? 1 : Math.max(2, Math.ceil(viewport.clientWidth / distance) + 1);
    while (track.children.length > copies) track.lastElementChild.remove();
    while (track.children.length < copies) {
      const clone = group.cloneNode(true);
      clone.removeAttribute('id');
      clone.setAttribute('aria-hidden', 'true');
      clone.querySelectorAll('a').forEach(link => link.tabIndex = -1);
      track.append(clone);
    }
    toggle.hidden = reducedMotion.matches;
    if (!reducedMotion.matches && distance) viewport.scrollLeft %= distance;
    update();
  }

  toggle.addEventListener('click', () => {
    paused = !paused;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.setAttribute('aria-label', paused ? 'Resume screenshot scrolling' : 'Pause screenshot scrolling');
    toggle.querySelector('span').textContent = paused ? 'Play' : 'Pause';
    toggle.querySelector('path').setAttribute('d', paused ? 'M4 2l10 6-10 6z' : 'M4 3h3v10H4zm5 0h3v10H9z');
    update();
  });
  viewport.addEventListener('pointerenter', event => {
    if (event.pointerType === 'mouse') { hovered = true; update(); }
  });
  viewport.addEventListener('pointerleave', () => { hovered = false; update(); });
  viewport.addEventListener('pointerdown', () => {
    clearTimeout(resumeTimer);
    dragging = true;
    update();
  });
  function finishInteraction() {
    if (!dragging) return;
    clearTimeout(resumeTimer);
    resumeTimer = setTimeout(() => { dragging = false; update(); }, 1200);
  }
  window.addEventListener('pointerup', finishInteraction);
  window.addEventListener('pointercancel', finishInteraction);
  viewport.addEventListener('focusin', update);
  viewport.addEventListener('focusout', () => queueMicrotask(update));
  document.addEventListener('visibilitychange', update);
  reducedMotion.addEventListener('change', layout);

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      update();
    }).observe(viewport);
  }
  if ('ResizeObserver' in window) new ResizeObserver(layout).observe(viewport);
  else window.addEventListener('resize', layout);
  layout();
})();
