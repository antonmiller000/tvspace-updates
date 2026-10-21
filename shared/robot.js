// The Claude robot: an orange pixel creature that acts out how much of your Claude limits is left.
// Drawn in "units" (u) from the point between its feet: the body is 12u × 8u, standing on legs 2u high.

const ORANGE = "#d97757";
const ORANGE_LIGHT = "#ec9a7c";
const ORANGE_DARK = "#b65f42";
const INK = "#2b1a12";
const PI = Math.PI;

/** Seconds each behaviour lasts before the robot picks another. */
const DURATION = {
  idle: 7, wave: 5, dance: 10, jump: 7, walk: 12, typing: 10, think: 8, juggle: 10, sleep: 16, tired: 9,
  celebrate: 6, spin: 4, look: 6, love: 6, coffee: 9, read: 10, stretch: 6,
};

const MOVES = {
  plenty: ["dance", "jump", "juggle", "wave", "walk", "spin", "love", "typing", "coffee", "idle"],
  okay: ["typing", "think", "walk", "idle", "wave", "look", "juggle", "read", "coffee"],
  low: ["tired", "typing", "think", "idle", "look", "stretch", "coffee"],
  empty: ["sleep", "sleep", "sleep", "tired", "stretch"],
  unknown: ["look", "think", "idle", "wave", "read"],
};

// Not "celebrate": that one is reserved for a real reset, because its speech bubble says "Fresh limits!".
const TRICKS = ["dance", "jump", "spin", "juggle", "love", "wave"];

const BLEND = 0.35; // seconds to ease from the previous pose into a new behaviour

const random = (list) => list[Math.floor(Math.random() * list.length)];
const smooth = (x) => x * x * (3 - 2 * x);
const lerp = (a, b, k) => a + (b - a) * k;

export class Robot {
  constructor({ compact = false } = {}) {
    this.compact = compact;
    this.mood = "unknown";
    this.behavior = "idle";
    this.time = 0; // seconds into the current behaviour
    this.clock = 0; // seconds since creation
    this.homeFrom = 0; // where the last behaviour left the robot, in u; it strolls back to the middle
    this.pose = neutralPose();
    this.from = neutralPose();
    this.confetti = [];
    this.onBehavior = null;
    this.start("wave");
  }

  setMood(mood) {
    if (mood === this.mood) return;
    const wasDown = this.mood === "low" || this.mood === "empty";
    this.mood = mood;
    // A fresh window after running low deserves a party.
    this.start(wasDown && mood === "plenty" ? "celebrate" : this.pick());
  }

  /** Something fun on demand (the OK button). */
  trick() {
    this.start(random(TRICKS.filter((t) => t !== this.behavior)));
  }

  pick() {
    const moves = MOVES[this.compact ? "plenty" : this.mood].filter((m) => !(this.compact && m === "walk"));
    return random(moves.filter((m) => m !== this.behavior));
  }

  start(behavior) {
    this.from = { ...this.pose };
    this.homeFrom = this.pose.x;
    this.behavior = behavior;
    this.time = 0;
    this.confetti = behavior === "celebrate" ? Array.from({ length: 160 }, makeConfetto) : [];
    this.onBehavior?.(behavior);
  }

  /** Advances the animation and works out this frame's pose. */
  step(dt, widthInUnits) {
    this.clock += dt;
    this.time += dt;
    if (this.time >= DURATION[this.behavior]) this.start(this.pick());

    const target = this.target(widthInUnits);
    const k = this.time < BLEND ? smooth(this.time / BLEND) : 1;
    for (const key of ["x", "y", "tilt", "squash", "flip", "leftArm", "rightArm", "wave", "eyeX", "eyeY", "eyeOpen"]) {
      this.pose[key] = lerp(this.from[key], target[key], k);
    }
    for (const key of ["eyes", "legs", "blush", "mouth", "prop"]) this.pose[key] = target[key];
  }

