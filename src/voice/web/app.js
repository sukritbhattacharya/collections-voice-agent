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
};

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
    const res = await fetch("/token");
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

    room.on(LK.RoomEvent.Disconnected, () => endCall({ remote: true }));
    room.on(LK.RoomEvent.ConnectionStateChanged, (state) => {
      if (state === LK.ConnectionState.Reconnecting) setStatus("Reconnecting", "connecting");
      else if (state === LK.ConnectionState.Connected) setStatus("On call", "live");
    });

    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true);
    await holdWakeLock();

    el.intro.hidden = true;
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

/* Tell the user before they tap, not after it fails. */
const upfront = secureContextProblem();
if (upfront) showError(upfront);
