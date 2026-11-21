/* Call client.
 *
 * Three platform constraints shape this file, and getting any of them wrong
 * makes the app look broken rather than misconfigured:
 *
 *  1. Microphone access needs a secure context. localhost counts, a LAN
 *     address does not -- so a phone needs the HTTPS tunnel, and we say so
 *     explicitly rather than letting it fail silently.
 *  2. iOS Safari will not play remote audio until a user gesture has resumed
 *     an AudioContext. That has to happen inside the tap handler itself, not
 *     after an await, or the gesture is spent. Symptom if you get it wrong:
 *     the agent hears you and you hear nothing, which reads as a backend bug.
 *  3. Android Chrome throttles background tabs and drops the connection
 *     mid-call, so we hold a wake lock while a call is live.
 */

const LK = window.LivekitClient;

const el = {
  call: document.getElementById("call"),
  status: document.getElementById("status"),
  transcript: document.getElementById("transcript"),
  error: document.getElementById("error"),
  remote: document.getElementById("remote"),
  outcomeWrap: document.getElementById("outcome-wrap"),
  outcome: document.getElementById("outcome"),
  intro: document.getElementById("intro"),
  persona: document.getElementById("persona"),
  personaHint: document.getElementById("persona-hint"),
};

// The accounts available to call. Loaded once so a demo can switch persona
// between calls from the handset, with no restart on the laptop. The late-fee
// threshold is surfaced because two fixtures sit either side of it, and which
// side a call is on changes what a correct answer sounds like.
async function loadPersonas() {
  if (!el.persona) return;
  try {
    const res = await fetch("/api/personas");
    if (!res.ok) return;
    const { accounts, default: fallback } = await res.json();
    // ?customer=MB-9023 preselects an account, so a QR code can point at one
    // persona. An unknown id is ignored in favour of the server's default.
    const asked = new URLSearchParams(location.search).get("customer");
    const wanted = accounts.some((a) => a.customer_id === asked) ? asked : fallback;
    el.persona.innerHTML = "";
    for (const a of accounts) {
      const opt = document.createElement("option");
      opt.value = a.customer_id;
      opt.textContent = `${a.name} - ${a.days_past_due} days overdue`;
      opt.dataset.lateFee = a.late_fee_applies ? "yes" : "no";
      if (a.customer_id === wanted) opt.selected = true;
      el.persona.appendChild(opt);
    }
    describePersona();
  } catch {
    /* non-fatal: the call falls back to the server's default account */
  }
}

function describePersona() {
  if (!el.persona || !el.personaHint) return;
  const opt = el.persona.selectedOptions[0];
  if (!opt) return;
  el.personaHint.textContent =
    opt.dataset.lateFee === "yes"
      ? "Balance is over the late-fee threshold, so the fee applies."
      : "Balance is under the late-fee threshold, so no late fee is due.";
}

let room = null;
let wakeLock = null;
let audioCtx = null;

function setStatus(text, kind) {
  el.status.textContent = text;
  el.status.className = `status status--${kind}`;
}

function showError(message) {
  el.error.textContent = message;
  el.error.hidden = false;
}

function clearError() {
  el.error.hidden = true;
}

function addLine(who, text) {
  const node = document.createElement("div");
  if (who === "note") {
    node.className = "line line--note";
    node.textContent = text;
  } else {
    node.className = `line line--${who}`;
    const label = document.createElement("span");
    label.className = "who";
    label.textContent = who === "agent" ? "Agent" : "You";
    node.append(label, document.createTextNode(text));
  }
  el.transcript.append(node);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

/* Secure-context check, up front and in plain words. Without it the browser
 * rejects the microphone and the page just looks dead. */
function secureContextProblem() {
  if (window.isSecureContext) return null;
  return (
    "Microphone access needs HTTPS. Opening this page over a plain " +
    "http:// address will not work on a phone — run ./scripts/tunnel.sh " +
    "and use the https://…trycloudflare.com link instead."
  );
}

/* Must run synchronously inside the tap handler: an await before this and
 * iOS treats the gesture as consumed. */
function unlockAudio() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    audioCtx = audioCtx || new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    el.remote.play().catch(() => {});
  } catch {
    /* Non-fatal: desktop browsers do not need this. */
  }
}

