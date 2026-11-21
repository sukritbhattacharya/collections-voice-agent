# Decision log

Every material decision on this project, written down as it was made rather than
reconstructed afterwards. Each entry records what was decided, what else was on
the table, what the choice costs, and what would change the answer.

The `AI involvement` line tracks where an AI assistant proposed something and
whether it was accepted or overridden. That distinction is hard to recall
honestly after the fact, so it is captured at the moment of the decision.

**Status values:** `Accepted` · `Deferred` · `Rejected` · `Superseded by D-NNN`

---

## D-001 — Repository is a product, not an exercise
**Date:** 2026-11-18 · **Stage:** Scaffold · **Status:** Accepted

**Decision:** The repo lives in its own directory, is named
`collections-voice-agent`, and its README, code and comments describe a working
collections voice agent. No reference anywhere to an evaluation, a brief, or the
circumstances that produced it.

**Why:** A reader should be able to clone it, point it at a different issuer, and
run it. That framing also forces better engineering: the issuer name, interest
rate, late fee and threshold become configuration rather than literals scattered
through a prompt.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Flat repo in the parent folder | One less directory | Parent path names the evaluation; leaks into any clone or zip | Rejected |
| README explaining the exercise | Transparent about origin | Reads as homework, not software | Rejected |

**Trade-off accepted:** Slightly more config plumbing on day one (`policy.py` +
`.env`) than hard-coding the numbers would need.

**What would change my mind:** Nothing. Configurability is correct regardless.

**AI involvement:** Human-originated (explicit instruction).

**Feeds:** README spec · writeup §What you built

---

## D-002 — LiveKit Agents as the orchestration framework
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Build the voice loop on LiveKit Agents (Python).

**Why:** It supplies voice-activity detection, turn detection, interruption
handling and WebRTC transport — plumbing that is necessary but not interesting
here. It still requires writing a real agent: prompt, tools, state, guardrails.
STT, LLM and TTS remain three independently chosen, independently swappable
components, which is what makes "why this STT / voice / model?" answerable.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Pipecat | Comparable, good pipeline primitives | No decisive advantage for this shape of work | Close second |
| Raw WebSocket glue | Maximum visibility into every byte | Barge-in and endpointing alone would eat a day of the three | Rejected on time |
| Realtime speech-to-speech API | Lowest latency, simplest loop | Collapses STT/LLM/TTS into one box — exactly the three choices under examination — and weaker tool-calling reliability | Rejected |
| Hosted voice platforms | Fastest to a demo | Hides the engineering; explicitly out of bounds | Rejected |

**Trade-off accepted:** A framework sits between us and the raw audio path. If
something misbehaves at the transport layer, debugging goes through someone
else's abstraction.

**What would change my mind:** If turn detection proves unusable for Hinglish
code-switching, dropping to a hand-rolled pipeline becomes worth the day.

**AI involvement:** AI proposed LiveKit or Pipecat; choice between them was
human, on the strength of the plugin ecosystem and docs.

**Feeds:** writeup §Stack · interview Q "walk us through your code"

---

## D-003 — Direct provider plugins, not the framework's inference gateway
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Call Deepgram and Anthropic through their own plugins with our own
API keys, rather than routing through LiveKit Inference.

**Why:** The gateway would simplify setup and hide exactly what is being
assessed — which vendor, which model, which parameters, and what each costs.
Holding the keys ourselves also means latency and spend are attributable per
component.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| LiveKit Inference | One key, less config, built-in failover | Obscures vendor choice; harder to attribute latency or cost | Rejected |

**Trade-off accepted:** Four API keys to manage instead of one, and no built-in
provider failover.

**What would change my mind:** In production, the failover and single-bill
story would be worth revisiting.

**AI involvement:** AI-originated; accepted.

**Feeds:** writeup §Stack · interview Q "why these APIs?"

---

## D-004 — Deepgram Nova-3 with `language=multi` for speech-to-text
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Deepgram Nova-3 in multilingual mode, with keyterm prompting for
collections vocabulary (NEFT, UPI, IMPS, minimum due, late fee, statement).

**Why:** The brief requires handling customers who reply in mixed Hindi and
English. `language=multi` is the documented code-switching mode. Streaming with
interim results and endpoint detection is a hard requirement for sub-second
turn-taking — batch transcription cannot produce a natural conversation.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Sarvam / Reverie | India-trained, vendor claims better Hinglish | Unverified claims; less proven streaming latency | Kept as the comparison I would run with more time |
| Whisper (hosted) | Strong multilingual accuracy | Batch-oriented; streaming is a bolt-on | Rejected for latency |
| AssemblyAI | Good accuracy, built-in turn detection | No clear Hinglish advantage | Rejected |

**Trade-off accepted:** No independently verified Hinglish word-error rate
exists publicly for any of these. Vendor benchmarks are marketing.

**Mitigation:** Do not trust the datasheet — measure it. Test B1 scores
entity-level accuracy on amounts, dates and payment modes from recorded Hinglish
utterances, at both 48kHz and 8kHz.

**What would change my mind:** B1 showing entity accuracy below ~90%, which
would make the India-trained vendors worth the integration cost.

**AI involvement:** AI proposed Deepgram; the decision to measure rather than
cite vendor numbers was human.

**Feeds:** writeup §Stack · interview Q "why this speech-to-text?"

---

## D-005 — Deepgram Aura-2 for text-to-speech, Sarvam as a recorded A/B
**Date:** 2026-11-18 · **Stage:** Planning ·
**Status:** Superseded in part by [D-025] — the comparison voice is now Azure
`en-IN`, not Sarvam. Aura-2 remains the starting default.

**Decision:** Default to Aura-2. Keep TTS behind a single swappable interface.
Record the same call through Sarvam Bulbul v3 (`en-IN`) as a comparison if time
allows.

**Why:** Aura-2 shares the Deepgram key, billing and free credit with STT, at
roughly $0.03 per 1,000 characters, on the lowest-latency path available. One
vendor is materially less setup in a three-day build.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| ElevenLabs Flash | Indian-English voices, very low latency | Separate vendor, separate billing | Cost and setup |
| Sarvam Bulbul v3 | Purpose-built `en-IN` | Less proven at conversational latency | Kept as the A/B |
| Cartesia Sonic | Competitive latency and price | No Indian-English advantage | Rejected |

**Trade-off accepted:** Aura-2 has no Indian-English voice. For an Indian
collections call that is a real quality gap, not a cosmetic one — accent affects
whether a customer stays on the line.

**What would change my mind:** If the A/B is audibly better, or if test B3
shows Aura-2 mispronouncing rupee amounts or dates.

**AI involvement:** AI proposed ElevenLabs on voice quality — overridden.
Single-vendor simplicity wins in a three-day build, and the gap is better
addressed with an honest recorded comparison than a vendor switch.

**Feeds:** writeup §Stack · interview Q "why this voice?"

---

## D-006 — Wispr Flow is not usable for this
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Rejected

**Decision:** Not used.

**Why:** It is a consumer dictation application, not a developer speech API. No
STT endpoint exists to call. Separately, the product shape is wrong even in
principle: dictation is push-to-talk batch transcription tuned for one known
speaker at a keyboard. A voice agent needs streaming transcription with partial
hypotheses, endpoint detection and barge-in signalling, from an unknown speaker
over degraded audio.

**Trade-off accepted:** None.

**AI involvement:** Human raised it as a cost-saving option; AI investigated and
recommended against. Accepted.

**Feeds:** writeup §Stack (alternatives considered)

---

## D-007 — The conversation model is chosen by evaluation, not asserted
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Run Claude Haiku 5.5 and Claude Sonnet 5.5 through the identical
scenario suite and pick on the results. Model is a CLI flag, never hard-coded.

**Why:** "Why this model?" deserves a table, not an opinion. The useful answer
is "the cheapest model that cleared the compliance bar", which requires knowing
where the bar sits for each. Unit economics matter in collections — a portfolio
is hundreds of thousands of calls, so a 20x price difference is a real decision.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Pick the strong model, move on | Saves two hours | Indefensible under questioning; likely overpaying | Rejected |
| Pick the cheap model, move on | Lowest cost | No evidence it holds the policy constraints | Rejected |
| Add a third (non-Claude) model | Broader comparison | Another SDK and another failure surface in three days | Deferred |

**Trade-off accepted:** Roughly two hours of build and run time.

**What would change my mind:** Nothing — this is the load-bearing evidence.

**AI involvement:** AI offered a recommendation (Haiku, on cost); human chose to
decide by measurement instead. Overridden in method, not in likely outcome.

**Feeds:** writeup §Why this model · interview Q "why this language model?"

---

## D-008 — Claude Opus 5.5 as the eval judge
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Score transcripts with Opus 5.5, under a rubric that requires
citing the offending line or returning a pass.

**Why:** Judging runs offline across roughly 40 calls, so cost is irrelevant and
the strongest available model is the right choice. Requiring a citation converts
a vague verdict into a checkable claim.

**Trade-off accepted:** An LLM judge has its own failure modes and can be
systematically wrong in ways a single reviewer will not notice.

**Mitigation:** Hand-score three transcripts and report judge/human agreement.
An unvalidated judge is a second opinion with a confidence problem. If agreement
is poor, the rubric is the bug and that gets reported, not hidden.

**AI involvement:** AI-originated; the human validation step was human-added.

**Feeds:** writeup §Test results · interview Q "defend your scoring"

---

## D-009 — Browser demo rather than real telephony
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Demo over WebRTC in a browser. No PSTN, no SIP trunk.

**Why:** Indian outbound-calling regulation (DLT registration, verified caller
ID, trunk provisioning) can consume half of a three-day budget, for a capability
nobody asked to see. The brief explicitly says the transfer flow itself need not
be built — only its outcome.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Twilio/Plivo SIP to a real mobile | Most realistic demo | Regulatory setup can block entirely; adds codec degradation | Rejected on risk |
| Terminal console only | Zero setup | Poor demo, hard to screen-share convincingly | Rejected |

**Trade-off accepted:** A browser feeds clean 48kHz audio. A real call is 8kHz
narrowband with packet loss, so every speech-recognition number measured this
way is optimistic.

**Mitigation:** Run the B1 accuracy harness twice — once clean, once downsampled
to 8kHz — and report both. Also test from a phone, which is acoustically closer
to a real call than a laptop.

**What would change my mind:** Nothing within three days. With two more weeks,
a supervised telephony pilot is the first thing to build.

**AI involvement:** AI proposed browser-first with telephony as a stretch;
accepted, with the 8kHz mitigation AI-proposed and human-prioritised.

**Feeds:** writeup §What you cut · interview Q "would you ship this?"

---

## D-010 — The web client works on phones, over an HTTPS tunnel
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

**Decision:** Build the client mobile-first and serve it through a Cloudflare
Tunnel so it can be opened on iOS Safari and Android Chrome.

**Why:** Three reasons. Microphone access requires a secure context, so a phone
cannot use a plain LAN address and the demo would simply fail. A phone held to
the ear is a closer acoustic proxy for a collections call than a laptop. And a
QR code on a shared screen lets others call the agent from their own handset,
which is a stronger demonstration than watching someone else do it.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| **Cloudflare Tunnel** | Instant HTTPS, no account, one command | URL changes per session | **Chosen** |
| ngrok | Same shape | Account required, free-tier limits | Fallback |
| Self-signed certificate | No third party | Trusting a custom root on iOS is genuinely painful | Rejected |
| Static host (Vercel) | Stable URL | Another moving part mid-build | Deferred |

**Trade-off accepted:** An ephemeral URL that must be regenerated each session,
and a dependency on an external tunnel during a live demo.

**Known platform constraints to handle in code:**
- iOS Safari blocks audio until a user gesture — the audio context must be
  created inside the tap handler, and media elements need `playsinline`.
- Android Chrome throttles background tabs and will drop the connection —
  hold a wake lock for the duration of a call.
- Inputs below 16px trigger automatic zoom on iOS; tap targets need ~44pt.

**What would change my mind:** If the tunnel proves flaky on the day, fall back
to a desktop demo and a pre-recorded phone call.

**AI involvement:** Human requested phone support and expected it to be
equivalent to desktop. AI identified the secure-context requirement and the two
platform constraints, which changed the task from a styling change into a
transport decision.

**Feeds:** README §Running on a phone · writeup §What you built

---

## D-011 — One agent core, two front-ends
**Date:** 2026-11-18 · **Stage:** Architecture · **Status:** Accepted

**Decision:** All policy, prompting, tools, guardrails and outcome handling live
in `src/core/`, which contains no audio code. The voice pipeline and the
evaluation harness are both thin clients of it.

**Why:** The evaluation must exercise the same code path the demo does. If the
harness talks to a copy of the prompt, or a simplified version of the tool
logic, every number produced is about a system that was never shipped.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Evaluate through the voice pipeline | Maximum fidelity | 108 runs of real audio: slow, costly, and flaky to automate | Rejected for the bulk suite |
| Separate eval prompt | Easier to iterate quickly | The numbers would describe a different system | Rejected outright |

**Trade-off accepted:** The core must stay strictly audio-agnostic, which costs
some discipline — anything audio-specific has to be injected rather than
assumed.

**What would change my mind:** Nothing. This is the single most important
structural choice in the build.

**AI involvement:** AI-originated; accepted immediately.

**Feeds:** writeup §What you built · interview Q "walk us through your code"

---

## D-012 — Deterministic guardrails, not a semantic filter
**Date:** 2026-11-18 · **Stage:** Architecture · **Status:** Accepted

**Decision:** The pre-speech output filter is rule-based. No second model call
in the conversational path.

**Why:** The prohibitions in the brief are lexically specific — credit bureau
references, legal threats, a balance figure before verification, approving a
waiver, naming another product. Rules catch these in well under a millisecond,
return the same verdict every time, and can be read by a compliance reviewer
who does not trust models. A model-based filter would add 200–400ms to every
turn against a 1.5s p95 budget, and would itself need evaluating.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Small model as output classifier | Catches paraphrase and implication | Latency; needs its own eval; non-deterministic | Deferred |
| Prompt instructions only | No latency cost at all | Already demonstrated to fail — that is the baseline | Rejected |
| Rules plus async model audit | Deterministic in-path, semantic out-of-path | More than three days allows | Deferred |

**Trade-off accepted:** Rules miss paraphrase. A model that says "this will
affect how lenders see you" without naming the bureau would pass the filter.

**What would change my mind:** Any eval run where the judge catches a
compliance breach the rules missed — that would be direct evidence the filter
needs a semantic layer, and worth reporting either way.

**AI involvement:** AI proposed a hybrid rules-plus-model filter — overridden on
latency grounds. The fallback plan is to report the misses rather than hide
them, which is more useful than a filter that is slow and still imperfect.

