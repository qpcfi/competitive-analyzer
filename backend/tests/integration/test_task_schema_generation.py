from services.repositories import build_field_index


def test_build_field_index_adds_stable_ids():
    schema = {"basic": [{"name": "Product Name", "type": "text"}]}
    fields = build_field_index(schema)
    assert fields == [{"name": "Product Name", "type": "text", "id": "basic.Product Name", "group": "basic"}]