  target(widthInUnits) {
    const t = this.time;
    const c = this.clock;
    const p = t / DURATION[this.behavior];
    const s = neutralPose();
    s.x = this.homeFrom * (1 - smooth(Math.min(t / 1.5, 1)));
    s.y = Math.sin(c * 2.2) * 0.15;
    s.squash = Math.sin(c * 2.2) * 0.015;
    if (c % 3.6 < 0.12) s.eyes = "closed";

    switch (this.behavior) {
      case "idle":
        s.eyeX = Math.sin(c * 0.7) > 0.6 ? 0.4 : 0;
        break;
      case "wave":
        s.rightArm = 1; s.wave = Math.sin(t * 12) * 0.6; s.tilt = Math.sin(t * 3) * 3; s.eyes = "happy";
        break;
      case "dance": {
        const beat = Math.abs(Math.sin(t * PI * 2));
        const up = Math.sin(t * PI * 2) > 0;
        s.y = -beat * 1.2; s.squash = (1 - beat) * 0.1 - 0.03; s.tilt = Math.sin(t * PI) * 10;
        s.leftArm = up ? 1 : 0.2; s.rightArm = up ? 0.2 : 1; s.legs = up ? 1 : 2; s.eyes = "happy"; s.prop = "notes";
        break;
      }
      case "jump":
        jump(s, t, 1.4, 4); s.prop = "sparkles";
        break;
      case "celebrate":
        jump(s, t, 0.8, 2.5); s.leftArm = 1; s.rightArm = 1; s.eyes = "happy"; s.prop = "confetti";
        break;
      case "walk": {
        // Stay fully on screen: the robot is 16u wide with its arms.
        const range = Math.max(0, Math.min(widthInUnits / 2 - 9, 16));
        const phase = p * 2 * PI;
        const dir = Math.sign(Math.cos(phase));
        s.x = range * Math.sin(phase); s.eyeX = dir * 0.5; s.tilt = dir * 3;
        s.legs = Math.sin(t * 12) > 0 ? 1 : 2; s.y = -Math.abs(Math.sin(t * 12)) * 0.2;
        break;
      }
      case "typing":
        s.prop = "laptop"; s.eyeY = 0.4;
        s.leftArm = Math.sin(t * 23) > 0 ? 0.35 : 0.2;
        s.rightArm = Math.sin(t * 19 + 1) > 0 ? 0.35 : 0.2;
        if (t % 4 > 3.2) { s.eyeY = 0; s.eyeX = 0.4; }
        break;
      case "think":
        s.tilt = 7 * Math.min(t * 2, 1); s.eyeX = 0.5; s.eyeY = -0.5; s.rightArm = 0.45; s.prop = "thought";
        break;
      case "juggle":
        s.leftArm = Math.sin(t * 7) > 0 ? 0.7 : 0.25; s.rightArm = Math.sin(t * 7) > 0 ? 0.25 : 0.7;
        s.eyeY = -0.5; s.eyeX = Math.cos(t * 2.4) * 0.4; s.prop = "juggle";
        break;
      case "sleep":
        s.eyes = "closed"; s.squash = Math.sin(c * 1.2) * 0.04; s.y = 0.3; s.tilt = 4; s.prop = "zzz";
        break;
      case "tired":
        s.eyeOpen = 0.45; s.y = 0.4; s.tilt = Math.sin(t * 0.8) * 4; s.squash = 0.05; s.prop = "sweat";
        if (t % 4 > 3.4) s.eyes = "closed";
        break;
      case "spin":
        s.flip = Math.cos(p * 4 * PI); s.y = -Math.sin(p * PI) * 2; s.leftArm = 0.6; s.rightArm = 0.6; s.prop = "sparkles";
        break;
      case "look": {
        const step = Math.floor(t / 1.5) % 4;
        s.eyeX = [-0.5, 0.5, 0, 0.5][step]; s.eyeY = [0, 0, -0.5, 0.3][step]; s.tilt = s.eyeX * 6;
        break;
      }
      case "love":
        s.eyes = "happy"; s.blush = true; s.tilt = Math.sin(t * 2) * 6; s.leftArm = 0.3; s.rightArm = 0.3; s.prop = "hearts";
        break;
      case "coffee": {
        const sip = t % 3.5 > 2.4;
        s.rightArm = sip ? 0.9 : 0.45; s.prop = "coffee";
        if (sip) s.eyes = "happy";
        break;
      }
      case "read":
        s.leftArm = 0.3; s.rightArm = 0.3; s.eyeY = 0.5; s.eyeX = ((t % 2.5) / 2.5) * 1 - 0.5; s.prop = "book";
        break;
      case "stretch": {
        const k = Math.sin(Math.min(t / 2, 1) * PI);
        s.leftArm = k; s.rightArm = k; s.squash = -0.08 * k; s.eyes = k > 0.5 ? "closed" : s.eyes; s.mouth = k > 0.5;
        break;
      }
    }
    return s;
  }