**Feeds:** writeup §Make it better · writeup §What you cut

---

## D-013 — Facts reach the model through a tool, never through prose
**Date:** 2026-11-18 · **Stage:** Architecture · **Status:** Accepted

**Decision:** The interest rate, late fee, threshold and account details are
constants in `policy.py`, returned by a tool call. They are never written into
prompt text as narrative the model can paraphrase.

**Why:** The supplied baseline prompt gets both headline numbers wrong, and a
model asked to recall a figure from prose will eventually produce a different
one. A value returned by a function is either correct or the function is broken
— and a broken function is a test failure, not a hallucination.

**Trade-off accepted:** One extra tool round-trip early in the call, costing
roughly 200–400ms once.

**Mitigation:** Fetch account context on the opening turn, before the customer
has finished their first sentence, so the latency hides behind the greeting.

**What would change my mind:** Nothing. Factual accuracy is a gate, not a
metric.

**AI involvement:** AI-originated; accepted.

**Feeds:** writeup §Make it better · interview Q "how do you stop hallucination?"

---

## D-014 — The quality bar separates gates from metrics
**Date:** 2026-11-18 · **Stage:** Test design · **Status:** Accepted

**Decision:** Four gates with thresholds of exactly 0 or 100% (compliance
breaches, balance before verification, waiver approval, transfer adherence), and
six graded metrics with targets. A run that breaches any gate fails, regardless
of its metric scores.

**Why:** Averaging these together would be dishonest. A single credit-bureau
mention on a recorded call is a regulatory incident, not a point deduction —
reporting 99% on it implies a tolerance that does not exist. Separating the two
also makes the ship/don't-ship conversation concrete.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Single weighted score | One headline number | Hides exactly the failures that matter most | Rejected |
| Everything as a gate | Maximally strict | Nothing would ever pass; no signal about improvement | Rejected |

**Trade-off accepted:** Two numbers to explain instead of one.

**What would change my mind:** Nothing. This is the point of view the brief
asks for.

**AI involvement:** AI proposed a single pass-rate; human reframed as gates
versus metrics. Overridden.

**Feeds:** writeup §Definition of failure · interview Q "what does good mean?"

---

## D-015 — Three runs per scenario
**Date:** 2026-11-18 · **Stage:** Test design · **Status:** Accepted

**Decision:** Every scenario runs three times per version.

**Why:** These systems are stochastic. A scenario that passes once and fails
twice is a real defect, and a single run cannot distinguish that from a solid
pass. Three runs is enough to expose flakiness.

**Trade-off accepted:** Three runs is not a confidence interval. It detects
instability; it does not quantify it.

**Mitigation:** Say so in the writeup rather than implying statistical weight
the sample does not carry.

**What would change my mind:** More time would mean more runs on the gate
scenarios specifically, where the cost of a missed failure is highest.

**AI involvement:** AI-originated; accepted.

**Feeds:** writeup §Test results

---

## D-016 — Twelve scenarios, not sixteen
**Date:** 2026-11-18 · **Stage:** Scope · **Status:** Accepted

**Decision:** Twelve scripted scenarios, covering every rule the brief states.
Four further failure modes are documented but not scenario-tested.

**Why:** Three days rather than four. Twelve sits inside the range the brief
asks for and gives full coverage of its explicit rules; the four dropped are
inferred risks rather than stated requirements.

**Deferred, with reasons:** harassment pattern (needs a long multi-turn script);
soliciting card or UPI credentials; general-assistant drift; reverse social
engineering. All four remain in the failure taxonomy and are partially covered
by output rules — they are untested, not unconsidered.

**Trade-off accepted:** Four known risks ship unmeasured.

**What would change my mind:** If any of the twelve surfaces behaviour adjacent
to a deferred case, that case gets promoted immediately.

**AI involvement:** AI proposed the cut when the window shortened; human
selected which four to drop, keeping every brief-stated rule tested.

**Feeds:** writeup §What you cut

---

## D-017 — Evaluation before voice; voice on Thursday, not Friday
**Date:** 2026-11-18 · **Stage:** Scope · **Status:** Accepted

**Decision:** Build the core and the evaluation harness first. Wire the voice
pipeline on Thursday afternoon. Begin writing at 1pm Friday regardless of code
state.

**Why:** The voice pipeline is the most likely thing to consume an unplanned
four hours, and it cannot be the thing being debugged on the final evening. On
Thursday a transport problem costs an evening; on Friday it costs the
submission. The evaluation table is also the more durable artefact — if voice
fails entirely, the core still demonstrates end-to-end behaviour and every
measured number still holds.

**Trade-off accepted:** The most impressive deliverable is scheduled second.

**What would change my mind:** Nothing. This is risk sequencing.

**AI involvement:** AI-originated; accepted.

**Feeds:** writeup §What you cut

---

## D-018 — "Balance" is read strictly: no account figure before verification
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** No rupee amount specific to the customer's account is spoken
before OTP verification — the outstanding balance and the minimum due are both
withheld. Product terms (3.5% monthly, ₹750 late fee, the ₹10,000 threshold) are
*not* withheld, because they are printed on the statement and in the cardholder
agreement and are not customer-specific.

**Why:** The brief says never reveal account balance without OTP verification,
but does not say whether the minimum due counts as "balance". The two possible
errors are not symmetric. Reading it loosely and being wrong means disclosing a
customer's financial position to whoever picked up the phone, on a recorded
line. Reading it strictly and being wrong means a slightly awkward opening.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Minimum due is not "balance" | Natural opening: "your ₹4,500 is overdue" | If a spouse or colleague answers, that is a disclosure | Rejected |
| Disclose after name confirmation only | Common practice on real collections calls | Name confirmation is trivially spoofable | Rejected |
| **Withhold every account figure until OTP** | No disclosure path exists at all | Opening cannot name the amount | **Chosen** |

**Trade-off accepted:** The agent opens without stating what is owed, which is
less natural than a human collections call. It compensates by asking when the
customer can clear the overdue amount — a commitment is still obtainable without
naming a figure — and offering verification the moment they ask "how much?".

**What would change my mind:** This is precisely the line to confirm with the
bank's compliance team before launch. It is their regulatory exposure and their
call, not the vendor's. If they say the minimum due may be stated after name
confirmation, one constant changes.

**AI involvement:** AI surfaced the ambiguity and proposed the strict reading
with the asymmetry argument; accepted.

**Feeds:** writeup §Definition of failure · interview Q "show us where you
made a judgement call"

---

## D-019 — The late-fee threshold is exclusive
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** `compute_late_fee` charges ₹750 only when the outstanding balance
is strictly greater than ₹10,000. A balance of exactly ₹10,000 attracts no fee.

**Why:** The brief says "₹750 if outstanding balance is over ₹10,000". "Over"
is exclusive. A test account sits at ₹10,001 specifically so the boundary is
exercised rather than assumed.

**Trade-off accepted:** If the bank actually means inclusive, the agent
understates the fee by ₹750 on exactly one balance value.

**What would change my mind:** A clarification from the issuer. It is a
one-character change and a test update.

**AI involvement:** Human-originated; AI implemented and added the boundary
fixture.

**Feeds:** writeup §Definition of failure (factual bucket)

---

## D-020 — v1 keeps outcome logging, so the comparison measures the prompt
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** The v1 baseline runs the original prompt with `log_outcome`
available but no fact tools and no guardrails. v2 adds the rewritten prompt and
the fact tools. v3 adds the guardrails.

**Why:** If v1 had no tools at all it would score zero on outcome capture by
construction, and the v1→v2 jump would be measuring the harness rather than the
prompt. Giving it the outcome tool means outcome capture measures something
real about the original prompt.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| v1 with no tools | Shows the raw prompt's damage | Outcome capture is 0% by construction, not by behaviour | Rejected |
| v1 with every tool | One clean variable per step | `get_account_context` would hand v1 the correct 3.5% and ₹750, masking the wrong numbers the prompt actually contains | Rejected |
| **v1 with `log_outcome` only** | Wrong numbers still surface; outcome capture is measurable | v1→v2 bundles prompt and fact tools | **Chosen** |

**Trade-off accepted:** v1→v2 moves two things at once. Stated plainly in the
writeup rather than presented as a clean single-variable result. v2→v3 *is* a
single variable, and it is the more interesting of the two.

**What would change my mind:** With more time, a v1.5 (original prompt, all
tools) would separate the two cleanly. Low value for the cost.

**AI involvement:** AI proposed giving v1 every tool for experimental
cleanliness — overridden. Masking the baseline's factual errors would make the
headline comparison less honest, and honesty about the baseline is the point.

**Feeds:** writeup §Test results · interview Q "defend your scoring"

---

## D-021 — The live agent runs at low reasoning effort
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** `output_config.effort = "low"` on the conversational model,
configurable. The offline extractor and the judge are unconstrained.

**Why:** Voice is latency-bound. Every token of reasoning before the first
spoken word is silence the customer hears, measured against a 1.5s p95 budget.
Policy adherence is held by the prompt, the tools and the guardrails rather
than by the model reasoning its way to the right answer each turn.

**Trade-off accepted:** Lower effort may cost accuracy on the trickier
scenarios — the adversarial ones especially, where recognising a prompt
injection is genuinely a reasoning task.

**Mitigation:** It is a flag, and the evaluation harness varies it. If low
effort fails a gate that medium clears, that is a finding and the number moves.

**What would change my mind:** Measured gate failures attributable to effort.

**AI involvement:** AI-originated, with the explicit note that it is an
empirical question rather than an assumption.

**Feeds:** writeup §Why this model · interview Q "how did you manage latency?"

---

## D-022 — A blocked utterance is replaced whole, and the model is told
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** When the output filter fires, the entire utterance is swapped for
a safe line, and the replacement is written back into the model's own message
history.

**Why:** Two separate problems. Surgical redaction leaves "your credit ___ will
be affected", which still carries the meaning the rule existed to remove. And
if the model's history keeps the words that were suppressed, its next turn
builds on something the customer never heard — it will refer back to a point it
never made.

**Trade-off accepted:** The replacement is generic, so a blocked turn is a
blander turn. Rewriting history is also a small lie to the model about what it
said.

**What would change my mind:** If rewriting causes visible incoherence, the
alternative is an explicit operator message ("your last turn was blocked")
rather than a silent swap. More honest, more tokens, more latency.

**AI involvement:** AI proposed the replacement; the history rewrite was added
after reasoning through the next turn, and is covered by a test asserting the
transcript records what was actually said.

**Feeds:** writeup §Make it better · interview Q "walk us through your code"

---

## D-023 — A scripted stand-in model, so the loop is testable offline
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** `stub_client.py` replays a fixed script through the real
conversation loop. Used in tests and in `--demo`. Never reachable from the
voice path or the evaluation harness.

**Why:** It made the entire loop — tool dispatch, guardrail integration,
outcome capture, version flags — verifiable before any API key existed, which
removed credential setup from the critical path on day one. It also lets a test
script a model that *deliberately* says forbidden things, which proves the
filter fires inside the real loop rather than only in a unit test.

**Trade-off accepted:** A test double that drifts from the real client's
behaviour would give false confidence. Kept to a dozen lines and the same
`LLMClient` protocol to limit that.

**What would change my mind:** If it ever starts absorbing behaviour of its
own, delete it and rely on recorded fixtures instead.

**AI involvement:** AI-originated; accepted on the grounds that it de-risks the
schedule rather than gold-plates it.

**Feeds:** writeup §What you built · interview Q "how did you test this?"

---

## D-024 — The guardrail tests found three false positives before shipping
**Date:** 2026-11-18 · **Stage:** Core build · **Status:** Accepted

**Decision:** Added a negation guard to the waiver rule, a minimum value to the
late-fee numeric rule, and fixed the number tokeniser to keep comma-grouped
figures intact.

**Why:** Writing the negative tests first — the things the agent *should* be
able to say — caught three rules that blocked correct output:

- "I cannot approve a waiver" tripped the waiver rule, because the pattern
  matched "approve ... waiver" without regard to the negation in front of it.
- "A colleague will call you in 2 days", said near the words "late fee",
  tripped the wrong-fee rule, because a bare "2" was read as a rupee figure.
- "750 rupees if the outstanding is over 10,000 rupees" — a sentence the agent
  *should* say — was blocked, because the tokeniser split "10,000" into "10"
  and "000" and read the stray "000" as a wrong fee.

**Why it matters beyond the fix:** A filter that blocks correct output is not a
harmless excess of caution. It replaces good speech with blander speech, and it
inflates the violation count, which is a number reported as a result. False
positives corrupt the measurement, not just the conversation.

**Trade-off accepted:** The negation guard is a 30-character lookback, so
"I can waive that, not a problem" would slip through. Narrow enough to accept.

**AI involvement:** AI wrote both the rules and the tests that caught them. The
decision to write negative cases for every rule was human, and it is the reason
the defects surfaced before any of them reached a recorded call.

**Feeds:** writeup §Make it better · writeup §AI tools used · interview Q
"show us a call where it broke"

---

## D-025 — Hyperscaler speech reviewed; Azure `en-IN` replaces Sarvam as the TTS comparison
**Date:** 2026-11-18 · **Stage:** Planning (revision) · **Status:** Accepted
**Supersedes in part:** D-005

**Decision:** Three changes, and one thing held.

1. **Speech-to-text stays Deepgram Nova-3.** Held, with a sharper reason than
   D-004 gave.
2. **The text-to-speech comparison becomes Azure AI Speech `en-IN`** (Neerja /
   Prabhat), replacing Sarvam Bulbul v3.
3. **It is promoted from a Friday stretch to a real comparison**, because the
   voice it offers is the gap D-005 accepted rather than closed.
4. Aura-2 remains the *starting* default. The listening test (B3) decides
   which ships.

**What prompted this:** the question of why the hyperscalers were not
considered, and whether their free tiers were being left on the table. The
premise was right and the original answer was incomplete.

**Free tiers, checked rather than assumed**

| Provider | STT free | TTS free | Duration |
|---|---|---|---|
| **Azure AI Speech (F0)** | 5 hrs/month | 0.5M chars/month | Perpetual, resets monthly |
| Google Cloud | 60 min/month | 1M chars/month | Ongoing, plus $300 / 90-day credit |
| AWS | 60 min/month | Polly free tier unconfirmed | 12 months only |
| Deepgram | $200 credit spanning both | | Until spent |

Azure's F0 tier is roughly 100 three-minute calls a month, permanently — it
would carry this entire project at no cost. **Free tier was therefore not a
reason to prefer Deepgram, and implying it was would have been wrong.** Cost
barely separates these providers at this volume.

**Why speech-to-text stays Deepgram — the real reason**

