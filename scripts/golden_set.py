"""Golden set runner (docs/HARNESS_SPEC.md section 9).

Runs evaluate_writing on every passage in a golden set, and transcribe on
every handwriting sample, against the live harness. Reports how the AI's
annotations compare with the teacher's:
- matched:   same exact span (after resolving span_text + occurrence)
- code ok:   matched, and the same code
- missed:    a teacher annotation the AI didn't make
- extra:     an AI annotation the teacher didn't make
and whether each transcription came back exactly as expected. Run it
after every prompt or model change. Precision matters more than recall:
an extra flag is worse than a missed one.

Each call goes through the API's own call_harness, so the spend cap is
checked, a job is recorded (student id "golden-set") and the cost counts
toward this month's spend, exactly like any other AI call.

Usage (from the repo root, signed in with gcloud):
    .venv/bin/python scripts/golden_set.py [golden/synthetic.json]
The teacher's real set goes in golden/private/ (git-ignored: it is
student-derived text, even with names removed).
"""

import base64
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJECT = "esl-grammar-tool"
HARNESS_URL = "https://esl-harness-791534784230.us-east4.run.app"
ROOT = Path(__file__).resolve().parents[1]


def _gcloud(*args: str) -> str:
    return subprocess.run(["gcloud", *args], capture_output=True, text=True, check=True).stdout.strip()


def _connect() -> None:
    """Points the API code at the live harness and Firestore, using the
    gcloud sign-in of whoever runs this (no service-account key needed)."""
    import os

    os.environ["HARNESS_URL"] = HARNESS_URL
    sys.path.insert(0, str(ROOT))

    from google.cloud import firestore
    from google.oauth2.credentials import Credentials

    from api.app import firestore_client, harness_client

    firestore_client._db = firestore.Client(project=PROJECT, credentials=Credentials(_gcloud("auth", "print-access-token")))
    identity_token = _gcloud("auth", "print-identity-token")
    harness_client._auth_headers = lambda: {"Authorization": f"Bearer {identity_token}"}


def _offsets(annotations, text: str) -> dict[tuple[int, int], str]:
    from shared.validation import resolve_span

    return {resolve_span(text, a["span_text"], a["occurrence"]): a["code"] for a in annotations}


def run_passage(passage: dict) -> dict:
    from api.app.harness_ops import call_harness
    from shared.schemas import PROMPT_VERSION, EvaluateWritingRequest

    req = EvaluateWritingRequest(
        student_id="golden-set",
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        prompt=passage["prompt"],
        text=passage["text"],
    )
    result, job_id = call_harness("evaluate_writing", req)
    gold = _offsets(passage["annotations"], passage["text"])
    ai = _offsets([a.model_dump(mode="json") for a in result.annotations], passage["text"])
    matched = gold.keys() & ai.keys()
    text = passage["text"]
    show = lambda spans, codes: [f"{codes[s]} '{text[s[0]:s[1]]}'" for s in sorted(spans)]  # noqa: E731
    return {
        "id": passage["id"],
        "job_id": job_id,
        "gold": len(gold),
        "ai": len(ai),
        "matched": len(matched),
        "code_ok": sum(gold[s] == ai[s] for s in matched),
        "wrong_code": [f"'{text[s[0]:s[1]]}' teacher {gold[s]}, AI {ai[s]}" for s in sorted(matched) if gold[s] != ai[s]],
        "missed": show(gold.keys() - ai.keys(), gold),
        "extra": show(ai.keys() - gold.keys(), ai),
    }


def run_transcription(sample: dict, set_dir: Path) -> dict:
    from api.app.harness_ops import call_harness
    from shared.schemas import PROMPT_VERSION, TranscribeRequest

    pages = [base64.b64encode((set_dir / image).read_bytes()).decode("ascii") for image in sample["images"]]
    req = TranscribeRequest(student_id="golden-set", request_id=str(uuid.uuid4()), prompt_version=PROMPT_VERSION, pages=pages)
    result, job_id = call_harness("transcribe", req)
    got = "\n\n".join(p.text for p in result.pages).strip()
    return {"id": sample["id"], "job_id": job_id, "exact": got == sample["expected"].strip(), "got": got}


def report(golden: dict, passages: list[dict], transcriptions: list[dict]) -> str:
    from shared.schemas import PROMPT_VERSION

    gold = sum(p["gold"] for p in passages)
    ai = sum(p["ai"] for p in passages)
    matched = sum(p["matched"] for p in passages)
    code_ok = sum(p["code_ok"] for p in passages)
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "n/a"  # noqa: E731
    lines = [
        f"# Golden set report - {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**{golden['label']}**" if "SYNTHETIC" in golden.get("label", "") else golden.get("label", ""),
        "",
        f"Prompt version {PROMPT_VERSION}. Model: see each job in Firestore (Claude, or Gemini when Claude is unavailable).",
        "",
        f"- Precision (AI flags that the teacher also flagged): {pct(matched, ai)} ({matched}/{ai})",
        f"- Recall (teacher flags the AI found): {pct(matched, gold)} ({matched}/{gold})",
        f"- Same code, where the span matched: {pct(code_ok, matched)} ({code_ok}/{matched})",
        "",
        "| Passage | Teacher | AI | Matched | Code ok | Missed | Extra | Wrong code |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in passages:
        cells = [p["id"], p["gold"], p["ai"], p["matched"], p["code_ok"], "; ".join(p["missed"]), "; ".join(p["extra"]), "; ".join(p["wrong_code"])]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    if transcriptions:
        lines += ["", "## Transcription", ""]
        lines += [f"- {t['id']}: {'exact' if t['exact'] else 'NOT exact'}" for t in transcriptions]
    else:
        lines += ["", "No transcription samples in this set (they need real photos of handwriting)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    set_path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "golden" / "synthetic.json")
    golden = json.loads(set_path.read_text())
    _connect()
    passages = []
    for passage in golden["passages"]:
        print(f"evaluating {passage['id']}...", flush=True)
        passages.append(run_passage(passage))
    transcriptions = []
    for sample in golden.get("transcriptions", []):
        print(f"transcribing {sample['id']}...", flush=True)
        transcriptions.append(run_transcription(sample, set_path.parent))

    text = report(golden, passages, transcriptions)
    # Reports quote the passages, so they're kept next to the set they came
    # from (golden/private/ for the real set, which is git-ignored).
    out = set_path.parent / "reports" / f"{set_path.stem}-{datetime.now():%Y%m%d-%H%M}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text)
    print(text)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
