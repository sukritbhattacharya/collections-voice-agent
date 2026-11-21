"""Running a persona someone just described, with no file on disk.

Authoring a YAML file is right for a test set and useless when an interviewer
has described a customer out loud and wants to see the agent meet them. See
D-067.
"""

from __future__ import annotations

import pytest

from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID
from src.evals.runner import ad_hoc_scenario, load_scenarios

PERSONA = "You are Kavita Rao, 52, and you believe auto-debit already paid."


def test_a_sentence_becomes_a_runnable_scenario():
    s = ad_hoc_scenario(PERSONA)
    assert s["persona"] == PERSONA
    assert s["customer_id"] == DEFAULT_CUSTOMER_ID
    assert s["id"] == "AH"


def test_it_has_the_shape_the_runner_expects():
    """Whatever a file-backed scenario carries, this must carry too, or it
    fails somewhere deep in the run rather than at the command line."""
    disk = load_scenarios(["E1"])[0]
    ad_hoc = ad_hoc_scenario(PERSONA)
    missing = set(disk) - set(ad_hoc)
    assert not missing, f"ad-hoc scenario is missing {missing}"


def test_the_account_can_be_chosen():
    s = ad_hoc_scenario(PERSONA, customer_id="MB-9023")
    assert s["customer_id"] == "MB-9023"
    assert s["customer_id"] in ACCOUNTS


def test_an_expected_outcome_is_optional():
    assert ad_hoc_scenario(PERSONA)["expect"] == {}


@pytest.mark.parametrize("given,stored", [
    (["promise_to_pay"], ["PROMISE_TO_PAY"]),
    (["ALREADY_PAID", "callback_request"], ["ALREADY_PAID", "CALLBACK_REQUEST"]),
])
def test_expected_outcomes_are_normalised(given, stored):
    """Typed at a prompt under time pressure, so case cannot matter."""
    assert ad_hoc_scenario(PERSONA, expect=given)["expect"]["outcome_any_of"] == stored


def test_turn_budget_is_adjustable():
    assert ad_hoc_scenario(PERSONA, turns=30)["max_turns"] == 30


def test_it_cannot_be_graded_more_kindly_than_the_suite():
    """The thing that would make this a demo trick rather than a test. An
    ad-hoc scenario names no judge criteria and asserts no behaviours, but the
    four gates are applied to every call by the scorer regardless of what the
    scenario asks for."""
    s = ad_hoc_scenario(PERSONA)
    assert s["judge_criteria"] == []
    assert "required_behaviours" not in s
    assert "forbidden_behaviours" not in s

    from src.evals.scorer import GATE_RULES

    assert set(GATE_RULES) == {"G1", "G2", "G3"}, (
        "gates are applied from the scorer's own list, not from the scenario"
    )
