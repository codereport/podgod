(() => {
  document.querySelectorAll('[data-carousel]').forEach(initializeCarousel);
})();

function initializeCarousel(root) {
  const viewport = root.querySelector('[data-carousel-viewport]');
  const track = root.querySelector('[data-carousel-track]');
  const group = root.querySelector('[data-carousel-group]');
  const toggle = root.querySelector('[data-carousel-toggle]');
  if (!viewport || !track || !group || !toggle) return;

  const speed = 0.028 * Number(root.dataset.carouselSpeedMultiplier || 1);
  const name = root.dataset.carouselName;
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
  let ready = false;

  function moving() {
    return ready && !paused && !hovered && !dragging && !reducedMotion.matches && visible &&
      !document.hidden && !viewport.contains(document.activeElement);
  }

  function tick(time) {
    frame = null;
    if (!moving() || !distance) { previousTime = null; return; }
    // Keep subpixel precision without fighting manual swipes or keyboard scroll.
    if (Math.abs(viewport.scrollLeft - lastScrollLeft) > 1) position = viewport.scrollLeft;
    if (previousTime !== null) position += Math.min(time - previousTime, 50) * speed;
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

  function layout(rebuild = false) {
    if (rebuild) {
      while (track.children.length > 1) track.lastElementChild.remove();
      viewport.scrollLeft = 0;
    }
    ready = group.getAttribute('aria-busy') !== 'true' && group.children.length > 0 && !group.querySelector('.load-error');
    distance = group.getBoundingClientRect().width;
    const copies = !ready || reducedMotion.matches || !distance ? 1 : Math.max(2, Math.ceil(viewport.clientWidth / distance) + 1);
    while (track.children.length > copies) track.lastElementChild.remove();
    while (track.children.length < copies) {
      const clone = group.cloneNode(true);
      clone.removeAttribute('id');
      clone.removeAttribute('data-carousel-group');
      clone.removeAttribute('aria-live');
      clone.removeAttribute('aria-busy');
      clone.setAttribute('aria-hidden', 'true');
      clone.querySelectorAll('a').forEach(link => link.tabIndex = -1);
      if (root.dataset.carouselImageFallback) {
        clone.querySelectorAll('img').forEach(image => image.addEventListener('error', () => {
          image.src = root.dataset.carouselImageFallback;
        }, { once: true }));
      }
      track.append(clone);
    }
    toggle.hidden = !ready || reducedMotion.matches;
    if (!reducedMotion.matches && distance) viewport.scrollLeft %= distance;
    update();
  }

  toggle.addEventListener('click', () => {
    paused = !paused;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.setAttribute('aria-label', `${paused ? 'Resume' : 'Pause'} ${name} scrolling`);
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
  reducedMotion.addEventListener('change', () => layout());

  new MutationObserver(() => layout(true)).observe(group, { childList: true, attributes: true, attributeFilter: ['aria-busy'] });

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      update();
    }).observe(viewport);
  }
  if ('ResizeObserver' in window) new ResizeObserver(() => layout()).observe(viewport);
  else window.addEventListener('resize', () => layout());
  layout();
}
