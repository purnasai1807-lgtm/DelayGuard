from collections import defaultdict
from typing import Any


def summarize_bottlenecks(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in requests:
        grouped[item["current_stage"]].append(item)
    result = []
    for stage, rows in grouped.items():
        delayed = [row for row in rows if row.get("status") in {"AT_RISK", "CRITICAL", "BREACHED"}]
        result.append({"stage": stage, "delay_rate": round(len(delayed) / len(rows) * 100, 1), "affected_requests": len(delayed)})
    return sorted(result, key=lambda item: item["delay_rate"], reverse=True)
