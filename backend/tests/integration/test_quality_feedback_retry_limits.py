from services.state_machine import retry_exhausted


def test_quality_feedback_retry_limits_route_to_intervention_threshold():
    assert retry_exhausted(3)
    assert not retry_exhausted(2)
