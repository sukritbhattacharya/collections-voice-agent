/* The collections queue: what a human on the team would see after the bot
 * hangs up.
 *
 * Reads the same outcome records the CRM webhook receives. It is a view over
 * the agent's output, not a second source of truth -- if the dashboard and
 * the CRM ever disagreed, the number we report would depend on where you
 * looked.
 *
 * New calls arrive over server-sent events, so a call completed on a phone
 * appears on the laptop without a refresh.
 */

const OUTCOME_META = {
  PROMISE_TO_PAY:      { label: "Promise to pay",  color: "var(--oc-ptp)" },
  ALREADY_PAID:        { label: "Already paid",    color: "var(--oc-paid)" },
  CALLBACK_REQUEST:    { label: "Callback",        color: "var(--oc-callback)" },
  DISPUTE_OR_TRANSFER: { label: "Transfer",        color: "var(--oc-transfer)" },
};

const el = {
  tiles: document.getElementById("tiles"),
  feed: document.getElementById("feed"),
  empty: document.getElementById("empty"),
  count: document.getElementById("count"),
  live: document.getElementById("live"),
  detail: document.getElementById("detail"),
  detailBody: document.getElementById("detail-body"),
};

let calls = [];
let selected = null;

const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
};

function tile(value, label, sub) {
  const node = document.createElement("div");
  node.className = "tile";
  const v = document.createElement("div");
  v.className = "tile__value";
  v.textContent = value;
  const l = document.createElement("div");
  l.className = "tile__label";
  l.textContent = label;
  node.append(v, l);
  if (sub) {
    const s = document.createElement("div");
    s.className = "tile__sub";
    s.textContent = sub;
    node.append(s);
  }
  return node;
}

