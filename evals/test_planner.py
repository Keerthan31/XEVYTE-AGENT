"""
LLM-judged eval of the PLANNING step using deepeval's GEval metric. Unlike
test_retrieval.py, this needs a live judge call (deepeval defaults to
GPT-4o-mini as the judge) — set OPENAI_API_KEY before running:

    python -m pytest evals/test_planner.py -v

This exercises the real pipeline: real RAG retrieval against the real
catalog -> real instructor-structured planning call -> GEval judges
whether the chosen endpoint and extracted arguments are sensible given the
user's request and the retrieved candidates it had to choose from.
"""
import json
import sys
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.nodes import _run_planner  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.rag.ingest import ingest  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402

GOLDEN_PATH = Path(__file__).parent / "golden_queries.json"

planning_quality = GEval(
    name="HRMS Call Planning Quality",
    criteria=(
        "The actual output is a JSON plan (endpoint_id, path_args, query_args, body, missing_info) "
        "produced for the user's request, chosen from the candidate endpoints in the retrieval context. "
        "Score highly if: the chosen endpoint_id genuinely matches the user's intent; any path/query "
        "arguments that ARE filled in are plausible and use only parameter names that appear in the "
        "matching candidate's spec; and the plan does not invent specific ids, dates, or amounts that "
        "were never mentioned in the input (asking via missing_info instead is correct, not a flaw). "
        "Score low if it picked a clearly wrong endpoint, used a parameter name not defined for that "
        "endpoint, or fabricated a specific value with no basis in the input."
    ),
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.RETRIEVAL_CONTEXT],
    threshold=0.6,
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_ingested():
    ingest(load_catalog())


def _golden_cases():
    return json.loads(GOLDEN_PATH.read_text())


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["query"][:40])
def test_planner_picks_sensible_call(case):
    catalog = load_catalog()
    retrieved = retrieve(case["query"], top_k=12)
    candidates = [r.endpoint for r in retrieved]
    assert candidates, f"No candidates retrieved at all for {case['query']!r} — fix retrieval first"

    state = {"user_message": case["query"], "conversation_history": [], "employee_id": "EMP1023", "role": "EMPLOYEE"}
    plan = _run_planner(state, candidates)

    test_case = LLMTestCase(
        input=case["query"],
        actual_output=json.dumps(plan.model_dump()),
        retrieval_context=[c.as_prompt_block() for c in candidates],
    )
    assert_test(test_case, [planning_quality])