  /** Draws the robot standing at (cx, ground) at unit size u. */
  draw(ctx, cx, ground, u, dt) {
    const s = this.pose;
    const x = cx + s.x * u;
    const y = ground + s.y * u;

    // Shadow shrinks as the robot leaves the ground.
    const lift = Math.max(0, -s.y);
    ctx.fillStyle = "rgba(0, 0, 0, 0.35)";
    ctx.beginPath();
    ctx.ellipse(x, ground + 0.1 * u, 6.5 * u * (1 - lift / 9), 0.6 * u, 0, 0, 2 * PI);
    ctx.fill();

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate((s.tilt * PI) / 180);
    ctx.scale(s.flip * (1 + s.squash * 0.6), 1 - s.squash);
    this.drawBody(ctx, u);
    ctx.restore();

    const headTop = y - 10 * u * (1 - s.squash);
    this.drawProp(ctx, x, y, headTop, u, dt);
    return { x, headTop };
  }

  drawBody(ctx, u) {
    const s = this.pose;
    const box = (l, t, r, b, color) => {
      ctx.fillStyle = color;
      ctx.fillRect(l * u, t * u, (r - l) * u, (b - t) * u);
    };

    // Legs: alternate pairs lift for walking and dancing.
    [-4.5, -2.5, 1.5, 3.5].forEach((lx, i) => {
      const lifted = (s.legs === 1 && i % 2 === 0) || (s.legs === 2 && i % 2 === 1);
      const lift = lifted ? 0.6 : 0;
      box(lx, -2.2 - lift, lx + 1, -lift, ORANGE_DARK);
    });

    box(-6, -10, 6, -2, ORANGE);
    box(-6, -10, 6, -9.4, ORANGE_LIGHT);
    box(-6, -2.6, 6, -2, ORANGE_DARK);

    this.drawArm(ctx, u, -1, s.leftArm, 0, box);
    if (s.prop === "laptop") drawLaptop(ctx, u, box);
    if (s.prop === "book") drawBook(ctx, u, box, this.time);
    this.drawArm(ctx, u, 1, s.rightArm, s.wave, box);
    if (s.prop === "coffee") drawMug(ctx, u, box, s.rightArm, this.clock);

    if (s.flip < 0) return; // seen from behind: no face

    for (const ex0 of [-3, 3]) {
      const ex = ex0 + s.eyeX;
      const ey = -7 + s.eyeY;
      if (s.eyes === "open") {
        box(ex - 0.5, ey - s.eyeOpen, ex + 0.5, ey + s.eyeOpen, INK);
        box(ex - 0.5, ey - s.eyeOpen, ex - 0.1, ey - s.eyeOpen + 0.4, "rgba(255,255,255,0.55)");
      } else if (s.eyes === "closed") {
        box(ex - 0.6, ey + 0.2, ex + 0.6, ey + 0.55, INK);
      } else {
        ctx.strokeStyle = INK;
        ctx.lineWidth = 0.35 * u;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        ctx.moveTo((ex - 0.6) * u, (ey + 0.5) * u);
        ctx.lineTo(ex * u, (ey - 0.4) * u);
        ctx.lineTo((ex + 0.6) * u, (ey + 0.5) * u);
        ctx.stroke();
      }
    }
    if (s.blush) {
      box(-4.6, -5.6, -3.2, -5, "rgba(255, 143, 163, 0.6)");
      box(3.2, -5.6, 4.6, -5, "rgba(255, 143, 163, 0.6)");
    }
    if (s.mouth) box(-0.6, -5.4, 0.6, -4.2, INK);
  }

  /** A 2u block on the side of the body; raising lifts it on a 1u-wide stalk. */
  drawArm(ctx, u, side, raise, sway, box) {
    const l = Math.min(6 * side, 8 * side) + sway;
    const top = -6 - raise * 5.5;
    if (raise > 0.05) {
      const stalk = side < 0 ? -7 : 6;
      box(stalk + sway * 0.5, top + 1, stalk + 1 + sway * 0.5, -4.5, ORANGE);
    }
    box(l, top, l + 2, top + 2, ORANGE);
    box(l, top, l + 2, top + 0.45, ORANGE_LIGHT);
  }

