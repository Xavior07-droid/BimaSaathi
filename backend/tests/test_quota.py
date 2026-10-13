"""A27: the quota model gives sane numbers and stays in step with the code it describes."""
import pytest

from app.services import quota as Q


def test_cache_hit_and_cron_cost_nothing():
    f = Q.flows()
    assert f["ingest_cache_hit"].worst == 0 and f["reminders_cron"].worst == 0


def test_ingest_counts():
    assert Q.ingest_calls("best", with_summary=False) == 1
    assert Q.ingest_calls("best") == 2                       # extract + planned summary
    assert Q.ingest_calls("worst") == 6
    assert Q.ingest_calls("typical", extract_calls=1.5) == 2.5   # measured average replaces the optimistic default


def test_claim_scales_with_photos_and_is_capped_at_eight():
    assert Q.flows(4)["claim"].best == 5 and Q.flows(8)["claim"].best == 9
    assert Q.flows(20)["claim"].best == 9 and Q.flows(0)["claim"].best == 1
    assert Q.flows(8)["claim"].worst == 36


def test_fraud_dashboard_batches_of_twelve():
    assert Q.flows(fraud_flagged=0)["fraud_dashboard"].best == 0
    assert Q.flows(fraud_flagged=12)["fraud_dashboard"].best == 1
    assert Q.flows(fraud_flagged=15)["fraud_dashboard"].best == 2


def test_journey_is_the_sum_of_its_parts():
    # 1 upload (2) + 5 asks (5) + claim with 4 photos (5) + 1 compare (1)
    assert Q.journey_calls("typical") == 13
    assert Q.journey_calls("worst") == 6 + 5 * 4 + 4 * 5 + 4
    assert Q.journey_calls("typical", cache_hit_rate=1.0) == 11     # a cached upload saves exactly the ingest calls


def test_capacity_arithmetic():
    c = Q.capacity(250)
    assert c["ingests_best"] == 125 and c["ingests_worst"] == 41 and c["asks_per_day"] == 250
    assert c["journeys_typical"] == 19 and c["journeys_worst"] == 250 // 50
    assert Q.capacity(20)["journeys_typical"] == 1
    assert Q.capacity(0)["ingests_best"] == 0
    assert Q.per_day(10, 0) == 0


def test_rpm_pressure():
    assert Q.rpm_seconds(9, 10) == 54.0 and Q.rpm_seconds(10, 10) == 60.0


def test_report_mentions_every_flow_and_the_planned_summary():
    md = Q.markdown_report()
    for needle in ("Upload a new policy: extraction", "(planned)", "One question in Ask", "Review dashboard", "Full journeys/day", "| 250 |"):
        assert needle in md
    assert "(planned)" not in Q.markdown_report(with_summary=False).split("## Capacity")[1]


# ------------------------------------------------------------- drift guards: need the full app installed
def test_constants_match_the_code():
    from app.config import Settings
    from app.services import fraud_reason, policy_brain
    assert len(policy_brain.DEFAULT_PLAN) == Q.EXTRACT_MAX_CALLS
    assert fraud_reason.MAX_PER_CALL == Q.FRAUD_BATCH
    s = Settings(_env_file=None)
    assert s.gemini_max_retries == Q.HTTP_RETRIES and s.gemini_rpm == Q.DEFAULT_RPM


@pytest.mark.parametrize("module, fn", [("ask", "_call_gemini"), ("recommend", "recommend"), ("fraud_reason", "_reword_batch"),
                                         ("doc_classify", "classify_document"), ("exclusion_match", "_ask_model")])
def test_json_call_services_make_at_most_two_attempts_with_a_fallback(module, fn):
    """JSON_CALL_MAX = 4 assumes `for _attempt in (1, 2)` and one fallback call per attempt. If a service adds a third attempt, update quota.py."""
    import importlib
    import inspect
    src = inspect.getsource(getattr(importlib.import_module(f"app.services.{module}"), fn))
    assert "for _attempt in (1, 2)" in src
