# Deliverables

Everything submitted, in one place. Each file is generated from a source in
this repository, so nothing here is a copy that can drift out of date — the
command that rebuilds it is given beside it.

| File | What it is |
|---|---|
| **`solution_brief.pdf`** | The brief itself. Five pages of body, then appendices A–E: what two more weeks would buy, results by scenario, both prompt versions, the failure taxonomy, and where to find everything. |
| **`eval_results.xlsx`** | Every scored conversation, one per row. The **Legend** sheet explains every gate, metric, scenario id and column — including that a blank check means it did not apply, which is not the same as passing. |
| **`transcripts/`** | Three annotated calls: one clean, one where the agent breaks out loud, one where it drafted a breach and the filter caught it before it was spoken. |
| **`decision_log.pdf`** | All 69 decisions, written as the work happened rather than reconstructed afterwards. Indexed by stage, status and how each was reached. |
| **`code_glossary.pdf`** | What every identifier means — `E1`, `T7`, `G2`, `M5`, `P14`, the guardrail rule names, the account fixtures. |

**Code:** https://github.com/sukritbhattacharya/collections-voice-agent

## Rebuilding any of it

```bash
uv sync --extra docs
uv run python -m src.evals.export                      # the workbook + the CSV
uv run python scripts/export_transcripts.py            # the three transcripts
uv run python scripts/make_pdf.py docs/solution_brief.md \
    deliverables/solution_brief.pdf "solution brief" 0.86              # the solution brief
uv run python scripts/make_decision_log_pdf.py         # the decision log
uv run python scripts/make_glossary_pdf.py             # the glossary
```

The sources are `docs/solution_brief.md`, `docs/DECISIONS.md`, the scenario files in
`src/evals/scenarios/`, and the scored runs in `results/`. The numbers in the
brief are all recomputable from `results/eval_results.csv`, which is the
same data as the workbook in a form that diffs in version control.
