"""Record SSE streams from an in-process plg-api for the web tests to replay (MSW).

    uv run python scripts/record_sse_fixtures.py

Writes `web/src/test/fixtures/*.sse`. Streams come from the real API and graph with a
scripted LLMClient, so they match what the BFF receives from `plg serve`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from plg.api.app import create_app
from plg.config import REPO_ROOT, Settings
from plg.llm import ScriptedLLMClient

OUT = REPO_ROOT / "web" / "src" / "test" / "fixtures"
USER = {"X-PLG-User": "S05"}

SCRIPTS: dict[str, tuple[str, str, Exception | None]] = {
    "answer": (
        "When do we issue a letter of demand?",
        "Under **POL-003 v2.0**, a letter of demand is issued once arrears reach 60 days.",
        None,
    ),
    "error": (
        "When do we issue a letter of demand?",
        "Under POL-003 v2.0, a letter of",
        ConnectionError("Claude unavailable"),
    ),
}


def record(question: str, answer: str, error: Exception | None) -> str:
    llm = ScriptedLLMClient()
    llm.script("merge", question, answer, error=error)
    with TestClient(create_app(Settings(), llm=llm)) as client:
        thread_id = client.post("/threads", headers=USER).json()["thread_id"]
        with client.stream(
            "POST", f"/threads/{thread_id}/runs", json={"message": question}, headers=USER
        ) as response:
            return response.read().decode()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (question, answer, error) in SCRIPTS.items():
        path = OUT / f"{name}.sse"
        path.write_text(record(question, answer, error))
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