function renderTiles() {
  const n = calls.length;
  const captured = calls.filter((c) => c.captured_by === "agent").length;
  const clean = calls.filter((c) => !(c.guardrail_hits || []).length).length;

  const lat = calls
    .map((c) => c.latency?.p95_ms)
    .filter((v) => typeof v === "number" && v > 0)
    .sort((a, b) => a - b);
  const p95 = lat.length ? lat[Math.floor(lat.length * 0.5)] : null;

  const mix = Object.entries(
    calls.reduce((acc, c) => ({ ...acc, [c.outcome]: (acc[c.outcome] || 0) + 1 }), {})
  )
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${OUTCOME_META[k]?.label ?? k} ${v}`)
    .join(" · ");

  el.tiles.replaceChildren(
    tile(n, "Calls", mix || "—"),
    tile(n ? `${Math.round((captured / n) * 100)}%` : "—", "Outcome captured in call",
         n ? `${n - captured} needed the fallback` : ""),
    tile(n ? `${clean}/${n}` : "—", "No guardrail fired"),
    tile(p95 ? `${p95} ms` : "—", "Turn latency, median p95",
         p95 ? (p95 <= 1500 ? "within the 1.5s budget" : "over the 1.5s budget") : "voice calls only"),
  );
}

function renderFeed() {
  el.empty.hidden = calls.length > 0;
  el.count.textContent = calls.length ? `(${calls.length})` : "";

  el.feed.replaceChildren(
    ...calls.map((c) => {
      const meta = OUTCOME_META[c.outcome] ?? { label: c.outcome, color: "var(--ink-dim)" };
      const row = document.createElement("button");
      row.className = "row";
      row.type = "button";
      row.style.setProperty("--row-accent", meta.color);
      row.setAttribute("role", "listitem");
      row.setAttribute("aria-current", String(c.call_id === selected));

      const dot = document.createElement("span");
      dot.className = "dot";

      const main = document.createElement("span");
      main.className = "row__main";
      const title = document.createElement("span");
      title.className = "row__title";
      /* The words carry the meaning; the colour only reinforces it. */
      title.textContent = meta.label;
      if ((c.guardrail_hits || []).length) {
        const flag = document.createElement("span");
        flag.className = "flag";
        flag.textContent = `${c.guardrail_hits.length} guardrail`;
        title.append(flag);
      }
      const sub = document.createElement("span");
      sub.className = "row__sub";
      sub.textContent = summarise(c);
      main.append(title, sub);

      const metaCol = document.createElement("span");
      metaCol.className = "row__meta";
      metaCol.textContent = `${fmtTime(c.created_at)}\n${c.duration_sec ?? "–"}s · ${c.turn_count ?? 0} turns`;
      metaCol.style.whiteSpace = "pre-line";

      row.append(dot, main, metaCol);
      row.onclick = () => { selected = c.call_id; renderFeed(); renderDetail(c); };
      return row;
    })
  );
}

function summarise(c) {
  if (c.outcome === "PROMISE_TO_PAY")
    return `${c.customer_id} · ₹${c.ptp_amount_inr ?? "?"} by ${c.ptp_date ?? "?"}`;
  if (c.outcome === "ALREADY_PAID")
    return `${c.customer_id} · ${c.payment_mode ?? "?"} on ${c.paid_on ?? "?"}`;
  if (c.outcome === "CALLBACK_REQUEST")
    return `${c.customer_id} · call back ${c.callback_at ?? "?"}`;
  return `${c.customer_id} · ${c.transfer_reason ?? "?"}`;
}

function renderDetail(c) {
  const rows = [
    ["Customer", c.customer_id],
    ["Outcome", OUTCOME_META[c.outcome]?.label ?? c.outcome],
    ["Promised", c.ptp_amount_inr ? `₹${c.ptp_amount_inr} by ${c.ptp_date}` : null],
    ["Paid", c.payment_mode ? `${c.payment_mode} on ${c.paid_on}` : null],
    ["Callback", c.callback_at],
    ["Transfer reason", c.transfer_reason],
    ["Waiver asked", c.waiver_requested ? "yes" : null],
    ["Verified", c.otp_verified ? "yes" : "no"],
    ["Captured by", c.captured_by],
    ["Guardrails", (c.guardrail_hits || []).join(", ") || "none fired"],
    ["Duration", c.duration_sec != null ? `${c.duration_sec}s, ${c.turn_count} turns` : null],
    ["Latency", c.latency?.p95_ms ? `p50 ${c.latency.p50_ms} ms · p95 ${c.latency.p95_ms} ms` : null],
    ["Agent", `${c.agent_version} on ${c.model}`],
    ["Device", [c.client?.platform, c.client?.browser].filter(Boolean).join(" / ") || c.client?.surface],
  ].filter(([, v]) => v != null && v !== "");

  const dl = document.createElement("dl");
  for (const [k, v] of rows) {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = String(v);
    dl.append(dt, dd);
  }

  const turns = document.createElement("div");
  turns.className = "turns";
  for (const t of c.transcript || []) {
    const line = document.createElement("div");
    line.className = "turn";
    const who = document.createElement("b");
    who.textContent = t.role === "agent" ? "Agent" : "Customer";
    line.append(who, document.createTextNode(t.text || ""));
    turns.append(line);
  }

  el.detailBody.replaceChildren(dl, turns);
  el.detail.hidden = false;
}

function ingest(rows, { prepend } = {}) {
  for (const row of rows) {
    if (calls.some((c) => c.call_id === row.call_id)) continue;
    if (prepend) calls.unshift(row); else calls.push(row);
  }
  renderTiles();
  renderFeed();
}

async function boot() {
  try {
    const res = await fetch("/api/outcomes?limit=50");
    ingest(await res.json());
  } catch {
    /* empty state is fine */
  }

  const stream = new EventSource("/api/stream");
  stream.onopen = () => { el.live.textContent = "Live"; el.live.className = "status status--live"; };
  stream.onerror = () => { el.live.textContent = "Reconnecting"; el.live.className = "status status--connecting"; };
  stream.onmessage = (event) => {
    try {
      const row = JSON.parse(event.data);
      ingest([row], { prepend: true });
      renderDetail(row);
      selected = row.call_id;
      renderFeed();
    } catch {
      /* ignore malformed frames */
    }
  };
}

boot();
