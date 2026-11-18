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
**Date:** 2026-11-18 · **Stage:** Planning · **Status:** Accepted

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