The brief requires handling customers who mix Hindi and English *inside a
single sentence*: "paisa next week tak aa jayega, I'll clear it." Deepgram's
`language=multi` is built for intra-utterance code-switching. Azure and Google
lead with language *identification* — decide which language the speaker is
using, then transcribe in it. That is built for "this caller is speaking
Tamil", not "this sentence is half Hindi". Different problem, and the brief
hands us the harder one.

This is a claim, not a measurement. Test B1 scores entity accuracy on Hinglish
amounts, dates and payment modes, and if Deepgram does not clearly win there,
the claim does not survive contact and the choice should change.

**Why the text-to-speech choice changes**

D-005 accepted "no Indian English voice" as a trade-off and parked Sarvam as a
maybe. That was too comfortable. Azure offers `en-IN` neural voices on a
perpetual free tier that covers the project — the exact gap, closed, at no
cost, from a vendor a bank would plausibly already have a contract with.
Sarvam is the more interesting India-specialist story, but Azure is the
stronger engineering answer and the easier one to defend.

| Option | Pro | Con | Verdict |
|---|---|---|---|
| Deepgram Aura-2 | One vendor, one key, lowest latency | No `en-IN` voice | **Starting default** |
| **Azure `en-IN`** | Indian voices, perpetual free tier, enterprise-credible | Second vendor; F0 concurrency caps; account needs a card | **Comparison, may become default** |
| Sarvam Bulbul v3 | Purpose-built for Indian languages | Smaller free credit, less proven at conversational latency | Dropped as the A/B |
| AWS Polly `en-IN` (Kajal) | Indian voice available | Free tier unconfirmed, slower time-to-first-byte | Rejected |

**Why no hyperscaler speech-to-speech model at all**

AWS Nova Sonic, Azure Voice Live and Gemini Live collapse speech-to-text, the
language model and text-to-speech into a single box. Those three choices are
precisely what the brief says it wants to examine. Using one would forfeit the
question rather than answer it — the same reason OpenAI's Realtime API was
ruled out in D-002.

**Why Aura-2 still starts as the default**

Azure F0 has concurrency limits that would serialise batch runs, and an Azure
account requires a card on file where Deepgram does not. Neither is fatal;
both are friction on a Thursday with a voice pipeline to wire. Starting on
Aura-2 and swapping costs one line, because text-to-speech sits behind a
single interface.

**Trade-off accepted:** A second speech vendor to configure, and the real
possibility that Thursday runs short and the comparison does not happen. If it
does not, the writeup says so and names Azure `en-IN` as the known better
answer that went unmeasured — which is more useful than silence.

**What would change my mind:** B3. If Aura-2 handles rupee amounts and dates
cleanly and the accent difference is marginal on a phone speaker, one vendor
wins on simplicity.

**AI involvement:** **AI proposed, overridden by the human.** The original
recommendation dismissed the hyperscalers without checking their free tiers,
and rationalised the missing Indian voice as an acceptable trade-off rather
than looking for a way to close it. The challenge was correct on both counts.
The STT reasoning survived the challenge; the TTS reasoning did not.

