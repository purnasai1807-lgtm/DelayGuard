import csv
from datetime import datetime
from io import TextIOWrapper
from typing import Any, BinaryIO

REQUIRED = ["request_id", "department", "service_type", "request_date", "sla_deadline", "current_stage", "stage_start_time", "priority", "historical_stage_avg_hours", "historical_stage_delay_rate", "department_delay_rate", "previous_delays"]
PRIORITIES = {"Low", "Medium", "High", "Urgent"}


def validate_csv(file: BinaryIO) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reader = csv.DictReader(TextIOWrapper(file, encoding="utf-8-sig", newline=""))
    missing = [field for field in REQUIRED if field not in (reader.fieldnames or [])]
    if missing:
        return [], [{"row": 1, "message": f"Missing required fields: {', '.join(missing)}"}]
    valid, errors, seen = [], [], set()
    for row_number, row in enumerate(reader, 2):
        try:
            if not row["request_id"] or row["request_id"] in seen:
                raise ValueError("request_id is empty or duplicated")
            if row["priority"] not in PRIORITIES:
                raise ValueError("invalid priority")
            parsed = {**row}
            for field in ("request_date", "sla_deadline", "stage_start_time"):
                parsed[field] = datetime.fromisoformat(row[field].replace("Z", "+00:00"))
            for field in ("historical_stage_avg_hours", "historical_stage_delay_rate", "department_delay_rate"):
                parsed[field] = float(row[field])
                if parsed[field] < 0 or parsed[field] > 100000:
                    raise ValueError(f"invalid {field}")
            parsed["previous_delays"] = int(row["previous_delays"])
            if parsed["previous_delays"] < 0:
                raise ValueError("previous_delays cannot be negative")
            seen.add(row["request_id"])
            valid.append(parsed)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({"row": row_number, "message": str(exc)})
    return valid, errors
