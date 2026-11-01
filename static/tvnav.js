'use strict';
// Arrow-key focus movement for TV remotes (Fire TV D-pad). Browsers and app web views on TVs
// often have no built-in way to move between buttons, so this picks the nearest focusable
// element in the pressed direction. Pages turn it on with window.tvNav.enabled.
window.tvNav = {enabled: document.body.dataset.tvnav === 'always'};
(() => {
  const selector = 'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';
  const dirs = {ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0]};
  const usable = el => {
    // Skip the map surface itself and the map's attribution links.
    if (el.disabled || el.classList.contains('leaflet-container') || el.closest('.leaflet-control-attribution')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  document.addEventListener('keydown', e => {
    if (!window.tvNav.enabled || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    // The remote's select button sends Enter: tick a checkbox instead of submitting its form.
    if (e.key === 'Enter' && document.activeElement?.matches('input[type=checkbox], input[type=radio]')) {
      e.preventDefault();
      document.activeElement.click();
      return;
    }
    const d = dirs[e.key];
    if (!d) return;
    const current = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
    // Left/Right inside a text box move the cursor, as usual.
    if (current && d[0] && current.matches('input:not([type=checkbox]):not([type=radio]):not([type=submit]), textarea')) return;
    const candidates = [...document.querySelectorAll(selector)].filter(el => el !== current && usable(el));
    let best = null, bestScore = Infinity;
    if (!current) best = document.querySelector('[data-tv-start]') || candidates[0];
    else {
      const r = current.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      for (const el of candidates) {
        const s = el.getBoundingClientRect(), x = s.left + s.width / 2, y = s.top + s.height / 2;
        // Gap between facing edges in the pressed direction; must be ahead of the current element.
        const gap = d[0] ? (d[0] > 0 ? s.left - r.right : r.left - s.right) : (d[1] > 0 ? s.top - r.bottom : r.top - s.bottom);
        if (gap < -2) continue;
        // Sideways distance: zero when the two elements line up (overlap) on the other axis.
        const across = d[0] ? Math.max(0, s.top - r.bottom, r.top - s.bottom) : Math.max(0, s.left - r.right, r.left - s.right);
        const drift = Math.abs(d[0] ? y - cy : x - cx);
        const score = Math.max(gap, 0) + across * 3 + drift * 0.05;
        if (score < bestScore) { best = el; bestScore = score; }
      }
    }
    if (best) {
      e.preventDefault();
      best.focus();
      best.scrollIntoView({block: 'nearest', inline: 'nearest'});
    }
  });
})();
