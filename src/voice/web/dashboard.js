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
  scrim: document.getElementById("scrim"),
  sheetSub: document.getElementById("sheet-sub"),
  sheetClose: document.getElementById("sheet-close"),
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
      row.onclick = () => openSheet(c);
      row.tabIndex = 0;
      row.onkeydown = (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openSheet(c); }
      };
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
    line.className = `turn turn--${t.role === "agent" ? "agent" : "customer"}`;

    const who = document.createElement("b");
    who.className = "turn__who";
    who.textContent = t.role === "agent" ? "Agent" : "Customer";

    const said = document.createElement("span");
    said.className = "turn__text";
    said.textContent = t.text || "";
    line.append(who, said);

    // What speech recognition returned, where it had to be repaired. The
    // record keeps the raw text; this is where you can see it.
    if (t.repaired_to) {
      const raw = document.createElement("span");
      raw.className = "turn__tag";
      raw.textContent = `heard "${t.text}" - read as "${t.repaired_to}"`;
      line.append(raw);
    }

    // The sentence a guardrail replaced, on the turn it happened.
    if (t.blocked) {
      const tag = document.createElement("span");
      tag.className = "turn__tag turn__tag--blocked";
      tag.textContent = `guardrail: ${t.blocked.join(", ")}`;
      line.append(tag);
    }

    turns.append(line);
  }

  el.detailBody.replaceChildren(dl, heading("Conversation"), turns);
}

function heading(text) {
  const h = document.createElement("h3");
  h.className = "sheet__h3";
  h.textContent = text;
  return h;
}

/* --- the sheet ------------------------------------------------------------
 *
 * Opens over the page. Closing restores focus to the row that opened it, so
 * keyboard users are not dropped at the top of the list after reading a call.
 */
let lastFocused = null;

function openSheet(c) {
  selected = c.call_id;
  renderDetail(c);
  el.sheetSub.textContent =
    `${c.customer_id} · ${fmtTime(c.created_at)} · ${c.turn_count ?? 0} turns`;
  lastFocused = document.activeElement;
  el.detail.hidden = false;
  el.scrim.hidden = false;
  // Next frame, so the transition has a starting state to animate from.
  requestAnimationFrame(() => {
    el.detail.classList.add("sheet--open");
    el.scrim.classList.add("scrim--open");
  });
  el.sheetClose.focus();
  renderFeed();
}

function closeSheet() {
  el.detail.classList.remove("sheet--open");
  el.scrim.classList.remove("scrim--open");
  const finish = () => {
    el.detail.hidden = true;
    el.scrim.hidden = true;
  };
  // Match the CSS transition, but do not depend on the event firing.
  setTimeout(finish, 220);
  if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  selected = null;
  renderFeed();
}

const sheetIsOpen = () => !el.detail.hidden;

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
      // Update the sheet only if it is already open on this call. Opening it
      // unbidden would cover the queue mid-demo, and replacing what someone
      // is reading with a different call is worse than making them click.
      if (sheetIsOpen() && selected === row.call_id) openSheet(row);
      renderFeed();
    } catch {
      /* ignore malformed frames */
    }
  };
}

el.sheetClose.onclick = closeSheet;
el.scrim.onclick = closeSheet;
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && sheetIsOpen()) closeSheet();
});

boot();