async function holdWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch {
    /* Denied or unsupported; the call still works, it may just drop if the
       screen sleeps. */
  }
}

function releaseWakeLock() {
  wakeLock?.release?.().catch(() => {});
  wakeLock = null;
}

/* Re-acquire after the user switches away and back: a wake lock is released
   automatically when the page is hidden. */
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && room && !wakeLock) holdWakeLock();
});

function describeDevice() {
  const ua = navigator.userAgent;
  const platform =
    /iPhone|iPad|iPod/i.test(ua) ? "ios"
    : /Android/i.test(ua) ? "android"
    : /Macintosh/i.test(ua) ? "macos"
    : /Windows/i.test(ua) ? "windows"
    : /Linux/i.test(ua) ? "linux"
    : "unknown";
  const browser =
    /CriOS/i.test(ua) ? "chrome"
    : /FxiOS|Firefox/i.test(ua) ? "firefox"
    : /EdgiOS|Edg\//i.test(ua) ? "edge"
    : /Chrome/i.test(ua) ? "chrome"
    : /Safari/i.test(ua) ? "safari"
    : "unknown";
  return { platform, browser };
}

const OUTCOME_FIELDS = [
  ["outcome", "Outcome"],
  ["ptp_date", "Promised date"],
  ["ptp_amount_inr", "Promised amount"],
  ["payment_mode", "Payment mode"],
  ["paid_on", "Paid on"],
  ["callback_at", "Callback at"],
  ["transfer_reason", "Transfer reason"],
  ["waiver_requested", "Waiver requested"],
  ["otp_verified", "Verified"],
  ["duration_sec", "Duration (s)"],
  ["turn_count", "Customer turns"],
  ["captured_by", "Captured by"],
];

