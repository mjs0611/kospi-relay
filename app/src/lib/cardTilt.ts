// Card tilt: a pressed card leans toward the finger (max ~6deg) with a soft glare, then springs back.
// Framework-agnostic: one document-level listener set, no DOM nodes added, no dependencies.
// Usage (once, at app start): installCardTilt('.home-card, .summary-card')
// Opt out inside a card with data-no-tilt on any ancestor of the touch point.
// Ported from economy-piggy src/components/Card3d.tsx (2026-10-18).

const MAX_DEG = 6;
const STYLE_ID = 'card-tilt-style';
const INTERACTIVE = 'button, a, input, select, textarea, label, summary, [role="button"], [role="link"], [role="tab"], [role="switch"], [role="checkbox"]';
const CSS = `
:where([data-card-tilt]) { position: relative; }
[data-card-tilt] { will-change: transform; user-select: none; -webkit-user-select: none; }
[data-card-tilt]::after {
  content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: 2;
  background: radial-gradient(ellipse at var(--tilt-x, 50%) var(--tilt-y, 50%), rgb(255 255 255 / 32%), rgb(222 235 255 / 12%) 35%, transparent 70%);
  opacity: var(--tilt-glare, 0); transition: opacity 120ms ease-out;
}
@media (prefers-reduced-motion: reduce) { [data-card-tilt] { transform: none !important; } [data-card-tilt]::after { display: none; } }
`;

export function installCardTilt(selector: string): () => void {
  if (typeof window === 'undefined' || !selector) return () => {};
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style'); style.id = STYLE_ID; style.textContent = CSS; document.head.appendChild(style);
  }
  const motion = (() => { try { return window.matchMedia('(prefers-reduced-motion: reduce)'); } catch { return null; } })();
  let card: HTMLElement | null = null, pointer: number | null = null, base = '', frame = 0;
  let x = 0, y = 0, vx = 0, vy = 0;

  const paint = () => { if (card) card.style.transform = `${base} perspective(720px) rotateX(${x}deg) rotateY(${y}deg)`.trim(); };
  const clear = () => {
    if (!card) return;
    card.style.transform = base;
    card.style.removeProperty('--tilt-glare'); card.style.removeProperty('--tilt-x'); card.style.removeProperty('--tilt-y');
    delete card.dataset.cardTilt; card = null;
  };
  const settle = () => {
    cancelAnimationFrame(frame); pointer = null;
    if (!card) return;
    card.style.setProperty('--tilt-glare', '0');
    let prev = performance.now(); const start = prev;
    const step = (now: number) => {
      // Small fixed steps keep the spring stable on slow WebViews.
      let left = Math.min((now - prev) / 1000, 0.032); prev = now;
      while (left > 0) {
        const dt = Math.min(left, 1 / 120);
        vx += (-600 * x - 32 * vx) * dt; vy += (-600 * y - 32 * vy) * dt; x += vx * dt; y += vy * dt; left -= dt;
      }
      if (now - start > 400 || (Math.abs(x) + Math.abs(y) < 0.03 && Math.abs(vx) + Math.abs(vy) < 0.2)) { x = y = vx = vy = 0; clear(); frame = 0; }
      else { paint(); frame = requestAnimationFrame(step); }
    };
    frame = requestAnimationFrame(step);
  };
  const follow = (e: PointerEvent) => {
    if (!card) return;
    const r = card.getBoundingClientRect(); if (!r.width || !r.height) return;
    const px = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), py = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    x = -(py * 2 - 1) * MAX_DEG; y = (px * 2 - 1) * MAX_DEG; vx = vy = 0;
    card.style.setProperty('--tilt-x', `${px * 100}%`); card.style.setProperty('--tilt-y', `${py * 100}%`); card.style.setProperty('--tilt-glare', '1');
    paint();
  };
  const down = (e: PointerEvent) => {
    if (!e.isPrimary || e.button !== 0 || motion?.matches) return;
    const target = e.target as Element | null;
    const next = target?.closest?.(selector) as HTMLElement | null;
    if (!next || target?.closest('[data-no-tilt]')) return;
    // A press that starts on a button or link inside the card must not move it: on touch devices the click
    // retargets to the card and the inner button's handler never runs (mainquest 2026-08-10).
    const control = target?.closest(INTERACTIVE);
    if (control && control !== next && next.contains(control)) return;
    cancelAnimationFrame(frame); frame = 0;
    if (card !== next) { clear(); card = next; base = next.style.transform || ''; }
    card.dataset.cardTilt = ''; pointer = e.pointerId; follow(e);
  };
  const move = (e: PointerEvent) => { if (pointer === e.pointerId) follow(e); };
  const up = (e: PointerEvent) => { if (pointer === e.pointerId) settle(); };
  const cancel = () => { if (pointer !== null) settle(); };

  const opts = { passive: true, capture: true } as const;
  document.addEventListener('pointerdown', down, opts);
  document.addEventListener('pointermove', move, opts);
  document.addEventListener('pointerup', up, opts);
  document.addEventListener('pointercancel', cancel, opts);
  window.addEventListener('scroll', cancel, opts);
  window.addEventListener('blur', cancel);
  return () => {
    cancelAnimationFrame(frame); clear();
    document.removeEventListener('pointerdown', down, opts);
    document.removeEventListener('pointermove', move, opts);
    document.removeEventListener('pointerup', up, opts);
    document.removeEventListener('pointercancel', cancel, opts);
    window.removeEventListener('scroll', cancel, opts);
    window.removeEventListener('blur', cancel);
  };
}