  drawProp(ctx, x, y, headTop, u, dt) {
    const t = this.time;
    const rising = (count, speed, fn) => {
      for (let i = 0; i < count; i++) {
        const phase = (t * speed + i / count) % 1;
        ctx.globalAlpha = Math.sin(phase * PI);
        fn(phase, i);
      }
      ctx.globalAlpha = 1;
    };
    const glyph = (text, gx, gy, size, color) => {
      ctx.font = `600 ${size}px Inter, Roboto, sans-serif`;
      ctx.fillStyle = color;
      ctx.textAlign = "center";
      ctx.fillText(text, gx, gy);
    };

    switch (this.pose.prop) {
      case "zzz":
        rising(3, 0.45, (q) => glyph("Z", x + 5 * u + q * 4 * u, headTop - q * 6 * u, (1.3 + q * 1.6) * u, "#b8c4ff"));
        break;
      case "notes":
        rising(4, 0.6, (q, i) => {
          const side = i % 2 ? 1 : -1;
          glyph(side < 0 ? "♪" : "♫", x + side * (8 + q * 3) * u, headTop + 2 * u - q * 7 * u, 2.2 * u, "#ffd27a");
        });
        break;
      case "hearts":
        rising(4, 0.5, (q, i) => drawHeart(ctx, x + Math.sin(q * 6 + i * 2) * 5 * u, headTop - q * 7 * u, (0.8 + q) * u, "#ff6f91"));
        break;
      case "laptop":
        rising(3, 0.5, (q, i) => glyph(["</>", "{ }", "✓"][i], x - 6 * u + q * 8 * u + i * u, headTop - q * 5 * u, 1.3 * u, "#9fe6b8"));
        break;
      case "sweat": {
        const q = (t % 1.6) / 1.6;
        ctx.globalAlpha = Math.sin(q * PI);
        drawDrop(ctx, x + 6.6 * u, headTop + (1 + q * 3) * u, 0.6 * u, "#8fd3ff");
        ctx.globalAlpha = 1;
        break;
      }
      case "thought": {
        ctx.fillStyle = "rgba(242, 244, 255, 0.92)";
        const bubble = (bx, by, r) => { ctx.beginPath(); ctx.arc(bx, by, r, 0, 2 * PI); ctx.fill(); };
        if (t > 0.3) bubble(x + 6.5 * u, headTop - 0.5 * u, 0.4 * u);
        if (t > 0.6) bubble(x + 8 * u, headTop - 2 * u, 0.7 * u);
        if (t > 0.9) {
          ctx.beginPath();
          ctx.ellipse(x + 11 * u, headTop - 5.2 * u, 3.2 * u, 2.3 * u, 0, 0, 2 * PI);
          ctx.fill();
          glyph(t % 2 < 1 ? "?" : "…", x + 11 * u, headTop - 4.3 * u, 2.6 * u, INK);
        }
        break;
      }
      case "juggle":
        for (let i = 0; i < 3; i++) {
          const a = t * 2.4 + (i * 2 * PI) / 3;
          drawSpark(ctx, x + Math.cos(a) * 4 * u, headTop - 3.5 * u - Math.abs(Math.sin(a)) * 3.5 * u, u, ORANGE);
        }
        break;
      case "sparkles":
        for (let i = 0; i < 6; i++) {
          const a = i * 1.05 + this.clock * 0.6;
          const r = (9 + (i % 2) * 2) * u;
          drawSparkle(ctx, x + Math.cos(a) * r, headTop + 3 * u + Math.sin(a) * r * 0.6, 0.7 * u * Math.abs(Math.sin(this.clock * 3 + i)), "#ffe9a8");
        }
        break;
      case "coffee":
        rising(3, 0.6, (q, i) => {
          const mx = x + (7 + Math.sin(q * 8 + i) * 0.4) * u;
          const top = y + (-6 - this.pose.rightArm * 5.5 - 1) * u;
          ctx.strokeStyle = "rgba(255,255,255,0.7)";
          ctx.lineWidth = 0.18 * u;
          ctx.beginPath();
          ctx.moveTo(mx + (i - 1) * 0.5 * u, top - q * 3 * u);
          ctx.quadraticCurveTo(mx + (i - 0.5) * u, top - (q * 3 + 0.6) * u, mx + (i - 1) * 0.5 * u, top - (q * 3 + 1.2) * u);
          ctx.stroke();
        });
        break;
      case "confetti":
        for (const c of this.confetti) {
          c.vy += 9 * dt; c.x += c.vx * dt; c.y += c.vy * dt; c.spin += c.vSpin * dt;
          ctx.save();
          ctx.translate(x + c.x * u, headTop + c.y * u);
          ctx.rotate(c.spin);
          ctx.fillStyle = c.color;
          ctx.fillRect(-0.35 * u, -0.18 * u, 0.7 * u, 0.36 * u);
          ctx.restore();
        }
        break;
    }
  }
}