function showOutcome(msg) {
  const p = msg.payload || {};
  const rows = OUTCOME_FIELDS
    .filter(([k]) => p[k] !== null && p[k] !== undefined && p[k] !== "")
    .map(([k, label]) => `${label.padEnd(17)} ${p[k]}`);

  const hits = msg.guardrail_hits || [];
  rows.push("");
  rows.push(
    hits.length
      ? `Guardrails fired    ${hits.join(", ")}`
      : "Guardrails fired    none"
  );

  const lat = msg.latency || {};
  if (lat.p50_ms != null) {
    rows.push(`Turn latency p50    ${lat.p50_ms} ms`);
    rows.push(`Turn latency p95    ${lat.p95_ms} ms`);
  }
  const st = msg.stages || {};
  if (st.tts_first_byte_ms != null) {
    rows.push("");
    rows.push("Median per stage");
    if (st.stt_final_ms != null) rows.push(`  transcript        ${st.stt_final_ms} ms`);
    if (st.llm_first_token_ms != null) rows.push(`  model reply       ${st.llm_first_token_ms} ms`);
    if (st.tts_first_byte_ms != null) rows.push(`  speech            ${st.tts_first_byte_ms} ms`);
    if (st.audio_out_ms != null) rows.push(`  audio out         ${st.audio_out_ms} ms`);
  }

  el.outcome.textContent = rows.join("\n");
  el.outcomeWrap.hidden = false;
  el.outcomeWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function startCall() {
  clearError();

  const problem = secureContextProblem();
  if (problem) {
    showError(problem);
    return;
  }

  unlockAudio();

  el.call.disabled = true;
  setStatus("Connecting", "connecting");

  try {
    const chosen = el.persona && el.persona.value;
    const res = await fetch(chosen ? `/token?customer=${encodeURIComponent(chosen)}` : "/token");
    if (!res.ok) throw new Error(`token request failed (${res.status})`);
    const { token, url } = await res.json();

    room = new LK.Room({ adaptiveStream: true, dynacast: true });

    room.on(LK.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === LK.Track.Kind.Audio) {
        track.attach(el.remote);
        el.remote.play().catch(() => {
          showError("Tap anywhere to allow audio playback.");
          document.body.addEventListener(
            "click", () => el.remote.play().catch(() => {}), { once: true }
          );
        });
      }
    });

    /* Live captions for both sides. Interim results are skipped so the pane
       does not flicker as the transcriber revises itself. */
    room.on(LK.RoomEvent.TranscriptionReceived, (segments, participant) => {
      const mine = participant?.identity === room.localParticipant.identity;
      for (const seg of segments) {
        if (seg.final && seg.text?.trim()) addLine(mine ? "you" : "agent", seg.text);
      }
    });

    /* The agent sends the structured outcome when the call closes. Showing
       it next to the transcript is the clearest way to make the point that
       the product is not the conversation, it is the record the conversation
       produces. */
    room.on(LK.RoomEvent.DataReceived, (payload, _p, _k, topic) => {
      if (topic !== "outcome") return;
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === "outcome") showOutcome(msg);
      } catch {
        /* malformed; nothing useful to show */
      }
    });

    room.on(LK.RoomEvent.Disconnected, () => endCall({ remote: true }));
    room.on(LK.RoomEvent.ConnectionStateChanged, (state) => {
      if (state === LK.ConnectionState.Reconnecting) setStatus("Reconnecting", "connecting");
      else if (state === LK.ConnectionState.Connected) setStatus("On call", "live");
    });

    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true);

    /* Announce the device. A mid-range Android and an iPhone have different
       microphones, different echo cancellation and different autoplay rules,
       so a problem that only appears on one of them should be visible in the
       data rather than remembered as an impression.

       Sent again when the agent joins. Data messages are not buffered for
       participants who arrive later, and the agent takes several seconds to be
       dispatched -- so the announcement made here, on connect, reaches an
       empty room and is lost. That is why every call so far recorded
       `platform: null`. See D-045. */
    const announceDevice = async () => {
      try {
        await room.localParticipant.publishData(
          new TextEncoder().encode(JSON.stringify({ type: "client", ...describeDevice() })),
          { reliable: true, topic: "client" }
        );
      } catch {
        /* non-fatal: the call works without it */
      }
    };
    room.on(LK.RoomEvent.ParticipantConnected, announceDevice);
    await announceDevice();
    await holdWakeLock();

    el.intro.hidden = true;
    el.outcomeWrap.hidden = true;
    el.transcript.replaceChildren();
    addLine("note", "Connected. The agent will speak first.");

    setStatus("On call", "live");
    el.call.textContent = "End call";
    el.call.className = "btn btn--end";
    el.call.disabled = false;
    el.call.onclick = () => endCall({ remote: false });
  } catch (err) {
    el.call.disabled = false;
    setStatus("Ready", "idle");
    const message = String(err?.message || err);
    showError(
      /permission|notallowed/i.test(message)
        ? "Microphone permission was denied. Allow it in your browser settings and try again."
        : `Could not start the call: ${message}`
    );
  }
}

async function endCall({ remote }) {
  releaseWakeLock();
  try {
    await room?.disconnect();
  } catch {
    /* already gone */
  }
  room = null;

  setStatus(remote ? "Call ended" : "Ended", "ended");
  addLine("note", remote ? "The agent ended the call." : "You ended the call.");

  el.call.textContent = "Start call";
  el.call.className = "btn btn--start";
  el.call.disabled = false;
  el.call.onclick = startCall;
}

el.call.onclick = startCall;
if (el.persona) el.persona.onchange = describePersona;
loadPersonas();

/* Tell the user before they tap, not after it fails. */
const upfront = secureContextProblem();
if (upfront) showError(upfront);
