// Your Claude limits, as published to a secret gist by usage-bridge/bridge.mjs on the Mac.
//
// The gist API is fresh but allows 60 requests an hour per network. Its responses carry an ETag and
// max-age=60, so polling once a minute lets the browser revalidate, and "nothing changed" answers (304)
// don't count. If the network is rate-limited anyway, fall back to the raw file, which has no limit but
// can lag up to 5 minutes behind.

const OWNER = "antonmiller000";
const GIST = "d53693b4791df95a59f51756c53633c9";

/** Made-up numbers for previewing a mood: add ?demo=plenty (or okay, low, empty) to the page URL. */
function demo(mood) {
  const used = { plenty: [18, 22, 4], okay: [61, 48, 10], low: [88, 71, 30], empty: [100, 83, 41] }[mood];
  const at = (hours) => new Date(Date.now() + hours * 3600e3).toISOString();
  return {
    updatedAt: new Date().toISOString(),
    limits: [
      { kind: "session", label: "5-hour limit", percent: used[0], resetsAt: at(2.3), severity: used[0] >= 90 ? "critical" : used[0] >= 75 ? "warning" : "normal" },
      { kind: "weekly_all", label: "Weekly · all models", percent: used[1], resetsAt: at(97), severity: "normal" },
      { kind: "weekly_scoped", label: "Weekly · Fable", percent: used[2], resetsAt: at(97), severity: "normal" },
    ],
  };
}

/** @returns {Promise<{limits: Limit[], error: string|null, updatedAt: Date|null}>} */
export async function fetchUsage() {
  let data;
  const demoMood = new URLSearchParams(location.search).get("demo");
  // no-cache: GitHub says the answer is good for 60 s, but we want the latest. The browser still sends the ETag,
  // and an unchanged answer (304) is quick and doesn't count against the rate limit.
  const api = demoMood ? null : await fetch(`https://api.github.com/gists/${GIST}`, { cache: "no-cache" });
  if (demoMood) {
    data = demo(demoMood);
  } else if (api.ok) {
    data = JSON.parse((await api.json()).files["usage.json"].content);
  } else if (api.status === 403 || api.status === 429) {
    data = await (await fetch(`https://gist.githubusercontent.com/${OWNER}/${GIST}/raw/usage.json`, { cache: "no-cache" })).json();
  } else {
    throw new Error(`GitHub answered ${api.status}`);
  }
  return {
    error: data.error ?? null,
    updatedAt: data.updatedAt ? new Date(data.updatedAt) : null,
    limits: (data.limits ?? []).map((l) => ({
      kind: l.kind ?? "",
      label: l.label,
      used: Math.max(0, Math.min(100, l.percent)),
      left: 100 - Math.max(0, Math.min(100, l.percent)),
      resetsAt: l.resetsAt ? new Date(l.resetsAt) : null,
      severity: l.severity ?? "normal",
    })),
  };
}

/** The limit closest to running out decides the mood. */
export function tightest(usage) {
  return usage?.limits?.reduce((a, b) => (b.used > a.used ? b : a), usage.limits[0]) ?? null;
}

export function session(usage) {
  return usage?.limits?.find((l) => l.kind === "session") ?? tightest(usage);
}

export function weekly(usage) {
  return usage?.limits?.find((l) => l.kind === "weekly_all") ?? null;
}

export function moodFor(usage) {
  const t = tightest(usage);
  if (!t) return "unknown";
  if (t.used >= 100) return "empty";
  if (t.used >= 80 || t.severity === "critical") return "low";
  if (t.used >= 50 || t.severity === "warning") return "okay";
  return "plenty";
}

export function severityColor(limit) {
  if (limit.severity === "critical" || limit.used >= 90) return "var(--critical)";
  if (limit.severity === "warning" || limit.used >= 70) return "var(--warning)";
  return "var(--good)";
}