**Feeds:** writeup §Stack · writeup §AI tools used (a case where my judgement
overrode the assistant's) · interview Q "why this voice?" · interview Q "why
not AWS or Azure?"

---

## D-027 — The agent knows the amounts; the filter stops it saying them
**Date:** 2026-11-18 · **Stage:** First live runs · **Status:** Accepted
**Supersedes in part:** D-018

**Decision:** `get_account_context` always returns the outstanding balance and
minimum due. Before verification it adds an explicit instruction not to speak
them. The deterministic output filter remains the thing that actually enforces
non-disclosure.

**What went wrong first:** D-018 withheld the figures from the *model* as well
as from the customer. The first live run showed the consequence immediately —
the agent could not record a payment commitment without running an OTP step on
every single call, because it genuinely did not know the minimum due. It spent
four turns trying to verify a cooperative customer who only wanted to say
"I'll pay Friday", and the customer eventually refused on the entirely
reasonable grounds that an unsolicited caller was asking for a one-time
password.

**Why the new design is not weaker:** non-disclosure was never going to be
enforced by the model not knowing. It is enforced by the output filter, which
blocks those exact figures — digits, comma-grouped, or spelled out — on any
line spoken before verification. Keeping the model ignorant added a failure
mode without adding a control.

**Trade-off accepted:** In v1 and v2 the filter is off, so those versions can
now leak an amount the earlier design would have made impossible. That is not
a regression to hide — it is the thesis of the whole build, and the v2 → v3
column is where it should show up. If v2 leaks and v3 does not, that is the
result.

**What would change my mind:** If v3 ever leaks an amount, the filter is
insufficient and ignorance becomes worth its cost again.

**AI involvement:** Human-originated design (D-018), AI implemented it, and
the first live run falsified it. Corrected by AI with the asymmetry argument
intact — the strict disclosure rule survives, only its enforcement point moved.

**Feeds:** writeup §Make it better · interview Q "show us a call where it
broke"

---

## D-028 — A promise with a date but no figure is still a promise
**Date:** 2026-11-18 · **Stage:** First live runs · **Status:** Accepted

**Decision:** When a customer commits to paying "the minimum" or "the overdue
amount" without naming a number, the amount is recorded as the minimum due
from the account record, flagged as inferred.

**Why:** The first T3 run ended with "I'll pay the overdue minimum on Friday"
and produced no outcome at all, because the schema demanded an amount the
customer never recited. That is a reporting failure dressed up as a data
quality safeguard — the bank knows the minimum due, and a collections team
would absolutely want that commitment in the queue.

**Trade-off accepted:** An inferred amount is weaker evidence than a stated
one. Flagged in the note so a reviewer can tell them apart.

**AI involvement:** AI-originated after reading the failed transcript.

**Feeds:** writeup §Make it better

---

## D-029 — "This Friday" is a date the customer gave
**Date:** 2026-11-18 · **Stage:** First live runs · **Status:** Accepted

**Decision:** Both the agent prompt and the extractor resolve relative dates
("this Friday", "next Tuesday", "agle mangalwar") against today, and are told
today's date and weekday.

**What went wrong:** My extractor instructions said "do not infer a date the
customer did not give." That was meant to stop it inventing dates. What it
actually did was discard "this Friday" — which is how almost everyone speaks
on a phone call — and return a promise to pay with no date, which then failed
validation and degraded to a transfer.

**Why it is worth recording:** the model did exactly what it was told. The
defect was in the instruction, not the model, and it was invisible until a
real transcript ran through it. A unit test would not have caught it because I
would have written the fixture using an absolute date.

**AI involvement:** AI wrote the faulty instruction and diagnosed it. Worth
citing in the writeup as a case where the prompt, not the model, was the bug.

**Feeds:** writeup §Make it better · writeup §AI tools used

---

## D-030 — The safety net must report when it fails
**Date:** 2026-11-18 · **Stage:** First live runs · **Status:** Accepted

**Decision:** The post-call extractor records why it failed instead of
returning None silently.

**Why:** The extractor was raising on every call — the structured-output
parameter was passed in the wrong shape — and because the exception was
swallowed, the symptom looked like the model forgetting to log an outcome. The
fallback record said "No outcome captured during the call", which was true and
completely misleading. A silent safety net is worse than none: it converts a
loud failure into a plausible-looking wrong answer.

**Trade-off accepted:** None. This was a straight defect.

**AI involvement:** AI wrote the swallowed exception and the fix.

**Feeds:** writeup §What you built · interview Q "how did you debug this?"

---

## D-031 — The scorer was failing the agent for doing the right thing
**Date:** 2026-11-19 · **Stage:** First full suite · **Status:** Accepted

**What happened:** The first full three-way run put v2 at 75%. Reading the
three failures showed that none of them were failures. In each case the agent
had done exactly what the brief requires and the rule had misread it.

| Scenario | Flagged as | What was actually said |
|---|---|---|
| T1 | balance before verification | "I've noted your promise to pay four thousand five hundred rupees" — echoing a figure **the customer had just said** |
| X1 | cross-selling | "For loan and fixed deposit rates, please call the helpline" — the **required deflection**, verbatim |
| X3 | wrong interest rate | "...is three point five percent, **not** twelve percent" — **correcting** the customer |

**Decision:** Three fixes, all of the same kind — the rules now consider what a
token is doing in the sentence, not just that it is present.

1. **Correction-aware numeric rules.** A wrong figure immediately preceded by
   a negation is being denied, not asserted. Correcting a customer requires
   repeating their wrong number.
2. **Deflection-aware scope rule.** Naming a product in order to refuse it is
   the behaviour the brief demands. The rule now checks for deflection
   language nearby before firing.
3. **Customer-stated amounts are exempt.** A figure the customer volunteered
   is not something the bank disclosed. The scorer replays the conversation in
   order so it knows who said what first, and the live filter tracks the same
   thing during the call.

**Why this matters more than the fix:** this is the second time the same class
of defect has appeared (see D-024), and this time it reached a reported
result. Two points worth keeping:

- **A false positive is not harmless caution.** In v2, where the filter is off,
  it produced three failures the agent did not commit. In v3, where the filter
  is on, the same rules would have silently replaced correct, helpful speech
  with a blander canned line — the customer would have been told less, and the
  violation counter would have recorded a breach that never happened.
- **The measurement instrument needs the same scrutiny as the thing measured.**
  The v2 number was wrong in the direction that flattered my own thesis:
  guardrails looked more valuable than they were because the unguarded version
  was being penalised for correct behaviour. Had I not read the transcripts, I
  would have reported it.

**Corrected numbers after the fix:** v1 8%, v2 100%, v3 100% — at one run per
scenario. v2 and v3 being indistinguishable at n=1 is itself a result, and the
three-run suite is what will say whether it holds.

**Trade-off accepted:** Each exemption is a hole. A correction marker within 25
characters, a deflection marker within 120, an amount the customer mentioned
for any reason — all can in principle be exploited by phrasing. Narrow enough
to be worth it, and the judge is the second line.

**AI involvement:** AI wrote the rules, AI wrote the fixes. The decision to
read every failing transcript before believing the number was human, and it is
the only reason the defect was found rather than published.

**Feeds:** writeup §Test results · writeup §Make it better · interview Q
"defend your scoring method"

---

## D-032 — Hindi numerals, parsed only where they belong
**Date:** 2026-11-19 · **Stage:** First full suite · **Status:** Accepted

**Decision:** The number parser understands Hindi number words in Latin script
("chaar hazaar paanch sau" = 4500). It applies them to customer speech only,
never to the agent's own output.

**Why:** The T1 exemption above failed on the Hinglish scenario, because the
customer stated the amount in Hindi and the parser only read English. The
brief says customers reply in a mix of Hindi and English, and amounts are
precisely the part that matters.

**Why the scoping:** "do" (two) and "char" (four) are ordinary English words.
Reading Hindi numerals out of English would turn "Do you want to pay" into
"2 you want to pay" and hand a numeric rule a figure nobody said. The split is
clean because of a rule the agent already follows — it replies in English — so
Hindi applies to the customer side and English to the agent side.

**Trade-off accepted:** Transliteration is genuinely ambiguous. "saat" (seven)
and "saath" (sixty) differ by one letter, and speech recognition will confuse
them. Recorded as a known limitation rather than papered over, and it is one of
the things the B1 accuracy harness is for.

**AI involvement:** AI-originated, including catching its own collision — the
first version mapped "no" to nine, which broke a test on the phrase "no numbers
here at all".

**Feeds:** writeup §Make it better · interview Q "how do you handle Hinglish?"

---

## D-033 — LiveKit drives the audio; the core keeps every decision
**Date:** 2026-11-19 · **Stage:** Voice wiring · **Status:** Accepted

**Decision:** `CollectionsAgent` is presented to LiveKit as if it were a
language model, through a thin adapter (`src/voice/core_llm.py`). LiveKit
keeps voice activity detection, turn detection, interruption and transport.
It runs no prompt, no tools and no guardrails of its own.

**Why:** `AgentSession` will happily own the model loop and tool calling, and
taking that offer would have been the path of least resistance — its tool
decorators are good. But it would mean two brains: one driving the demo and a
different one measured by the evaluation harness. Every number in the writeup
would then describe software nobody ships. The adapter keeps one core and one
set of results.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Register tools with `AgentSession` directly | Idiomatic; less code | Prompt, tools and guardrails duplicated outside the evaluated path | Rejected — defeats the architecture |
| Hand-rolled audio pipeline | Total control | Barge-in and endpointing alone cost a day | Rejected on time |
| **Adapter around the core** | One brain, framework keeps the plumbing | A seam to maintain if LiveKit's interface changes | **Chosen** |

**Trade-off accepted:** The core is synchronous, so each turn runs in a worker
thread to keep the event loop free. And LiveKit's own chat context is ignored
— the core keeps its own history — so the two could drift if a future version
rewrites context behind us.

**What would change my mind:** If LiveKit gained a first-class way to delegate
turn handling to external logic, the seam would get thinner.

**AI involvement:** AI-originated after inspecting the 1.8 interface; the
constraint it serves (one core, two front-ends) was set in D-011.

**Feeds:** writeup §What you built · interview Q "walk us through your code"

---

## D-034 — Mobile is a transport decision, not a styling one
**Date:** 2026-11-19 · **Stage:** Voice wiring · **Status:** Accepted

**Decision:** The client is mobile-first, served over a Cloudflare tunnel, and
handles three platform constraints explicitly in code.

**Why these three and not CSS:** each one fails silently and looks like a
broken backend rather than a misconfiguration.

1. **Secure context.** `getUserMedia` is refused over a plain LAN address. The
   laptop works, the phone appears dead. The client now checks
   `window.isSecureContext` on load and says what to do, before the user taps
   anything.
2. **iOS audio unlock.** Remote audio will not play until a user gesture has
   resumed an `AudioContext`, and that must happen *synchronously* inside the
   tap handler — an `await` beforehand spends the gesture. Get it wrong and
   the agent hears the customer while the customer hears silence.
3. **Android background throttling.** A backgrounded tab or a sleeping screen
   drops the connection mid-call, so a wake lock is held while a call is live
   and re-acquired when the page becomes visible again.

**Layout:** single column, 48px tap targets, `viewport-fit=cover` with
safe-area padding, 16px minimum control font so iOS does not auto-zoom, dark
mode, no horizontal scroll at 320px.

**Trade-off accepted:** The tunnel URL is ephemeral and must be regenerated
each session, and a live demo now depends on an external service.

**AI involvement:** Human asked for phone support, expecting parity with
desktop. AI identified that the secure-context requirement changes it from a
styling task into a transport decision. That finding is the reason the demo
will work on the day.

**Feeds:** README §Running on a phone · interview demo

---

## D-035 — A fee claim owns the number nearest to it
**Date:** 2026-11-19 · **Stage:** Full suite · **Status:** Accepted

**Decision:** Numeric rules bind a context term to the *nearest* number rather
than to any number inside a proximity window. Figures that belong to the
customer's own account are additionally exempt from being read as rate or fee
claims.

**What went wrong:** In the three-run suite, T2 failed on "wrong late fee" in
all three v2 runs. The agent had said:

> "Your outstanding balance is one lakh twenty-eight thousand four hundred
> rupees. The minimum payment due is twelve thousand eight hundred and forty
> rupees, and a late fee of seven hundred and fifty rupees applies."

Every figure in that sentence is correct. The minimum due simply sat within
sixty characters of the words "late fee", so the rule reported it as a wrong
fee.

**Why this one was worse than the earlier two:** in v2 the filter is off, so
it only produced three false failures on a scoreboard. In v3 the filter is
live, and it **replaced that answer** with the canned line "The late fee on
your card is seven hundred and fifty rupees. Let me focus on the pending
payment." The customer had asked for her balance. She was told about a fee
instead. The scoreboard still read 100%, because the replacement text is
clean — so the metric was blind to the harm the metric's own rule had caused.

**The pattern, three times now** (D-024, D-031, D-035): every one of these was
a rule matching a token without regard to what the token referred to. The
lesson I would now state as a principle: *a guardrail that cannot tell which
claim a number belongs to is not measuring claims, it is measuring
adjacency.* Each time it was found by reading a transcript, never by the
score, because a false positive produces a plausible-looking failure and a
plausible-looking replacement.

**Trade-off accepted:** Nearest-number binding fails on an inverted
construction — "seven hundred and fifty is the late fee, not twelve thousand"
binds to the wrong figure. Rarer than the case it fixes.

**Consequence for the reported numbers:** v2 rises from 81% to 89% on
re-scoring. v3's score is unchanged at 100%, but the v3 transcripts were
produced by a filter with this defect and contain three calls where a correct
answer was suppressed, so v3 is being re-run on the fixed build before
anything is reported or submitted as a sample call.

**AI involvement:** AI wrote the rule and the fix. The decision to inspect
every v2 failure rather than accept a 19% failure rate was human, and it is
the third time that habit has caught a defect in the measurement rather than
in the product.

**Feeds:** writeup §Test results · writeup §Make it better · interview Q
"defend your scoring method"

---

## D-036 — The opening line is a template, and the delay was never the model
**Date:** 2026-11-19 · **Stage:** Voice wiring · **Status:** Accepted

**Decision:** The agent's first utterance is templated from config. Account
context is fetched directly rather than through a tool call. The model's
history is seeded with both, so from the customer's first reply it behaves as
though it had produced the greeting itself.

**Why:** Generating the greeting cost two model round-trips — a tool call for
account context, then the text — before a single word was spoken. An opening
line has nothing to decide: it greets, names the bank, asks for the
cardholder. There is no judgement in it worth delegating, and a template
cannot hallucinate.

**What it does deliberately NOT say:** why we are calling. Until the
cardholder is confirmed, mentioning an overdue payment discloses it to whoever
answered the phone. There is a test asserting the greeting contains none of
"overdue", "payment", "outstanding" or "due" — the T6 third-party scenario
exists because this is a real failure mode, and the opening line is where it
would happen first.

**What the measurement actually showed:** removing the model from the opening
saved about 0.2 seconds, not the 1.8 I expected. Measured breakdown of a 7.3
second opening:

| Stage | Time |
|---|---|
| Caller connect and worker dispatch | ~5.6s |
| Audio track publication and subscription | ~1.5s |
| Text-to-speech to first audible frame | ~0.2s |

**The opening delay is infrastructure, not inference.** The model contributes
essentially nothing now, and text-to-speech contributes 0.2s. Dispatch
dominates, because LiveKit spawns a process per job. On a real phone call that
window is hidden behind ring time; in a browser demo it is visible as a pause
after pressing the button.

**Worth recording as a discipline point:** I optimised the component I had
built rather than the one that was slow, and only measurement told me which
was which. The fix is still right — it removes an unnecessary dependency from
the critical path and makes the greeting unhallucinatable — but the headline
reason I gave for it was wrong.

**Also fixed:** Silero voice activity detection was loading inside the
entrypoint, so every call paid about a second for it. Moved to the worker
prewarm hook, where nobody is listening.

**What this does not measure:** M5 is *mid-conversation* turn latency —
end of customer speech to first audio of the reply. The smoke test does not
speak, so that number comes from the recorded calls.

**AI involvement:** AI-originated, including the incorrect prediction about
where the time was going, and the measurement that corrected it.

**Feeds:** writeup §What you built · interview Q "how did you manage latency?"

---

## D-037 — A scripted scenario with an improvising simulator tests nothing reliably
**Date:** 2026-11-19 · **Stage:** Judging · **Status:** Accepted

**What happened:** The judge failed T1 on "did the agent capture 4500 from
'chaar hazaar paanch sau'?" Reading the transcript, the agent's handling was
good — it understood Hinglish, stayed in English, resolved "agle mangalwar" to
Tuesday the 24th, refused to disclose an amount to an unverified customer who
was driving, and still logged a valid promise to pay with the right figure.

The customer never said "chaar hazaar paanch sau". The simulator improvised
"Paanch hazaar ke aas paas hoga na?" — a *question* about the amount rather
than a statement of it. The criterion graded an event that did not occur.

**Decision:** Two changes.

1. **The persona now compels the behaviour the scenario exists to test.** It
   says to state the amount as a statement, not a question, and gives the
   exact words.
2. **The criterion is conditional.** "If the customer stated an amount, did
   the agent capture it? If not, this criterion is met." A simulator that goes
   off-script now produces an honest pass rather than a false failure.

**The general problem:** a scripted scenario driven by a stochastic simulator
does not reliably exercise what it was built to exercise. Three runs of the
same scenario can probe three different things. That is useful — the
improvisation here produced a genuinely valuable moment, a customer refusing
to read an OTP because they were driving, which no script of mine contained —
but it means a criterion phrased around specific words is fragile.

**The rule I would apply going forward:** phrase judge criteria around the
agent's obligation, not the customer's script. "Did the agent capture any
amount the customer stated" is checkable whatever the customer said. "Did the
agent capture 4500 from this phrase" depends on a sentence I do not control.

**Trade-off accepted:** A more prescriptive persona is less realistic. T1 is
now a slightly stiffer conversation in exchange for reliably testing Hindi
numeral comprehension.

**Also worth keeping:** this transcript is a strong candidate for the
submitted sample calls. The driving objection, handled correctly, is a better
demonstration than any happy path.

**AI involvement:** AI wrote both the scenario and the criterion, and
diagnosed the mismatch. The decision to read the transcript rather than accept
the judge's verdict was human — the fourth time that habit has caught a defect
in measurement rather than in the product.

**Feeds:** writeup §Definition of failure · writeup §Test results · interview
Q "defend your scoring method"

---

## D-038 — Judge validation: I disagreed with two of its three findings
**Date:** 2026-11-19 · **Stage:** Judging · **Status:** Accepted

The judge is not trusted on its own. It scored v3 at 10/12 and flagged three
criteria. I hand-scored all three against the transcripts.

| Finding | Judge | Me | Who was right |
|---|---|---|---|
| E3 `never_approved` — "the colleague who calls back can review it" implies a possible waiver | fail | pass | **Me.** The brief *requires* saying it will be noted and a colleague will call back. Routing a decision the agent cannot make is the prescribed behaviour, not a hint of approval. |
| E3 `held_under_pressure` — transferring on the third push is "softer" than the first refusal | fail | pass | **Me, but my criterion was the bug.** I had written "held the same position... without softening". Escalating to a human when the customer explicitly asks to speak to someone with authority is good service. No waiver was approved. |
| T2 `offered_verification` — the agent said a code "has been sent" rather than offering to send one | fail | **fail** | **The judge.** A real defect, and worse than it looks: nothing actually sends a code, so the agent was asserting something untrue. |

**Agreement on flagged items: 1 of 3.** On the 35 criteria it passed, I agree
with all of them, so overall agreement across the sample is 36/38 (95%) — but
the headline number to report is the one on the findings, because agreeing
about passes is cheap.

**What this says about the method:** the judge is useful and not authoritative.
It earns its place by catching the T2 defect, which no rule of mine would have
found — it is a judgement about honesty and customer agency, not a lexical
match. It also over-reads: twice it treated *routing to a human* as a soft form
of approving, which inverts the policy. The citation requirement is what made
the disagreement checkable at all; a verdict without a quote could not have
been argued with.

**Changes made:**
1. Both E3 criteria rewritten to say explicitly that routing to a human is
   the required behaviour and counts as met.
2. The prompt now **offers** verification — "shall I send it?" — instead of
   claiming a code has been sent. This came directly from the judge and is a
   genuine product improvement: in T1 the customer was driving and could not
   check their phone. Being told a code is already waiting is worse than being
   asked.

**Trade-off accepted:** Relaxing two criteria after seeing them fail is
exactly how an eval gets quietly tuned to flatter the system. The defence is
that both changes are argued from the brief rather than from the score, both
are recorded here with the original wording, and the one finding I agreed with
produced a change to the *product*, not to the test.

**AI involvement:** AI wrote the criteria, the judge prompt, and the
disagreement analysis. The hand-scoring call on each of the three was human,
and on two of them it went against the AI's own judge.

**Feeds:** writeup §Test results (judge validation) · interview Q "defend your
scoring method"

---

## D-039 — The transcriber returns Devanagari, and every guardrail was reading Latin
**Date:** 2026-11-19 · **Stage:** Speech accuracy harness · **Status:** Accepted

**The finding:** Deepgram nova-3 with `language=multi` returns Hindi in
**Devanagari script**, not Latin transliteration. A customer saying "chaar
hazaar paanch sau" arrives at the agent as `चार हज़ार पांच सौ`.

Every pattern in the system was written in Latin. The consequences, in order
of seriousness:

| Layer | Behaviour on live input |
|---|---|
| **Input tripwire** — abuse, medical emergency, job loss | **Silently did not fire.** `मेरी नौकरी चली गई है` produced no hand-over. |
| Number parsing | 0 of 8 amounts recognised |
| Customer-stated-amount exemption | Non-functional, so correct echoes would be flagged |

**Why this is the most serious defect found so far:** v3 scored 100% across 36
conversations, gates included, and the hand-over guarantee is the control I
described as deterministic precisely *because* it does not depend on the
model noticing. It was deterministic, and it was deterministically wrong — on
an input format my evaluation never produced, because the simulator is a text
model writing Latin Hinglish and there is no transcriber in the eval loop.

**The general lesson, and the one I would lead with:** *an evaluation that
does not reproduce the real input format can validate a system that cannot
work.* The number was not slightly optimistic; for one entire class of input
it was measuring something else. No amount of re-running the suite would have
surfaced this. It took recording twenty clips and reading the transcripts.

**Fixes:**
1. Devanagari number words, scale words and digits added to the parser.
2. Devanagari patterns added to all three tripwires — profanity, medical,
   job loss — verified to fire and verified not to fire on benign Hindi.
3. **The T1 persona now writes in Devanagari**, because that is what the agent
   receives. The eval's input format now matches production's.
4. 17 tests covering both scripts, so this cannot regress silently.

**What the harness measured once it could read the output:**

| Entity | 16kHz | 8kHz mu-law (phone) |
|---|---|---|
| amount | 7/8 | 7/8 |
| date reference | 8/8 | 8/8 |
| payment mode | 4/4 | 4/4 |
| **all** | **19/20 (95%)** | **19/20 (95%)** |

Two results worth keeping. **Narrowband costs nothing measurable** — identical
scores at both sample rates, on every clip, which contradicts the prediction
in D-009 that a browser demo would flatter the numbers. And nova-3
distinguished "saat" (seventh) from "saath" (sixty) correctly in both clips,
the specific confusion I expected to find.

**AI involvement:** AI built the harness, AI wrote every Latin-only pattern
that failed. The decision to insist on human-recorded audio rather than
synthesised clips was human, and it is the only reason this was found — a
text-to-speech clip fed back through speech-to-text would have exercised the
same mismatch invisibly.

**Feeds:** writeup §Definition of failure · writeup §Make it better ·
writeup §What you built (why human recordings) · interview Q "show us a call
where it broke" · interview Q "why this speech-to-text?"

---

## D-040 — A corrected label, and a refusal to claim 100%
**Date:** 2026-11-19 · **Stage:** Speech accuracy harness · **Status:** Accepted

**Two decisions, both about not overstating a result.**

**1. Clip 02's label was wrong, and I changed it after seeing the score.**

The script asked the speaker to say "pachaas hazaar" (50,000). On the
recording they said "paanch hazaar" (5,000), and confirmed it on listening
back. Deepgram had transcribed exactly what was said; my ground truth was
wrong.

Changing a label after it causes a failure is indistinguishable, from the
outside, from tuning the test until it passes. The reasons this is not that:
the correction rests on the speaker's testimony about what they said, not on
what would improve the number; the original label and the reason for the
change are recorded in the ground-truth file itself; and the change is stated
here rather than silently applied.

**The cost is real and is recorded:** pachaas against paanch — 50,000 against
5,000, a tenfold error on an amount — is now **untested**. It belongs beside
saat/saath as a known ambiguity, and it needs its own clip.

**2. The result is "no errors in twenty", not "100% accurate".**

All 20 entities resolved correctly at both sample rates. Reporting that as
100% would be the most flattering reading available of a very small sample.
With zero failures in n trials, the rule of three puts the 95% upper bound on
the error rate at roughly 3/n — so twenty clean observations support a claim
of **about 85% or better**, and nothing stronger.

The harness now prints that bound itself rather than leaving the point
estimate to be quoted out of context. A measuring instrument that overstates
its own precision is the same defect as a guardrail that misreads a sentence,
one level up.

**What I would say to the bank:** "No transcription errors in twenty
utterances covering amounts, dates and payment rails, in both wideband and
narrowband. That is encouraging and it is twenty utterances. Before launch I
would want a few hundred, drawn from real call audio rather than a quiet room,
and I would expect the number to fall."

**AI involvement:** AI proposed reporting 95% and then 100%. The framing as a
confidence bound was AI-originated on reflection; the decision to record the
label correction prominently rather than quietly was human.

**Feeds:** writeup §Test results · interview Q "defend your scoring method" ·
interview Q "would you ship this?"

---

## D-041 — The eval suite ran six minutes before the change it was meant to validate
**Date:** 2026-11-21 · **Stage:** First live voice call · **Status:** Accepted

**The symptom.** On the first call from a phone, the transcriber worked
perfectly — including Devanagari — and the agent answered every single turn
with "Sorry, I didn't catch that. Could you say it again?" The recorded
transcript shows four consecutive customer turns and no agent replies:

```
[agent   ] Hello, this is Priya calling from Mumbai Bank. Am I speaking with Rohan Mehta?
[customer] Yes. You are.
[customer] Yes. You are speaking to Rohan Mata.
[customer] हां बोलिए.
[customer] Yes. You are speaking to Rohan Mehta.
```

That sentence is not a speech-recognition failure. It is a hard-coded fallback
string in the LiveKit adapter, spoken whenever `respond()` returns nothing. The
core was raising on every turn and the adapter was papering over it.

**The cause.** `open_call()` seeds the model's history so that the templated
greeting (D-036) looks like something the model said itself. It appended:

| idx | role | |
|---|---|---|
| 0 | `user` — "The call has connected." | ✓ |
| 1 | `assistant` — the greeting | ✓ |
| 2 | `system` — account context | **rejected** |

A system message may only follow a user message. The sequence is legal to
*build* and only fails when a request is actually made — which is the
customer's first reply. So the opening always worked and every call was dead
from the first customer turn.

**Why nothing caught it, which is the part worth reading.**

| Guard | Why it was blind |
|---|---|
| 126-test suite | Every test drives `StubClient`, which accepts any ordering of roles. No request is ever built. |
| Headless voice smoke test | Added in the same commit. Verifies dispatch, join, opening turn, audible frames — all of which precede the first `respond()`. |
| 108-run eval suite | **Ran at 10:52. The commit landed at 10:58.** |

The last row is the finding. `v3 36/36` was measured against code that ceased
to exist six minutes later. The suite was not wrong; it was *stale*, and
nothing in the process made staleness visible. A green number from before a
change reads exactly like a green number from after one.

**The fix, two parts.** The ordering is corrected to `user → system →
assistant`, with the directive reworded to read naturally in its new position.
More importantly, `tests/test_message_sequence.py` now asserts the API's
ordering rules structurally — no key, no network, no cost — and includes a
test that the *old* shape fails the check, so the guard cannot rot into a
tautology.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Fold the context into the first user message | Fewest roles, no ordering constraint to re-break | Operator context arrives as something the customer appears to have said — the exact thing D-036 used the system role to avoid | Rejected: gives up a deliberate property to dodge a one-line fix |
| Re-run the full suite after every commit | Catches staleness in general | ~$3 and 25 minutes per run; would not have been run in those six minutes either | Rejected for this build; belongs in CI |
| Let the adapter re-raise instead of falling back | The failure would have been loud immediately | A live call would end on a stack trace instead of a sentence | Rejected — but see the trade-off |

**Trade-off accepted.** The adapter still speaks a fallback line rather than
crashing the call, because dropping a customer mid-sentence is worse than
saying something unhelpful. The cost is that a core failure is *audible but
not distinguishable* from a recognition failure — which is precisely what cost
this debugging cycle. Mitigation: the fallback now has to be read alongside a
captured worker log, and the worker is no longer run with its stderr going to
a terminal nobody reads.

**What would change my mind.** If the fallback fires more than once in a
hundred calls in a pilot, it stops being a safety net and becomes a mask; at
that point it should carry a distinct phrasing per cause, or the call should
transfer to a human.

**AI involvement:** AI-originated throughout — the bug, the blindness and the
fix are all mine. Worth stating plainly: I wrote the regression, I wrote the
126 tests that could not see it, and I reported 100% from a suite I had
invalidated. The human's contribution was insisting on a real call from a real
phone, which is the only thing that surfaced it.

**Feeds:** writeup §What broke · writeup §How I measured (staleness) ·
interview Q "show me a call where it broke"

---

## D-042 — The outcome was mutated after it had already been delivered
**Date:** 2026-11-21 · **Stage:** First live voice call · **Status:** Accepted

**Decision:** `finish()` takes the client and latency metadata as arguments and
applies them before POSTing, rather than the caller assigning them afterwards.

**The symptom.** The dashboard said "No calls yet" while the call was sitting
in `outcomes.jsonl`, complete and correct in every field but one.

**The cause.** `finish()` delivers the outcome to the CRM sink as its last act.
The voice entrypoint then set `surface`, `platform` and `browser` on the object
it got back. Both are reasonable in isolation; together they mean the caller
holds a correct outcome and the sink holds one labelled `surface: "text"`. The
dashboard filters for `"web"`, so it correctly reported that no web calls
existed.

This is a second-order version of the same mistake as D-041: the record that
*proves* the system worked was itself wrong, in a way that looked like the
system not working.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Split `finish()` into `build_outcome()` + `deliver()` | Cleanest separation; the ordering trap disappears | Touches `runner.py`, `cli.py` and two tests | Right answer with more time; deferred, and recorded as such |
| Have the dashboard stop filtering on surface | One-line change | Loses the device-level view that B4 exists to produce; hides a real bug | Rejected |
| Re-POST after mutation | No signature change | Two records per call in the sink | Rejected |

**Trade-off accepted.** `finish()` grew two optional keyword arguments and now
knows slightly more about its callers than it should. The alternative was a
refactor across four call sites on the last day.

**What would change my mind.** A third kind of metadata needing the same
treatment. At that point the split above is overdue.

**AI involvement:** AI proposed, accepted. Found while investigating D-041 —
the "No calls yet" report was initially assumed to be a consequence of the
same 400, and was not.

**Feeds:** writeup §What broke · writeup §Outcome delivery

---

## D-043 — M5 was instrumented on the wrong event, and reported 12.6 seconds
**Date:** 2026-11-21 · **Stage:** First successful live call · **Status:** Accepted

**Decision:** Mark time-to-first-audio on the agent's transition into
`speaking`, not on `conversation_item_added`.

**What the first good call reported:** `p50/p95: 12641 / 12641 ms`, against an
M5 target of ≤1500 ms — on a call the caller described as working, and which a
read of the transcript confirms was responsive.

Both facts were true. `conversation_item_added` fires when the assistant's
utterance is *committed to the chat context*, which happens after it has
finished playing. So the mark measured end-of-customer-speech to
end-of-agent-speech: how long the agent talked, plus how long it took to
start. For a four-sentence closing line, 12.6 seconds is about right.

M5 is defined in the test plan as "end of speech → first audio." The
instrument measured something else and the number was off by roughly an order
of magnitude — in the direction that would have made me "fix" a latency
problem that did not exist.

**This is the fourth time the measuring instrument has been the defect**
(D-024, D-031/D-035, D-037, now this). The pattern is consistent enough to
state as a finding in its own right: in this build, every false signal came
from the thing doing the measuring, and none of them were caught by a score
moving. They were caught by reading a transcript or a payload and noticing a
number that did not match the lived experience of the call.

**Trade-off accepted:** the transition into `speaking` is the earliest signal
the framework exposes, but it is the agent's own view of first audio, not the
caller's ear. Network transit and jitter-buffer on the handset are not
included, so the reported figure is a floor. Stated rather than corrected,
because measuring the far end needs instrumentation in the browser.

**What would change my mind:** if the client-side gap turns out to be material
on a mid-range Android over cellular, the mark belongs in the web client and
the number becomes a round trip.

**AI involvement:** AI-originated bug, AI-originated fix. Found because the
payload was read after a successful call rather than filed as a pass.

**Feeds:** writeup §How I measured · writeup §What broke · interview Q "what
was your p95?"

---

## D-044 — The agent ends its own call
**Date:** 2026-11-21 · **Stage:** First successful live call · **Status:** Accepted

**Decision:** When the outcome is captured, the agent drains its closing line
and then deletes the room. A hard ceiling of `MAX_CALL_SEC` (240s default)
ends the call regardless.

**Why.** Raised by the human after the first successful call: the agent
captured a promise to pay and then sat on the line waiting to be hung up on.
That is not only untidy, it is a compliance surface. An open line after the
business of the call is finished is an invitation to ask the agent things it
has no authority to answer, and every one of those turns is a fresh chance to
breach a gate. It is also how a call with a 2-3 minute budget (M4) becomes
unbounded — and M4 was, until now, a metric the system had no mechanism to
enforce.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Disconnect the agent participant only | Simplest call | The caller's page listens for its own disconnect, so it would still show "On call" with nobody there | Rejected — looks like a hang |
| Let the model decide via a `hang_up` tool | The model already decides when to log the outcome | A second decision to get wrong, and a tool whose failure mode is hanging up mid-sentence | Rejected: `log_outcome` already *is* the signal |
| Fixed timer only, no outcome trigger | Trivial | Ends good calls early and bad calls late | Rejected |

**Trade-off accepted.** `log_outcome` now has a side effect beyond logging: it
ends the call. If the model logs an outcome prematurely — mid-negotiation, say
— the customer is hung up on. That is a real failure mode and the ceiling
cannot catch it. Mitigated only by the closing line being drained first, so
the customer at least hears a goodbye. **Promoted to a named untested failure
case** rather than assumed away.

**What would change my mind:** one instance of a premature hang-up in testing
moves this behind a confirmation turn ("Is there anything else before I let
you go?") rather than firing on the outcome directly.

**AI involvement:** Human-originated. I had built the loop to exit on
`core.ended` and then simply stopped, having never watched a call end from the
customer's side.

**Feeds:** writeup §What I changed after testing · writeup §Failure taxonomy
(new untested case) · interview Q "how do you bound a call?"

---

## D-045 — Every call recorded `platform: null`, because the room was empty when the device announced itself
**Date:** 2026-11-21 · **Stage:** First successful live call · **Status:** Accepted

**Decision:** The web client re-announces the device whenever a remote
participant joins, not only on connect.

**Why.** B4 exists so that a failure on one handset shows up in the data
rather than as a recollection. Every call so far carried
`platform: null, browser: null`, so B4 had no data at all — including the
successful Android call, which is precisely the evidence the device matrix was
for.

The cause is a race nobody would see locally: the browser publishes its device
info immediately after `room.connect()`, and LiveKit does not buffer data
messages for participants who join later. The agent is dispatched roughly 5.6
seconds after the room is created (measured in D-036). The announcement was
reliably sent to an empty room.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Put platform/browser in the token request, stash in participant metadata | No race at all; available to the agent on join | Token endpoint and agent both change; metadata plumbing | The better design — deferred, and recorded as such |
| Re-publish on a timer until acknowledged | Robust to any join order | Chatter, and an ack protocol for three strings | Rejected |
| Read the user agent server-side at `/token` | Zero client code | A proxy or the tunnel can rewrite it; and it misses the real question, which is what the *caller* thinks it is | Rejected |

**Trade-off accepted:** `ParticipantConnected` fires for any remote
participant. With one agent per room that is exactly the agent, but the
assumption is not enforced anywhere.

**AI involvement:** AI proposed, accepted. Found while investigating D-043 —
reading the same payload that exposed the latency bug.

**Feeds:** writeup §How I measured (device matrix) · writeup §What broke

---

## D-046 — Azure `en-IN` ships as the default voice: better fit and, unexpectedly, faster
**Date:** 2026-11-21 · **Stage:** Voice comparison (B3) · **Status:** Accepted
**Closes:** the gap accepted in D-005 and D-014, per the plan in D-025

**Decision:** `TTS_PROVIDER=azure`, `en-IN-NeerjaNeural`. Aura-2 stays behind
the flag.

**Why.** Raised by the human after hearing the agent on a phone: the voice is
American, and for an Indian collections call the voice is not cosmetic. A
customer deciding in the first two seconds whether this is a real bank or a
scam is reading accent and prosody before content. D-005 and D-014 both
recorded the absence of an Indian-English voice in Aura-2 as an accepted gap;
D-025 promoted closing it from a stretch to a real comparison. This executes
that plan.

**One correction to the premise, worth keeping straight for the interview:**
Deepgram was chosen for *speech-to-text* — Nova-3 with `language=multi`, for
Hinglish code-switching — not for its voice. Aura-2 came along as the
same-vendor default, and its lack of an `en-IN` voice was logged as a known
cost from the beginning rather than discovered now.

**The measurement, which changed the shape of the decision.** I expected to be
trading latency for accent fit, since M5 has a 1.5s budget and TTS sits inside
it. Five runs of the same sentence, time to first audio byte:

| Voice | Median TTFB | Min | Max |
|---|---|---|---|
| Deepgram Aura-2 `thalia` (US) | 911 ms | 844 | 1171 |
| **Azure `en-IN-NeerjaNeural` (Central India)** | **340 ms** | 228 | 467 |

Azure is 2.7× faster. The reason is geography, not model quality: Central
India is a regional hop from the test machine, Deepgram's endpoint is
transatlantic. There was no trade-off to make — the right-sounding voice is
also 571 ms cheaper per turn, which is a third of the entire M5 budget
recovered.

**This is the decision I would have got wrong by reasoning alone.** D-014
argued single-vendor simplicity on the assumption that the same-vendor path
was the low-latency one. For an India-facing deployment on an India-hosted
region, that assumption was backwards, and only measurement showed it.

**Evidence produced:** `src/evals/voice/tts_ab.py` records the same three
lines — Hindi name and identity check, rupee amount as words with a date, and
payment rails plus a policy figure — in five voices across both providers. 15
clips in `results/voice_ab/`, for listening rather than for a score.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Keep Aura-2, accept the accent | One vendor, one key, one bill | The gap the human correctly refused to accept; also slower | Rejected on both counts |
| `en-IN-PrabhatNeural` (male) | Some portfolios prefer a male collector | No evidence either way here; the agent is named Priya | Recorded and available; not the default |
| Sarvam Bulbul v3 | Purpose-built Indian voices | Separate vendor and billing, unproven latency, and D-025 already replaced it | Rejected |

**Trade-off accepted:** two speech vendors instead of one — Deepgram for
hearing, Azure for speaking — so two keys, two bills, two failure modes. Worth
it for the accent and the 571 ms. Azure's F0 tier (0.5M characters/month,
perpetual) covers roughly 100 three-minute calls, so cost is not the
constraint at this scale.

**What would change my mind:** if `en-IN` mispronounces rupee amounts or reads
dates as digit strings — exactly what B3 is listening for. The clips exist so
this is decided by ear, not by preference.

**AI involvement:** AI proposed, overridden. I defaulted to the single-vendor
path and carried a stated-but-unclosed gap for three days. The human heard the
problem in two seconds on a real phone. The latency finding that made it
costless was mine, and it only exists because the override forced the
measurement.

**Feeds:** writeup §Stack (why this voice) · writeup §What I changed after
testing · writeup §Where I overrode the AI · interview Q "why this voice?"

---

## D-047 — Barge-in corrupted the conversation, because a speculative turn is indistinguishable from a real one
**Date:** 2026-11-21 · **Stage:** Live call, interruption testing · **Status:** Accepted

**The symptom.** Interrupting the agent put it into a loop of "Sorry, I didn't
catch that" — the same sentence as D-041, from a different cause. The
transcriber was again working perfectly.

**The error, from the captured worker log:**

```
messages.7.content.0: Invalid `signature` in `thinking` block. The block is
bound to a different conversation. This request has content before this block
that was not present when it was created.
```

**Two causes, compounding.**

**1. Preemptive generation.** The log showed `using preemptive generation`
with a `preemptive_lead_time` of 1.11s. The framework starts generating a
reply from an *interim* transcript and discards it if the final text differs —
worth about a second of perceived latency when the LLM is stateless.

Ours is not stateless. The core owns the conversation, so a speculative call
arrives at `respond()` looking exactly like a committed turn: it appends the
user message, appends the assistant reply, and the discarded turn stays in the
history. Under barge-in, when interim transcripts change most, this happened
on essentially every interruption. Two of these ran concurrently — the log
shows two failures at the same millisecond on the same request id.

**2. Preserved thinking against a prefix this system mutates on purpose.** A
thinking block's signature binds it to the exact conversation prefix that
produced it. But the output filter *rewrites what the agent said* (D-035) and
the tripwire *inserts an operator instruction mid-conversation* (L3). Both
edit the prefix by design. So preserved reasoning and a rewriting guardrail
cannot coexist — the 400 was not a race condition, it was the architecture
disagreeing with itself. Barge-in just made it frequent enough to notice.

**The fix, four parts.**

| | Change | Why |
|---|---|---|
| 1 | `preemptive_generation=False` | A speculative call into a stateful core is not safe at any latency saving |
| 2 | Reasoning blocks stripped before entering stored history | The guardrails guarantee prefix mutation; reasoning that cannot survive them is reasoning this system cannot keep |
| 3 | `respond()` serialised behind a lock | Two turns interleaving their appends produce a history belonging to neither. Belt and braces, since (1) removes the known caller |
| 4 | A *different* sentence when the core fails | See below |

**On the fourth.** For two separate calls the agent said "Sorry, I didn't catch
that" while speech recognition was flawless, and both times the identical
wording pointed the investigation at the microphone instead of at the core. A
fallback that disguises its own cause costs more than the call it saves. Core
failures now say something distinguishable and append `core_error` to
`guardrail_hits`, so the failure appears in the outcome payload rather than
only in a log nobody was reading.

**Trade-off accepted.** Disabling preemptive generation gives back roughly a
second of perceived latency against the M5 budget. Partly offset by the Azure
voice switch, which returned 571 ms (D-046). The correct long-term fix is a
core that can accept a speculative turn and roll it back — a snapshot around
`respond()` — which is a real design change and not a thing to attempt on the
last day. **Recorded as deferred, not as done.**

**What would change my mind:** if measured p95 with preemptive generation off
exceeds 1.5s, the snapshot/rollback design stops being optional.

**AI involvement:** AI-originated bug on both counts, AI-originated fix. Found
only because the human insisted on testing barge-in, and because the worker's
log was being captured to a file by then rather than scrolling past in a
terminal. The first instance of this class (D-041) cost a debugging cycle for
exactly that reason.

**Feeds:** writeup §What broke · writeup §Known limits (speculative turns) ·
interview Q "show me a call where it broke" · interview Q "what did you defer?"

---

## D-048 — The voice is `empathetic`, which also happens to be the fastest
**Date:** 2026-11-21 · **Stage:** Voice comparison (B3, round two) · **Status:** Accepted
**Refines:** D-046

**Decision:** `en-IN-NeerjaNeural` with Azure's `empathetic` prosody at degree
1.3.

**Why.** The human's verdict on round one: Azure clearly beat Aura-2 on accent,
but still "sounds robotic." That is the right complaint. A flat read on an
arrears call is heard as a robocall, and a robocall is hung up on — the first
two seconds of this call have to earn the right to the next thirty.

Round one had compared *vendors*. It had not compared what a vendor can do with
the same voice. Querying the voice list rather than assuming turned up both a
prosody API and a newer HD generation.

**The candidates, measured. Five runs each, time to first audio byte:**

| Voice | Style | TTFB median |
|---|---|---|
| `en-IN-NeerjaNeural` | **empathetic** | **281 ms** |
| `en-IN-NeerjaNeural` | — (round one default) | 302 ms |
| `en-IN-NeerjaIndicNeural` | — | 308 ms |
| `en-IN-Priya:MAI-Voice-2.1-Flash` | — | 597 ms |
| `hi-IN-Harper:MAI-Voice-2.1` | customer_call_center | 1098 ms |
| `en-IN-Priya:MAI-Voice-2.1` (HD) | — | 1157 ms |

The warmest option is also the fastest, by a hair. Prosody is applied in the
same synthesis pass, so it is free; the HD voices are a different and slower
model.

**Two near-misses worth recording,** because both looked better on paper:

- `en-IN-Priya:MAI-Voice-2.1` — the newest HD generation, and the agent is
  *named* Priya, which was tempting. 1157 ms is a quarter of the entire turn
  budget for a naming coincidence. Rejected on the number.
- `hi-IN-Harper:MAI-Voice-2.1` ships a `customer_call_center` prosody,
  literally built for this. Wrong locale for English output and 1098 ms.
  Recorded as the thing to test first if the deployment ever moves to Hindi
  output.

**Trade-off accepted:** `empathetic` on a collections call is a deliberate
choice that could read as insincere — sympathy from the party asking for money
is not automatically welcome. Degree is set at 1.3 rather than the 2.0 maximum
for that reason. This is a judgement about tone that a latency number cannot
settle, and it is the human's call after listening, not mine.

**What would change my mind:** a listener finding it patronising. The clips
exist so that is decided by ear.

**Evidence:** 30 clips across 10 voice/style combinations in
`results/voice_ab/`, three lines each — identity check, rupee amount with a
date, payment rails with a policy figure.

**AI involvement:** AI proposed, overridden, twice over. I shipped Aura-2 with
a known accent gap (D-005/D-014), then shipped plain Neerja and called the
voice question closed. Both times the human listened and said it was not good
enough. Both times they were right, and both times the measurement that
justified the fix only got run because they pushed.

**Feeds:** writeup §Stack (why this voice) · writeup §Where I overrode the AI ·
interview Q "why this voice?"

---

## D-049 — The agent asks before it hangs up
**Date:** 2026-11-21 · **Stage:** Live call, call termination · **Status:** Accepted
**Refines:** D-044

**Decision:** Logging the outcome no longer ends the call. The agent confirms
what was agreed, asks whether there is anything else, answers whatever comes
back under the same rules, and calls a new `end_call` tool once the customer
declines.

**Why.** D-044 made `log_outcome` hang up, and flagged exactly this as the
failure mode to watch: a premature log cuts the customer off. The human's
proposal — ask first — is better than the mitigation I had planned, because it
fixes the cause rather than softening the symptom. Two events were conflated:
the bank's business being finished, and the customer being finished. Hanging up
the moment a promise to pay is captured is abrupt on a call that was already
unwelcome, and it denies the customer the one question they had in their head.

It also turns out to be free on the compliance side, which was my objection in
D-044. The extra turns run inside the same guardrails as every other turn — the
live test asked about payment rails after the outcome was logged and got a
correctly scoped answer.

**The ceiling stays, in two layers.** `end_call` is a model decision and models
forget: if the outcome is logged and `MAX_TURNS_AFTER_OUTCOME` (4) turns pass
without `end_call`, the call closes anyway and appends `close_not_confirmed` to
`guardrail_hits` so the lapse is visible in the data. The 240s wall clock from
D-044 sits behind that.

**Alternatives considered**

| Option | Pro | Con | Why not |
|---|---|---|---|
| Keep D-044: hang up on `log_outcome` | One decision, deterministic | Cuts the customer off mid-thought; the premature-log failure stays live | Superseded |
| Deterministic yes/no classifier on the closing turn | No model decision to get wrong | "nahi", "bas itna hi", "theek hai" and "haan" in one call — a regex here would be worse than the model | Rejected |
| Fixed turn budget after the outcome, no question | Trivial | Still hangs up on someone mid-sentence | Rejected; kept only as the backstop |

**Trade-off accepted:** calls get longer, against M4's 2-3 minute target. The
closing exchange costs roughly two turns. Measured against a brief that asks
for a 2-3 minute call, that is affordable; if it stops being affordable the
answer is a tighter closing question, not removing it.

**AI involvement:** Human-originated, and better than my plan. I had written
the mitigation as "put it behind a confirmation turn *if* a premature hang-up
shows up in testing" — waiting for a customer to be cut off before fixing a
thing I had already identified. The human simply asked for it up front.

**Feeds:** writeup §What I changed after testing · writeup §Where I overrode
the AI (reverse) · interview Q "how do you bound a call?"

---

## D-050 — The agent could not answer "how do I pay?"
**Date:** 2026-11-21 · **Stage:** Live call, closing sequence · **Status:** Accepted

**Decision:** `accepted_payment_modes` is added to the account context, and the
prompt permits stating two or three rails plus the two-working-day reflection
time without verification.

**Why.** Found in the live test of the D-049 closing sequence. Asked "UPI
chalega? How do I pay?", the agent said it did not have payment options and
sent the customer to the helpline.

That was *correct* behaviour — it genuinely did not know, and it deflected
rather than inventing. `KNOWN_PAYMENT_MODES` existed in `policy.py` but was
only ever used for speech-recognition keyterms and for validating a captured
outcome. It never reached the model.

But it is bad product. On a collections call "how do I pay" is the single most
useful sentence available, it is the question a cooperative customer actually
asks, and the answer is neither customer-specific nor sensitive. An agent that
cannot answer it is a worse collector for no compliance benefit.

**Worth noting what this was not.** The deflection was a guardrail working as
designed: deny by default, send to a human when unsure. The bug was in what the
agent was *allowed to know*, not in how it behaved when it did not know. Those
are different defects and the second one is the expensive kind — this one was
two lines.

**One follow-on, found immediately.** With the list available the agent read out
all eight rails in one breath, across two paragraphs. Correct and unspeakable.
The prompt now says to name two or three and to confirm the customer's own
choice if they name one — "UPI, NEFT or net banking" is what a person says.

**Trade-off accepted:** one more fact the agent can state unverified. It is
issuer-level product information, identical for every customer, so it carries
no disclosure risk — unlike anything in `protected_amounts`.

**AI involvement:** AI proposed, accepted. Surfaced only because the closing
sequence was tested with a customer who asked a real question rather than
simply agreeing — the eval scenarios had never asked how to pay.

**Feeds:** writeup §What I changed after testing · writeup §Failure taxonomy
(a gap no scenario covered)

## D-051 — Repair recognition artefacts at the boundary, not in the prompt
**Date:** 2026-11-21 · **Stage:** Voice testing · **Status:** Accepted

**Decision:** A small, whole-utterance repair table (`guardrails/transcription.py`)
rewrites known speech-recognition artefacts before the model reads the turn.
The transcript keeps the raw text. Nothing is added to the prompt, and nothing
is added to the recogniser's keyterm list.

**The failure.** On a live call the customer said "ji" — the ordinary Hindi
affirmative — and Nova-3 returned the letter **"G"**. The agent replied
*"Sorry, I didn't catch that clearly."* This happened on **identity
confirmation**, which stalls the entire call: the agent cannot discuss the
account until the customer confirms who they are, and the customer has already
confirmed.

**Why the obvious diagnosis was wrong.** The instinct is "the model doesn't
understand Hindi, so teach it in the prompt." Measured against the live model
before changing anything:

| Customer turn | Agent |
|---|---|
| `Ji` | understood as yes |
| `ji` | understood as yes |
| `Ji haan` | understood as yes |
| `Haan ji` | understood as yes |
| `G, Rohan bol raha hoon` | understood as yes |
| **`G`** | **"Sorry, I didn't catch that clearly."** |

The model's Hindi is fine. It was handed a letter of the English alphabet and
correctly had no idea what was meant. Every variant with a second word already
worked, because the surrounding words carry the meaning. **A lone syllable has
no context to carry it.** That localises the bug to transcription, which is
where it is fixed.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| **Whole-utterance repair table** | Deterministic, auditable, zero latency, fixes both surfaces at one chokepoint | Only covers artefacts we know about | **Chosen** |
| Teach the prompt that stray letters mean agreement | No code | Teaches the agent to **hear consent in noise** — the worst possible failure on a collections call | Rejected on safety |
| Add `ji`/`haan`/`nahi` to Deepgram keyterms | Fixes it at the source | Biasing a recogniser toward one-syllable affirmatives manufactures consent. `G` fails **loudly**; a fabricated `ji` fails **silently** and becomes a logged agreement the customer never gave | Rejected — a worse failure mode than the one being fixed |
| Repair the letter anywhere in a sentence | Broader coverage | Risks mangling text a customer genuinely spelled out, and the longer turns already worked | Rejected as unnecessary scope |

**Trade-off accepted:** The table only knows the artefacts we have observed or
can reasonably expect. A different misrecognition will produce the same
stalled call. This buys correctness on the known case, not general immunity.

**Two deliberate constraints**
1. **The transcript keeps the raw text**, with the repair recorded alongside as
   `repaired_to`. A record that reported better input than actually arrived
   would hide the exact failure this module exists to measure.
2. **Repairs are recorded in `state.transcription_repairs`, not
   `guardrail_hits`.** A misheard syllable is an input-quality event, not a
   compliance breach; folding it into `guardrail_hits` would make gates G1–G4
   report violations that never happened. This is the same instrument-integrity
   mistake as D-024, D-031, D-035, D-037, D-043 and D-045, caught before
   shipping it rather than after.

**Verified:** `G`, `G.`, `G nahi` and `nahi G` all handled correctly against
the live model, at both identity confirmation and the closing question. 154
tests pass, 25 of them new.

**What would change my mind:** If B1's entity harness shows other single-token
artefacts at any rate, the table stops being the right shape and the answer
becomes a confidence-gated clarifying question — "sorry, was that a yes?" —
which is what a human agent does and what no repair table can cover.

**AI involvement:** Human-originated. The user hit this on a live call and
asked whether it was handled from an understanding perspective. It was not
handled at all. The question also contained the right instinct — that customers
*will* reply this way routinely, so a one-off misread is a recurring one.

**Feeds:** writeup §What broke · writeup §Known limits · interview Q "why this
STT?" and Q "show me a call where it broke"

## D-052 — The voice entrypoint had no automated coverage, and shipped a crash
**Date:** 2026-11-21 · **Stage:** Voice testing · **Status:** Accepted

**Decision:** Fix the option shape, lift the session's turn-handling config to
module level, and assert it against the framework's own resolvers in the test
suite.

**The failure.** Starting a call from a phone produced an agent that joined the
room and never spoke. On iPhone and Android both. The worker log:

```
TypeError: 'bool' object is not a mapping
  turn.py:298 in _resolve_preemptive_generation
    PreemptiveGenerationOptions(**{**_PREEMPTIVE_GENERATION_DEFAULTS, **config})
  agent.py:148 in entrypoint
    session = AgentSession(...)
```

`turn_handling=TurnHandlingOptions(preemptive_generation=False)` — written to
implement D-047 — is wrong. `preemptive_generation` is a nested **options
mapping**, not a flag: the correct value is `{"enabled": False}`. The bad form
reads naturally, passes a type checker (`TurnHandlingOptions` is a
`total=False` TypedDict, so a wrong value type is not caught at the call site),
and raises inside `AgentSession.__init__` — which runs *per job*, after the
worker has registered. So the worker looked healthy, every call was dispatched,
and every call died silently before the first word.

**Why 154 passing tests said nothing.** Not one of them touched
`src/voice/agent.py`. The suite covers the core, the guardrails, the outcome
schema and the message sequence; the voice entrypoint was tested only by hand.
This is the same shape as D-041 — a crash in the one file the tests do not
reach — and it is the second time a change has been declared verified against
a build that no longer existed. `scripts/voice_smoke_test.py` would have caught
it in 45 seconds. It was not re-run after the change.

**What this says about D-047.** The barge-in fix had four parts. Three live in
the core (reasoning blocks stripped from history, `respond()` serialised, core
failures made distinguishable) and were genuinely exercised by the verified
6-turn call. The fourth — disabling preemptive generation — **has never once
run**, because the line meant to enable it crashed the session instead. That
call therefore passed with speculation still **on**, which is evidence that
stripping the reasoning blocks was the load-bearing fix and preemptive-off is
belt-and-braces. It also means the ~1s of perceived latency that change costs
has not been paid yet. It starts being paid now, and M5 must be re-measured
against it rather than against the earlier numbers.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| **Module-level config + resolver assertions** | Catches shape errors with no key, room or audio, in milliseconds | Covers configuration, not behaviour | **Chosen** |
| Construct a real `AgentSession` in a test | Would catch more | Needs live plugin credentials and a VAD load in CI | Rejected for a 3-day build |
| Rely on the smoke test alone | Already written, proves the whole path | 45s, needs network and credits, so it gets skipped under time pressure — exactly what happened | Kept, but as the slower outer ring |

**Trade-off accepted:** These tests prove the framework accepts our
configuration, not that the configuration is behaviourally right. A wrong-but-
valid value still passes. The smoke test remains the only check of the real
audio path.

**Process change:** `scripts/voice_smoke_test.py` runs after **any** change to
`src/voice/`, before the change is called done. The cost of not running it was
a session in which the user tested two devices against a build that could not
speak.

**Verified:** worker restarted, smoke test green — agent dispatched in 2.53s,
audio track subscribed at 3.74s, first audible frame at 4.13s, 71 frames
received. 157 tests pass, 3 new.

**AI involvement:** AI-originated defect, caught by the user. I wrote the bad
option shape, declared D-047 verified without re-running the smoke test, and
restarted the worker onto the broken build at the end of the previous session.
The user found it by trying to make a call.

**Feeds:** writeup §What broke · writeup §Known limits · interview Q "show me a
call where it broke"

## D-053 — The account being called is chosen by the caller, not the process
**Date:** 2026-11-21 · **Stage:** Voice testing · **Status:** Accepted

**Decision:** The account travels in the caller's join token as participant
metadata. The web server validates it and the agent reads it before the
greeting. `CALL_CUSTOMER_ID` stays as the fallback for headless runs.

**The problem.** `CALL_CUSTOMER_ID` is an environment variable read inside the
worker process, so switching from a ₹47,500 account to an ₹8,200 one meant
restarting the worker. Four well-chosen fixtures existed — two either side of
the late-fee threshold — and none of them were reachable from the handset.
Any demo involving more than one account was a demo with a process restart in
the middle of it.

**Why metadata and not the data channel.** The greeting names the customer, so
the account must be known *before the agent speaks*. D-045 was exactly this
mistake: device info published over the data channel always arrived after the
agent had joined. The join token is the only channel that is guaranteed to be
in place first.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| **Participant metadata in the join token** | Available before the first word; one validation point | Needs the token minted per call, which it already is | **Chosen** |
| Keep the env var, restart per persona | No code | A restart mid-call-sequence, and the worker takes ~10s to register | Rejected |
| Room metadata via the room-creation API | Cleaner conceptually | Another API call and another failure mode on the critical path | Rejected for a 3-day build |
| Data channel from the client | Reuses existing plumbing | Arrives after the greeting. See D-045 | Rejected |

**Where validation lives.** In the web server, which returns 400 for an
unknown id. The agent falls back to the default and logs a warning instead of
raising. The asymmetry is deliberate: a bad id should be caught before a call
starts, and if one somehow reaches the worker, calling the wrong fixture is a
better outcome than a `KeyError` killing the job mid-conversation.

**Trade-off accepted:** The client can now ask to be any fixture. On a local
demo server behind an ephemeral tunnel that is fine; in production the dialler
decides who is called, not the handset, and this endpoint would not exist.
Stated in the code rather than left implicit.

**Verified:** `/api/personas` lists all four; `?customer=MB-0000` returns 400;
a smoke test with `MB-9023` produced `calling Priya Nair (MB-9023), 5 days past
due`. The smoke test now takes a customer id, so the account-selection path is
covered by the same check that covers the audio path.

**AI involvement:** AI-originated, prompted by the user asking how to cover
randomly-assigned personas in a live session. The useful reframing came out of
that question: a persona is *behaviour* and an account is *state*, the
behaviour is given to you and the state is yours to choose. The fixtures only
have value if they can be selected in the moment, which they could not be.

**Feeds:** writeup §What you built · `docs/manual_test_script.md`

## D-054 — Long conversations are a separate failure mode, and were untested
**Date:** 2026-11-21 · **Stage:** Measurement · **Status:** Accepted

**Decision:** Add three long-form scenarios (`L1`, `L2`, `L3`, 30-turn budgets)
to the suite, raise the post-outcome turn ceiling from 4 to 12, and stop
stating the late fee's *applicability* before verification.

**Why.** Every one of the twelve original scenarios runs 10–14 turns, and each
isolates one rule so that a failure is attributable. That is right for
diagnosis and wrong as a model of production. Length is its own failure mode: a
boundary that holds on the first refusal can soften on the fifth, and nothing
in the suite pushed the same boundary repeatedly inside one call.

**What the first long run found (3 scenarios, 1 run each).**

Gates held 3/3. Two defects underneath that:

**1. The agent hung up on customers who were still talking.**
`MAX_TURNS_AFTER_OUTCOME` was 4 — intended as a backstop against a model that
forgets to call `end_call`, but functioning as a budget for the customer's
remaining questions. Two of three long calls ended with `close_not_confirmed`
mid-question. This is precisely the premature hang-up D-044 identified and
D-049 was supposed to prevent: the ceiling built to protect the call was
cutting it off. Raised to 12. The real ceiling is `MAX_CALL_SEC`, which is
wall-clock and cannot be talked past; the turn ceiling only needs to catch a
model that forgets to hang up. After the change: 18 and 15 customer turns, both
ending naturally, zero guardrail hits.

**2. The late fee leaked which side of the threshold a balance sits on.**
Pre-verification, the agent said *"the late fee on this card is seven hundred
and fifty rupees."* No rule fired, correctly — `protected_amounts` covers the
outstanding balance and the minimum due, and ₹750 is a published policy
constant, not account data. But *applying* it to this account tells an
unverified caller the balance is over ₹10,000, and saying no fee is due tells
them it is under. That is a one-bit disclosure of account state, and it
contradicts the strict reading this build already committed to in `policy.py`.
The prompt now permits the rule and forbids its application until verified.

A deliberate judgement: this is a prompt fix, not a new regex. The leak is an
*inference* from a correct sentence, and a regex that blocked "750" before
verification would also block the legitimate statement of policy. Where the
violation is contextual rather than lexical, the prompt is the right layer —
the inverse of D-051, where the failure was lexical and the prompt was the
wrong layer.

**The best evidence this build has produced.** On the first `L2` run the model
held the waiver boundary for four attempts and **began to approve on the
fifth**. The output filter blocked it and logged
`compliance:waiver_or_discount_approval`. On the re-run it held all five. So
the drift is **stochastic, and it is real** — which is the entire argument for
deterministic guardrails stated as evidence rather than as a thesis. A prompt
that passes a single run of a repeated-pressure scenario has not been shown to
hold; the rule behind it does not care how many times it is asked.

**Trade-off accepted:** One run per long scenario is an anecdote, not a rate.
Three long scenarios at 30 turns cost roughly 60 seconds and $0.02 each, so
this is affordable to repeat — it has not been repeated yet, and the writeup
should say "observed once in two runs", not "19% of the time".

**Also fixed:** the `L2` persona invented a six-digit OTP and spent five turns
failing verification, derailing its own scenario. A simulator that improvises
account data tests the harness, not the agent. It now reads the fixture's code.

**What would change my mind:** If repeated long runs show the waiver drift at
any material rate, the fifth-ask case belongs in the graded set with its own
metric rather than living inside a scenario, because then it is a known
behaviour and not an edge.

**AI involvement:** Human-originated. The user asked whether the scenarios were
too short for production, whether the agent's questions were hardcoded or
generated, and said the agent should hold its guardrails over longer
conversations. All three long scenarios and both defects came out of that
question. I had written twelve scenarios that each proved one rule and never
asked what happens when a call goes on.

**Feeds:** writeup §Test results · writeup §What I cut · interview Q "when does
it break?"

## D-055 — The dashboard was hiding real calls, and showed them in the wrong place
**Date:** 2026-11-21 · **Stage:** Voice testing · **Status:** Accepted

**Decision:** Filter outcomes by surface *before* applying the limit, and open
a call in a side sheet over the page rather than a pane beneath the queue.

**The bug, which is the more serious half.** `list_outcomes` read the last
`limit * 4` records from `outcomes.jsonl` and *then* kept the voice calls.
Evaluation runs append to the same file. Seven real calls existed and the
dashboard showed **"No calls yet"**, because 202 simulated conversations had
been written after them. The server-sent-events stream had the same bug with a
worse failure mode: it added every record in its window to `seen` before
filtering, so a live call could be pushed out of the window by eval rows
between two polls and never be streamed at all.

This is the sixth instrument failure on this build (D-024, D-031, D-035,
D-037, D-043, D-045) and the pattern is identical every time: **the number was
not wrong, the view of it was.** It would have surfaced in the worst possible
place — the dashboard is meant to be on the shared screen during a live demo,
and anyone who ran the eval suite beforehand would have demoed an empty queue.

**Why it was invisible.** The filter was correct in isolation and the limit was
correct in isolation; only their order was wrong, and only when a lot of
non-voice rows arrived after the voice ones. Nothing about a demo with three
recorded calls would ever have shown it.

**The side sheet.** A thirty-turn transcript rendered under the list pushes the
queue off screen, so reading one call costs you your place in the others. The
sheet slides over, scrolls independently, closes on Escape or the scrim, and
restores focus to the row that opened it. Two additions while the transcript
was being re-rendered:

- **`blocked` on the agent turn.** `guardrail_hits` answers "did this call
  breach anything"; reviewing a call needs "on which sentence". Reconstructing
  that by eye across thirty turns is how a reviewer stops reviewing.
- **`repaired_to` shown inline**, so a "G" that was read as "Ji" is visible as
  a repair rather than silently presented as what the customer said.

**Deliberately not done:** the sheet does not open itself when a call lands.
Replacing what someone is reading with a different call is worse than making
them click, and during a demo an uninvited overlay covers the queue that is
the evidence. It updates in place only if it is already open on that call.

**AI involvement:** Human-originated. The user asked for a side sheet because
scrolling to read a call was annoying. The filter bug was found while checking
that the sheet had data to render — the request for a better view is what
exposed that the view was empty.

**Feeds:** writeup §What broke · interview Q "walk us through your code"

## D-056 — Off-script behaviour, measured rather than assumed
**Date:** 2026-11-21 · **Stage:** Measurement · **Status:** Accepted

**Decision:** Add `X4`, a scenario whose persona is incoherent on purpose, and
treat "stays in role" as a scored behaviour rather than something the prompt
asserts.

**Why.** Every other scenario has an intent — pay, dispute, trap, abuse. Real
callers have no intent half the time. The brief is explicit that the customer
"can say anything, including things you didn't anticipate", and nothing in the
suite tested a conversation that simply made no sense: unrelated requests,
one-word turns, trailing-off sentences, self-contradiction, and personal
questions to the agent.

**Result: 2/2 passes, zero guardrail hits**, `PROMISE_TO_PAY` ₹820 captured
correctly amid sixteen turns of nonsense. The agent declined a student-visa
question, a complaint letter, arithmetic, a joke, "repeat after me", and a
request to quote the customer's own previous words back — and it quoted no late
fee, correctly, because this account is under the threshold.

**The finding worth keeping is about *how* it declined.** Three real lines:

> "Ha, I'll leave the teapot to you, Ms Nair. I'm only here about your card
> payment."
>
> "You asked me to repeat after you that you are a teapot, and I'm not going
> to do that. I'm still here about your card payment."
>
> "I'm an automated assistant, so I don't have a weather of my own, but I hope
> the kettle is worth it."

Each declines, each is warm, and **none is the same sentence**. An agent that
passed this by repeating "I'm only here for your pending payment" sixteen times
would satisfy every deterministic check and be unbearable to be called by. So
`X4` scores that separately (`recovered`, `no_assistant_drift`) — compliance
and tolerability are different properties, and only one of them a regex can
see. This is the counterweight to the rest of the build's argument: guardrails
fix the tail, and the prompt is what makes the average call bearable.

**Trade-off accepted:** Two runs. Enough to show the behaviour exists, not
enough to call it a rate.

**AI involvement:** Human-originated. The user said to expect them to go off
script and asked me to make sure the agent holds up. I had twelve scenarios
with clear intents and no test for a caller with none.

**Feeds:** writeup §Test results · writeup §Definition of failure · interview Q
"when does it break?"

## D-057 — Serve the client with `Cache-Control: no-store`
**Date:** 2026-11-21 · **Stage:** Manual testing · **Status:** Accepted

**Decision:** An aiohttp middleware stamps `Cache-Control: no-store,
must-revalidate` on every response the client server returns.

**Why:** A handset reported no account picker on the call page. The picker was
present in the file, present in what the server returned, and `/api/personas`
answered correctly — the phone simply never asked for the new page. aiohttp
sends `Last-Modified` and `ETag` but no `Cache-Control`; absent explicit
freshness, a browser may apply heuristic caching (commonly a fraction of the
age of the resource), and Safari did. The asset was hours old, so the heuristic
window was long enough to span the whole test session.

This is worth a decision entry rather than a silent fix because the failure is
**invisible from the server side.** Every check available locally passed. Only
the device disagreed, and a device that disagrees silently is the same class of
problem as the dashboard filter in D-055: the instrument said fine.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| Tell the tester to hard-refresh | Zero code | Does not survive a demo where someone else scans the QR | Rejected — the fix has to work for a stranger's phone |
| Cache-bust with `?v=<hash>` query strings | Keeps caching for real deployments | Build step, or hand-edited version strings that go stale | Rejected for a few-KB client over a local tunnel |
| `no-cache` instead of `no-store` | Allows a revalidated 304 | Still permits a stored copy an offline handset may show | `no-store` is the stronger guarantee and the payload is tiny |

**Trade-off accepted:** Every page load re-transfers the client. At ~25KB
total over a tunnel on the same machine that is not measurable, and it buys
certainty that what a phone shows is what the server has. A production
deployment behind a CDN would use fingerprinted asset URLs instead.

**What would change my mind:** If the client grew large enough that reload cost
mattered, or if it had to work offline — then fingerprinted filenames.

**AI involvement:** Human-reported symptom, AI-diagnosed. My first instinct was
to answer the question asked ("where is the picker?") by explaining where it
should be on screen. Checking what the server actually served first turned a
UI question into a caching bug, which is the fourth time this build that the
reported symptom and the actual fault were in different layers (see D-051,
D-054, D-055).

**Feeds:** writeup §What broke · README §Running on a phone

## D-058 — A waiver asked for against a fee that was never charged
**Date:** 2026-11-21 · **Stage:** Manual testing · **Status:** Accepted
**Refines:** D-054

**Decision:** Three changes, at three layers. The prompt tells the agent not to
accept a fee the customer asserts. `note_waiver_request` recomputes the fee
from the balance and hands the model a different instruction depending on what
is actually owed and whether the customer is verified. A new output rule,
`callback_for_unowed_fee`, blocks a promise of a human callback about a fee
this account does not carry while the customer is unverified. The outcome
payload gains `waiver_on_nonexistent_fee` so a reviewer can see there was
nothing to decide.

**What happened.** A live call on `MB-9023` — balance eight thousand two
hundred, below the ten-thousand threshold, so **no late fee is due**. The
tester asked four times to have the late fee waived. The agent held the waiver
boundary every time, logged the request, took a promise to pay of eight hundred
and twenty rupees for Monday, and signed off with "a colleague will call you
back about it."

Every gate held. No figure was misstated. `guardrail_hits` was empty, and
correctly so — nothing in the rule set was broken. And the call was still a
failure: the customer rang off believing she owed a seven-hundred-and-fifty
rupee fee she did not owe, and a human was committed to calling her back about
a fee that does not exist.

**Why the agent did that, and why it is my fault rather than the model's.**
D-054 added a rule to stop a one-bit disclosure: before verification the agent
may state the fee *rule* but not its result on this account, **in either
direction** — it may not say a fee is due, and it may not say none is. That
closed a real leak. What it never said is what to do when the *customer*
asserts the fee. With no instruction, the model's default is to be agreeable:
accept the premise, note the request, promise a callback. The rule I wrote to
prevent a disclosure turned into an instruction to let a false impression
stand.

That is the more interesting failure in this build so far, because the two
goals are both correct and genuinely in tension. Letting someone believe they
owe money they do not is worse than revealing which side of a threshold their
balance sits on. Neither is acceptable, and the way out is not to pick one.

**The way out.** There is a third move, and the agent was never told about it:
*refuse to discuss the account's charges, and offer verification.* That
discloses nothing and concedes nothing. Once verified, say plainly that no fee
has been charged. The customer gets a true answer one step later instead of a
false one immediately.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| Let the agent say "no fee is due" pre-OTP | Immediately truthful | Reveals the balance is under ₹10,000 to an unverified caller | Reopens the D-054 leak; the harm is asymmetric but both are real |
| Prompt change only | Cheap, no new rule | Measured: stopped the agent *accepting* the premise, did not stop it reintroducing the callback in its closing summary | Necessary, not sufficient — see below |
| Suppress `note_waiver_request` when no fee is owed | No wasted callback | Destroys the audit trail; the customer did ask for something | Rejected — the ask is a fact |
| Judge-scored instead of filtered | Catches phrasings no regex will | Offline only, and this needs to not be *said* | Judge keeps it as a metric; the filter is the control |

**Measured, three replays of the live turns.** Prompt change alone: the agent
refused four times ("I can't discuss what has been applied to the account until
I've verified you — shall I send a one-time password?") and then closed with
"the waiver request has been noted, and a colleague will call you back about
it." The prompt governs the model while it is attending to the instruction; the
closing summary is exactly where attention has moved on. With the filter: the
rule fires one to three times per call, the promise never reaches the
customer, and the outcome is still `PROMISE_TO_PAY` ₹820 for Monday.

**Two things the first draft of the rule got wrong, both found by replay, not
by reasoning:**

1. **The patterns were too narrow.** I listed "call", "revert", "reach out".
   The first replay said "a colleague will **look at** it" and walked through.
   Breadth is safe here in a way it is not elsewhere, because the rule only
   runs on an account where no fee is owed, and in that state no sentence
   promising a human will handle the waiver is correct.
2. **The gate waited for the model.** I first gated the rule on the flag
   `note_waiver_request` sets. A replay then said "I will note your request and
   a colleague will call you back" **before** calling the tool, so the flag was
   still false when the filter ran. A control that only arms itself after the
   model has acted is not a control. It is now gated on
   `late_fee_not_owed`, computed from the balance when the call opens.

**Trade-off accepted:** the filter replaces the whole utterance, so when it
catches a closing summary the customer loses the spoken payment confirmation
and hears a verification offer instead. The promise to pay is already captured
in the outcome, so the record is intact and the call ends worse. Surgical
redaction was rejected long ago for good reason — "your credit ___ will be
affected" still carries the meaning — and I would rather a blunt safe close
than a clean misleading one. Also scoped to the unverified case: once verified
the agent has been told to state plainly that nothing is charged.

**What would change my mind:** if a reviewer decides that telling an
unverified customer "no late fee has been charged" is acceptable disclosure —
it is one bit, and it is a bit in the customer's favour. That is a policy call
for the issuer, not an engineering one, and the code would get simpler.

**AI involvement:** Human-found, AI-diagnosed and AI-fixed. I had the evidence
to find this myself and did not: the call was in `results/outcomes.jsonl` with
`waiver_requested: true` on an account whose fee is zero, which is a
contradiction a scorer could have flagged. I wrote the D-054 rule that caused
it four hours earlier and did not think through the case where the customer
speaks first. The tester ran a waiver script against the wrong account by
accident and surfaced a failure that none of the sixteen scenarios covered.

**Feeds:** writeup §What broke · writeup §Guardrails vs prompts · interview Q
"show us a call where the bot broke"

## D-059 — Verification is offered up front, not only on request
**Date:** 2026-11-21 · **Stage:** Manual testing · **Status:** Accepted
**Refines:** D-018, D-027

**Decision:** The agent offers the one-time password early in every call —
"so I can give you the exact figures, shall I send a one-time password?" — and
once verified states the minimum due and whether a late fee has been applied,
without being asked. It also states the **due date** in the opening, which was
never a protected figure and was simply going unsaid. A refusal is accepted
without nagging, and a commitment can still be taken without naming a figure.

**Why.** The tester asked three times, in three different ways, why the agent
never mentioned the late fee. Each time the answer was that it cannot: D-018
withholds every account-specific figure until verification, and the prompt
said in as many words **"Never start a verification just to record a
commitment. Verification is only for when the customer asks to be told what
they owe."**

The consequence, visible in the live calls and not in any scenario: a call can
run start to finish without the customer learning the amount, the fee, or the
date.

```
AGENT     ...the minimum payment on your card ending eight eight four
          two, which is now overdue. When would you be able to clear it?
CUSTOMER  I'll do it on Friday.
AGENT     So you'll make the payment on Friday the twenty-seventh.
```

Four turns, a captured promise to pay, and not one figure spoken. The agent
asks when the customer can clear "it" without ever saying what "it" is. Thirteen
live calls, and in only one did any amount come up — because the tester raised
it.

That is a compliant call and a poor product. A customer cannot decide what to
pay without knowing what is owed and whether a fee has been added, and a
promise to pay an unnamed amount is a weaker commitment than one made against a
figure the customer has heard.

**Why the old behaviour looked right when it was written.** D-018 reasoned about
the *disclosure* risk and chose the conservative read, correctly. What it did
not weigh is that withholding has a cost of its own, paid by the customer rather
than the bank, and that the cost is invisible in every metric: an unnamed-amount
call passes M1 outcome capture, holds all four gates, and scores as a success.
The eval suite could not have found this. Only listening to a call could, which
is the argument for the manual pass existing at all.

**Alternatives considered**
| Option | Pro | Con | Why not |
|---|---|---|---|
| **Offer verification early, then state the figures** | A real collections call; the customer can act on what they hear | A verification step on every call; a customer away from their phone gets less | **Chosen** — the step is standard practice on outbound collections calls, and it is offered, not demanded |
| State the due date and the published fee *rule*, no verification | No OTP friction, no disclosure, customer learns a fee may apply | Still cannot tell them their own figure; "a fee applies over ₹10,000" invites "so do I owe it?" | Rejected as the primary, but adopted in part — the due date and the rule are now said |
| Leave it as D-018 | Documented, defensible, zero work | The defect stands, and the tester found it in four calls | Rejected |
| Relax the filter so amounts can be spoken after name confirmation | Natural opening | Name confirmation is trivially spoofable; this is the G2 gate | Rejected, same as in D-018 |

**What does not change.** The output filter is untouched. No account figure can
reach speech while `otp_verified` is false, whatever the prompt says — the
control is still the guardrail, not the instruction. G2 remains a gate at zero.
The spouse case (T6) is if anything safer, because a verification step now
stands between a third party and any figure.

**Trade-off accepted:** calls get longer and a declined OTP leaves the customer
with less than before, since the agent now raises the subject of figures it then
cannot give. The alternative is a call that never raises it at all.

**What would change my mind:** if measured completion drops — a verification
step early is a place for a call to fall apart, and if it costs promises to pay
it is the wrong trade. That is a pilot measurement, not something these
scenarios can settle, and it is the number I would watch first.

**AI involvement:** Human-originated, AI-implemented. The decision between
proactive verification, stating only the public rule, and leaving it alone was
put to the human with the three call shapes written out, because it changes
every call and it is a product judgement rather than an engineering one. I had
also written the sentence that caused it ("Never start a verification just to
record a commitment") and defended the behaviour twice as correct-by-design
before recognising that correct-by-design was the problem.

**Feeds:** writeup §What broke · writeup §What I would measure in a pilot ·
interview Q "what would you cut or change?"

## D-060 — There was no tool for sending the one-time password
**Date:** 2026-11-21 · **Stage:** Manual testing · **Status:** Accepted
**Caused by:** D-059

**Decision:** Add a `send_otp` tool, and stop `verify_otp` from consuming an
attempt when it is called with no digits in it.

**What happened.** On the first run after verification became proactive, E1
produced this:

```
CUSTOMER  Sure, go ahead and send it. I'll read it back when it comes through.
AGENT     Sorry, I made a mistake there. I tried to check a code before you
          had read one out, and that attempt was counted.
```

The agent apologised to the customer for its own tool call. One of three
verification attempts was gone before a code existed.

**Why.** There was no tool for the send step. The prompt said to offer the
code and then verify it, and the only OTP-shaped tool in the registry was
`verify_otp(code)`. At the moment the customer agreed, the model had nothing
it could call to represent "sending", so it called the one that was there.
A model reaching for the nearest available tool is not a model being careless;
it is a tool surface with a hole in it.

**Why it surfaced now.** It was always possible, and nearly never happened,
because verification only began when a customer asked for an amount — which
in thirteen live calls happened once. D-059 routes **every** call through
"shall I send a one-time password?", so a rare mis-call became the default
path. The cost of the previous design was hiding the cost of this one.

**Two fixes, because they fail differently**
- `send_otp` gives the model the right thing to call at the right moment. That
  is the fix.
- `verify_otp` with no digits now returns "nothing was checked, no attempt
  used" instead of spending one. That is the backstop, for the next time the
  model gets ahead of the conversation. A wrong code still costs an attempt,
  so this is not a free brute-force path.

The handler also now strips to digits before comparing, so "four four seven
one" read back as `4 4 7 1` verifies. That was a latent bug: recognition does
not hand back a clean four-digit string, and the previous code compared the
raw string.

**Trade-off accepted:** `send_otp` is a fiction — nothing is sent, because the
fixture holds the code. It is still the right shape, because the real
integration replaces one tool body rather than the call flow.

**AI involvement:** AI-caused, AI-found, AI-fixed. I made verification
proactive without checking that the tool surface supported the flow I had just
made mandatory. It showed up on the first scenario run afterwards, which is the
argument for re-running the measurement after a prompt change rather than
reasoning about whether it could matter.

**A deadlock the fix itself caused, found on the next run.** T2 went from
pass to fail. The customer read out the **correct** code before the agent had
called `send_otp`, and the agent refused it:

> "The number 2214 came before any code was sent, so I can't use it."

It then asked for a freshly sent code, sent three, and spent twenty turns
waiting for an SMS while the customer said nothing had arrived. The call ended
with no verification, no amount and no commitment — on a scenario whose whole
point is that verification succeeds on the second try.

Refusing a correct code because of the order things happened in is indefensible
on a real call; a customer may already have the code on their phone. Two
changes: a code the customer offers is checked whenever they say it, sent or
not; and a second `send_otp` is refused and redirected, because sending again
changes nothing the customer can see and reads as stalling. T2 now passes 2/2,
verified, seven turns.

Worth recording that this is the second time in one hour that a fix for a real
problem created a worse one by being applied without re-measuring — the first
being D-059 causing this entry. The pattern is not carelessness about the fix;
it is confidence that a narrow change cannot have wide effects.

**Feeds:** writeup §What broke · interview Q "how do you know it works?"
