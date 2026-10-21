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

/** "11:39" within a day, "Sat 08:00" further out. */
export function clockTime(date) {
  if (!date) return "the reset";
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (date - Date.now() < 24 * 3600 * 1000) return time;
  return `${date.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

/** Calls `draw(dt)` every frame with seconds since the last one; pauses while the page is hidden. */
export function animate(draw) {
  let last = performance.now();
  const frame = (now) => {
    draw(Math.min((now - last) / 1000, 0.05));
    last = now;
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/** Sizes a canvas to its element at device resolution and returns its 2D context. */
export function fitCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  const resize = () => {
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.round(canvas.clientWidth * scale);
    canvas.height = Math.round(canvas.clientHeight * scale);
  };
  resize();
  new ResizeObserver(resize).observe(canvas);
  return ctx;
}
