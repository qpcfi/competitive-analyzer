from typing import Any


def count_schema_stats(schema: dict[str, Any]) -> dict[str, int]:
    fields = [
        field
        for group in schema.values()
        if isinstance(group, list)
        for field in group
        if isinstance(field, dict)
    ]
    return {
        "total_fields": len(fields),
        "user_defined": len([field for field in fields if field.get("origin") == "user"]),
        "agent_supplement": len([field for field in fields if field.get("origin") != "user"]),
    }


def source_stats(materials: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "accepted": len([item for item in materials if item.get("validation_status") == "accepted"]),
        "degraded": len([item for item in materials if item.get("validation_status") == "degraded"]),
        "failed": len([item for item in materials if item.get("access_status") == "failed"]),
        "blocked": len([item for item in materials if item.get("access_status") == "blocked"]),
    }