function neutralPose() {
  return {
    x: 0, y: 0, tilt: 0, squash: 0, flip: 1, leftArm: 0, rightArm: 0, wave: 0, eyeX: 0, eyeY: 0, eyeOpen: 1,
    eyes: "open", legs: 0, blush: false, mouth: false, prop: null,
  };
}

function jump(s, t, period, height) {
  const p = (t % period) / period;
  if (p < 0.15) {
    s.squash = 0.15 * Math.sin((p / 0.15) * PI);
  } else if (p < 0.85) {
    const q = (p - 0.15) / 0.7;
    s.y = -Math.sin(q * PI) * height; s.squash = -0.06; s.leftArm = 1; s.rightArm = 1; s.eyes = "happy";
  } else {
    s.squash = 0.12 * Math.sin(((p - 0.85) / 0.15) * PI);
  }
}

function makeConfetto() {
  return {
    x: Math.random() * 60 - 30, y: -Math.random() * 20 - 4,
    vx: Math.random() * 4 - 2, vy: Math.random() * 3,
    spin: Math.random() * 6, vSpin: Math.random() * 8 - 4,
    color: random([ORANGE, "#7c9cff", "#ffd27a", "#9fe6b8", "#ff6f91"]),
  };
}

function drawLaptop(ctx, u, box) {
  box(-4.5, -6.5, 4.5, -1.2, "#3a3f55");
  box(-4.5, -6.5, 4.5, -6.1, "#4b5170");
  box(-5.5, -1.2, 5.5, -0.6, "#565c78");
  drawSpark(ctx, 0, -3.85 * u, 1.1 * u, ORANGE);
}

function drawBook(ctx, u, box, t) {
  box(-5, -6, 5, -1.5, "#3d5a9e");
  box(-4.6, -5.6, -0.15, -1.9, "#f4ecd8");
  box(0.15, -5.6, 4.6, -1.9, "#efe5cc");
  for (let i = 0; i < 4; i++) {
    box(-4, -5 + i * 0.8, -0.8, -4.8 + i * 0.8, "#c9bea3");
    box(0.8, -5 + i * 0.8, 4, -4.8 + i * 0.8, "#c9bea3");
  }
  // A page turns every few seconds.
  const flip = (t % 3) / 3;
  if (flip > 0.8) {
    const w = Math.cos(((flip - 0.8) / 0.2) * PI) * 4.4;
    box(Math.min(0, w), -5.6, Math.max(0, w), -1.9, "#fff8e6");
  }
}

function drawMug(ctx, u, box, raise, clock) {
  const top = -6 - raise * 5.5 - 1;
  box(6.4, top, 8.6, top + 2.4, "#f2f4ff");
  box(6.4, top + 0.9, 8.6, top + 1.3, ORANGE);
  ctx.strokeStyle = "#f2f4ff";
  ctx.lineWidth = 0.3 * u;
  ctx.beginPath();
  ctx.arc(8.9 * u, (top + 1.2) * u, 0.55 * u, -PI / 2, PI / 2);
  ctx.stroke();
}

/** Claude's spark: eight rounded rays of alternating length. */
function drawSpark(ctx, x, y, r, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = r * 0.28;
  ctx.lineCap = "round";
  for (let i = 0; i < 8; i++) {
    const a = (i * PI) / 4 + 0.2;
    const len = i % 2 === 0 ? r : r * 0.7;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.cos(a) * len, y + Math.sin(a) * len);
    ctx.stroke();
  }
}

function drawSparkle(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y - r * 2);
  ctx.lineTo(x + r * 0.4, y - r * 0.4);
  ctx.lineTo(x + r * 2, y);
  ctx.lineTo(x + r * 0.4, y + r * 0.4);
  ctx.lineTo(x, y + r * 2);
  ctx.lineTo(x - r * 0.4, y + r * 0.4);
  ctx.lineTo(x - r * 2, y);
  ctx.lineTo(x - r * 0.4, y - r * 0.4);
  ctx.closePath();
  ctx.fill();
}

function drawHeart(ctx, x, y, s, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y + s * 0.9);
  ctx.bezierCurveTo(x - s * 1.6, y - s * 0.2, x - s * 0.8, y - s * 1.3, x, y - s * 0.4);
  ctx.bezierCurveTo(x + s * 0.8, y - s * 1.3, x + s * 1.6, y - s * 0.2, x, y + s * 0.9);
  ctx.fill();
}

function drawDrop(ctx, x, y, s, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y - s * 1.4);
  ctx.quadraticCurveTo(x + s, y, x, y + s);
  ctx.quadraticCurveTo(x - s, y, x, y - s * 1.4);
  ctx.fill();
}
