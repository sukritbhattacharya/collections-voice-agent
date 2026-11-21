"""Build docs/decision_log.pdf from docs/DECISIONS.md.

The log is the raw material the writeup is assembled from: every material
decision recorded when it was made, with the alternatives, the trade-off
accepted, what would change my mind, and where the AI's suggestion was
overridden. It is reference material, not a narrative, so the PDF adds the
two things a reader of reference material needs and the markdown does not
have: a front page saying how to read it, and an index that can be scanned.

Both are generated from the entries, so neither can drift from them.

    uv run --with reportlab python scripts/make_decision_log_pdf.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "DECISIONS.md"
STAGED = ROOT / "docs" / "_decision_log_build.md"
OUT = ROOT / "docs" / "decision_log.pdf"

ENTRY = re.compile(r"^## (D-\d+) — (.+?)$", re.M)
META = re.compile(
    r"\*\*Date:\*\*\s*([\d-]+).*?\*\*Stage:\*\*\s*(.+?)\s*·.*?\*\*Status:\*\*\s*(\S+)"
)


def involvement(body: str) -> str:
    """One word for how the decision was reached.

    Read off the entry's own `AI involvement` line rather than assigned here,
    so the index cannot disagree with the entry it points at.
    """
    m = re.search(r"\*\*AI involvement:\*\*\s*(.{0,120})", body, re.S)
    text = (m.group(1) if m else "").lower()
    if "overridden" in text:
        return "**overridden**"
    if text.startswith("human-originated") or "human-originated" in text:
        return "human"
    if "human-reported" in text or "human-found" in text or "human-identified" in text:
        return "human-found"
    if "ai-found" in text or "ai-caused" in text:
        return "AI-found"
    return "AI, accepted"


def main() -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}")
        return 1
    text = SOURCE.read_text(encoding="utf-8")

    marks = list(ENTRY.finditer(text))
    rows, counts = [], {"overridden": 0, "human": 0}
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        meta = META.search(body)
        date, stage, status = meta.groups() if meta else ("", "", "")
        tag = involvement(body)
        if "overridden" in tag:
            counts["overridden"] += 1
        if tag in ("human", "human-found"):
            counts["human"] += 1
        rows.append(
            f"| `{m.group(1)}` | {m.group(2)} | {stage} | {status} | {tag} |"
        )

    header = f"""# Decision log

**Collections Voice Agent · Sukrit Bhattacharya**
**Code:** https://github.com/sukritbhattacharya/collections-voice-agent

{len(marks)} decisions, written as the work happened rather than reconstructed
afterwards. That is the point of the file: rationale recalled three days later
is always tidier, and less honest, than rationale written while the trade-off
still hurts.

Each entry carries the decision, why, the alternatives considered as a table,
the **trade-off accepted**, **what would change my mind**, and an **AI
involvement** tag. The last of those exists because "where did you override
the AI?" is close to impossible to answer honestly after the fact — tagging
each decision as it is made means the answer can be read off rather than
remembered. **{counts['overridden']} entries record an override**, and
{counts['human']} record something a human found that no test here could have.

Entries are not renumbered or rewritten when a later one supersedes them;
the superseding entry says so. A few corrections are recorded as corrections
for the same reason. D-026 does not exist — a numbering slip, left as a gap
because entries cross-reference each other by number.

## Index

| | Decision | Stage | Status | How it was reached |
|---|---|---|---|---|
{chr(10).join(rows)}

---

"""
    STAGED.write_text(header + text, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/make_test_script_pdf.py"),
             str(STAGED), str(OUT), "decision log"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(result.stdout + result.stderr)
            return result.returncode
    finally:
        STAGED.unlink(missing_ok=True)
    print(f"  wrote {OUT.relative_to(ROOT)}  ({len(marks)} decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
