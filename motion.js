(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (reduced.matches || !window.IntersectionObserver || !Element.prototype.animate) return;

  const easing = 'cubic-bezier(.22,1,.36,1)';
  const duration = 650;
  const active = new Set();
  const columns = [...document.querySelectorAll('.ny-area, .frequency-area, .result-area')];
  const rows = [...document.querySelectorAll('.comparison-table tbody tr')];
  const targets = [...columns, ...rows];
  const delays = new Map(targets.map((element, index) => [element, (index < columns.length ? index : index - columns.length) * 50]));

  function animate(element, frames, delay, time = duration) {
    const animation = element.animate(frames, {duration: time, delay, easing, fill: 'backwards'});
    const finish = () => {
      animation.cancel();
      active.delete(finish);
    };
    active.add(finish);
    animation.onfinish = finish;
  }

  function countUp(element, delay) {
    const text = element.textContent;
    const value = Number.parseInt(text, 10);
    if (!Number.isFinite(value)) return;

    // The final value stays in the accessibility tree and reserves its full width.
    const final = document.createElement('span');
    final.className = 'count-final';
    final.textContent = text;
    const visual = document.createElement('span');
    visual.className = 'count-visual';
    visual.setAttribute('aria-hidden', 'true');
    visual.textContent = '0%';
    element.replaceChildren(final, visual);

    const start = performance.now() + delay;
    let frame;
    const finish = () => {
      cancelAnimationFrame(frame);
      element.textContent = text;
      active.delete(finish);
    };
    const tick = now => {
      const progress = Math.min(1, Math.max(0, (now - start) / duration));
      visual.textContent = `${Math.round(value * (1 - (1 - progress) ** 3))}%`;
      if (progress < 1) frame = requestAnimationFrame(tick);
      else finish();
    };
    active.add(finish);
    frame = requestAnimationFrame(tick);
  }

  function reveal(element) {
    const delay = delays.get(element);
    animate(element, [
      {opacity: 0, transform: 'translateY(18px)'},
      {opacity: 1, transform: 'translateY(0)'}
    ], delay, 380);
    element.classList.remove('motion-pending');

    element.querySelectorAll('.ny-track i, .frequency-track i').forEach((bar, index) => {
      // Negative US returns grow leftwards from the same 0% baseline.
      bar.style.transformOrigin = bar.parentElement.classList.contains('ny-track') && Number.parseFloat(bar.style.left) < 50
        ? 'right center' : 'left center';
      animate(bar, [{transform: 'scaleX(0)'}, {transform: 'scaleX(1)'}], delay + index * 50);
    });
    element.querySelectorAll('.freq-pct').forEach((value, index) => countUp(value, delay + index * 50));
    element.querySelectorAll('.result-mark').forEach((mark, index) => {
      const offset = (50 - Number.parseFloat(mark.style.left)) / 100 * mark.parentElement.getBoundingClientRect().width;
      animate(mark, [
        {transform: `translateX(calc(-50% + ${offset}px))`},
        {transform: 'translateX(-50%)'}
      ], delay + index * 50);
    });
  }

  // Static HTML is visible by default; only a successfully installed observer hides it.
  const observer = new IntersectionObserver(entries => {
    try {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        reveal(entry.target);
      });
    } catch (_) {
      finishAll();
    }
  }, {threshold: 0.12});

  function finishAll() {
    observer.disconnect();
    targets.forEach(element => element.classList.remove('motion-pending'));
    [...active].forEach(finish => finish());
  }

  try {
    targets.forEach(element => {
      observer.observe(element);
      element.classList.add('motion-pending');
    });
  } catch (_) {
    finishAll();
  }

  // Cancel immediately on a preference change or before restoring a page from bfcache.
  reduced.addEventListener('change', event => { if (event.matches) finishAll(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) finishAll(); });
  window.addEventListener('pagehide', finishAll);
  window.addEventListener('beforeprint', finishAll);
  document.addEventListener('focusin', event => {
    const target = event.target.closest('.motion-pending');
    if (target) {
      observer.unobserve(target);
      target.classList.remove('motion-pending');
    }
  });
})();
