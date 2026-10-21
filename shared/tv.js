// Shared helpers for TV Space pages: remote-control navigation, the native app bridge, time formatting.

/** The Android app exposes `TVSpace` to pages it shows; in a desktop browser it's missing. */
export const native = window.TVSpace ?? null;

/** Arrow keys move focus to the nearest [data-nav] element in that direction. */
export function enableDpad() {
  document.addEventListener("keydown", (event) => {
    const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
    if (!dir) return;
    event.preventDefault();
    const items = [...document.querySelectorAll("[data-nav]")];
    const current = document.activeElement;
    if (!items.includes(current)) return items[0]?.focus();

    const from = center(current);
    let best = null;
    let bestScore = Infinity;
    for (const item of items) {
      if (item === current) continue;
      const to = center(item);
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const along = dx * dir[0] + dy * dir[1];
      if (along <= 1) continue;
      const across = Math.abs(dx * dir[1]) + Math.abs(dy * dir[0]);
      const score = along + across * 2;
      if (score < bestScore) [best, bestScore] = [item, score];
    }
    best?.focus();
  });
}

function center(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

/** "4h 54m", "2d 3h", "12m". */
export function shortDuration(ms) {
  const minutes = Math.max(0, Math.round(ms / 60000));
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `${minutes}m`;
}

/** "3h 28m 05s" while under a day, so a countdown visibly ticks; "2d 3h" beyond that. */
export function countdown(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86400), h = Math.floor((total % 86400) / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const two = (n) => String(n).padStart(2, "0");
  if (d >= 1) return `${d}d ${h}h`;
  if (h >= 1) return `${h}h ${two(m)}m ${two(s)}s`;
  return `${m}m ${two(s)}s`;
}

/** "11:39" within a day, "Sat 08:00" further out. */
export function clockTime(date) {
  if (!date) return "the reset";
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (date - Date.now() < 24 * 3600 * 1000) return time;
  return `${date.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

/**
 * Calls `draw(dt)` with seconds since the last call, at most `fps` times a second (the projector's graphics
 * chip manages about 11 full-screen frames a second, so animations are capped and kept cheap).
 */
export function animate(draw, { fps = 30 } = {}) {
  const interval = 1000 / fps - 2;
  let last = performance.now();
  const frame = (now) => {
    requestAnimationFrame(frame);
    if (now - last < interval) return;
    draw(Math.min((now - last) / 1000, 0.1));
    last = now;
  };
  requestAnimationFrame(frame);
}

/**
 * Sizes a canvas to its element and returns its 2D context. Never renders wider than `maxWidth` pixels
 * (the browser scales it up to the screen): a TV with a 2x pixel ratio would otherwise draw 4x the pixels.
 * `onResize` runs after every size change, for redrawing cached layers.
 */
export function fitCanvas(canvas, { maxWidth = 960, onResize } = {}) {
  const ctx = canvas.getContext("2d");
  const resize = (notify = true) => {
    const scale = Math.min(window.devicePixelRatio || 1, maxWidth / Math.max(canvas.clientWidth, 1));
    canvas.width = Math.max(1, Math.round(canvas.clientWidth * scale));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight * scale));
    if (notify) onResize?.();
  };
  // The first size is set silently: the caller isn't ready for `onResize` until fitCanvas has returned.
  resize(false);
  new ResizeObserver(() => resize()).observe(canvas);
  return ctx;
}
