# Deliverables

Everything submitted, in one place.

| File | What it is |
|---|---|
| **`Solution Brief - vFinal.pdf`** | The brief. Five pages of body, then appendices A–E: what two more weeks would buy, results by scenario, both prompt versions, the failure taxonomy, and where to find everything. |
| **`Eval Results.xlsx`** | Every scored conversation, one per row, 204 of them. The **Legend** sheet explains every gate, metric, scenario id and column — including that a blank check means it did not apply, which is not the same as passing. |
| **`transcripts/`** | Three annotated calls: one clean, one where the agent breaks out loud, one where it drafted a breach and the filter caught it before it was spoken. |
| **`Decision Log.pdf`** | All 73 decisions, written as the work happened rather than reconstructed afterwards. Indexed by stage, status and how each was reached, with a "start here" list of five. |
| **`Code Glossary.pdf`** | What every identifier means — `E1`, `T7`, `G2`, `M5`, the guardrail rule names, the account fixtures. |

**Code, and everything these files cite:**
https://github.com/sukritbhattacharya/collections-voice-agent

## Where the cited files live

The brief points at a few things that are evidence rather than deliverables,
and they are in the repository rather than in this folder:

| Cited as | What it is |
|---|---|
| `results/eval_results.csv` | The same 204 rows as the workbook, in a form that diffs in version control |
| `results/stt_accuracy.csv` | The speech-recognition measurements behind M6 |
| `results/v3_claude-sonnet-5-5_runs.jsonl` | The raw runs behind the model head-to-head |
| `results/voice_ab/` | 30 clips across 10 voice and prosody combinations |
| `docs/DECISIONS.md` | The decision log in markdown; the PDF here is generated from it |
| `src/core/prompts/v2_rewrite.md` | The full rewritten prompt, excerpted in appendix C |

## Rebuilding any of this

```bash
uv sync --extra docs
uv run python -m src.evals.export                       # the workbook and the CSV
uv run python scripts/export_transcripts.py             # the three transcripts
uv run python scripts/make_pdf.py docs/solution_brief.md \
    "deliverables/Solution Brief - vFinal.pdf" "solution brief" 0.86
uv run python scripts/make_decision_log_pdf.py          # the decision log
uv run python scripts/make_glossary_pdf.py              # the glossary
```

Nothing here is hand-maintained. Every file is generated from a source in the
repository — `docs/solution_brief.md`, `docs/DECISIONS.md`, the scenario files
in `src/evals/scenarios/`, and the scored runs in `results/` — so the numbers
in the brief are all recomputable rather than asserted.
