from services.repositories import new_id


def test_partial_rerun_uses_new_module_version_identity_space():
    first = new_id("result")
    second = new_id("result")

    assert first.startswith("result_")
    assert second.startswith("result_")
    assert first != second
