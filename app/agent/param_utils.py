"""
Deterministic helpers for required-parameter discovery and date normalization.

The planner LLM is still responsible for *extracting* values from free text,
but whether a field is required — and whether a date string is well-formed —
must not depend solely on the LLM. Catalog schemas historically omit
`required: true` on body fields (0/1152 marked), so we apply conservative
heuristics here so the agent asks the user instead of calling Java APIs
with incomplete JSON.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from app.catalog.loader import EndpointSpec

# Body/DTO field names that are almost never required on write (audit, derived,
# optional flags, server-managed).
_OPTIONAL_NAME_HINTS = (
    "status", "created", "updated", "existing", "workflow", "reference",
    "reminder", "halfday", "optional", "totaldays", "employeename",
    "leaverequestid", "filename", "document", "attachment", "image",
    "lastreminder", "timeline", "version", "id",  # bare "id" often server-assigned on create
)

# Names that nearly always must be supplied by the user (or session) for writes.
_CORE_REQUIRED_NAME_HINTS = (
    "startdate", "enddate", "fromdate", "todate", "leavedate", "date",
    "leavetype", "type", "reason", "amount", "title", "category", "categoryid",
    "employeeid", "description", "comments", "comment", "subject",
)

_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_DMY = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_DATETIME_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def is_body_field_required(field: dict, *, http_method: str = "POST") -> bool:
    """Decide if a request-body / DTO field should block execution when missing."""
    if field.get("required") is True:
        return True
    if field.get("required") is False:
        return False

    name = (field.get("name") or "").lower()
    jtype = (field.get("java_type") or "").lower()

    if "optional<" in jtype:
        return False
    if any(h in name for h in _OPTIONAL_NAME_HINTS):
        return False
    if jtype in ("boolean", "bool") or jtype.endswith("boolean"):
        return False
    if http_method.upper() == "GET":
        return False

    if any(h in name for h in _CORE_REQUIRED_NAME_HINTS):
        return True

    # Remaining non-optional-looking fields on POST/PUT/PATCH: treat as required
    # so we ask rather than send half-empty DTOs. Large DTOs still skip
    # audit/flag fields via _OPTIONAL_NAME_HINTS above.
    return http_method.upper() in ("POST", "PUT", "PATCH") and bool(name)


def body_schema_for(endpoint: EndpointSpec) -> list[dict]:
    """Prefer top-level request_body_schema; fall back to multipart json_dto schema."""
    if endpoint.request_body_schema:
        return list(endpoint.request_body_schema)
    for part in endpoint.get_multipart_parts() or []:
        if part.get("part_type") == "json_dto" and part.get("schema"):
            return list(part["schema"])
    return []


def collect_required_param_names(endpoint: EndpointSpec) -> list[str]:
    """All parameter / body field names that must be present before execute."""
    names: list[str] = []
    for p in endpoint.path_params or []:
        if p.get("name"):
            names.append(p["name"])
    for p in endpoint.non_file_query_params():
        if p.get("required") and p.get("name"):
            names.append(p["name"])
    for p in endpoint.header_params or []:
        if p.get("required") and p.get("name"):
            names.append(p["name"])
    for part in endpoint.get_multipart_parts() or []:
        if part.get("required") and part.get("part_type") in ("file", "scalar") and part.get("name"):
            names.append(part["name"])
    if endpoint.http_method.upper() in ("POST", "PUT", "PATCH"):
        for field in body_schema_for(endpoint):
            if is_body_field_required(field, http_method=endpoint.http_method) and field.get("name"):
                names.append(field["name"])
        # Multipart json_dto with no schema: still require the DTO part conceptually,
        # but we ask for known fields via prompt; no single scalar name to gate on.
    # Preserve order, drop dupes
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _value_present(args: dict, body: Any, name: str) -> bool:
    if name in args and args[name] not in (None, ""):
        return True
    if isinstance(body, dict) and name in body and body[name] not in (None, ""):
        return True
    return False


def find_missing_args(
    endpoint: EndpointSpec,
    *,
    path_args: dict | None = None,
    query_args: dict | None = None,
    body: Any = None,
    employee_id: str | None = None,
) -> list[str]:
    """Return friendly missing-info questions for required params not yet filled.

    Session employee_id auto-satisfies employeeId / employee_id when present.
    """
    path_args = path_args or {}
    query_args = query_args or {}
    merged = {**query_args, **path_args}
    missing: list[str] = []
    for name in collect_required_param_names(endpoint):
        # Session identity fills self-referential employee ids
        if employee_id and name.lower() in ("employeeid", "employee_id", "empid"):
            continue
        if _value_present(merged, body, name):
            continue
        # Also accept camel/snake variants lightly
        alt = name[0].lower() + name[1:] if name else name
        if alt != name and _value_present(merged, body, alt):
            continue
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
        missing.append(f"Please provide {label}.")
    return missing


def normalize_date_string(value: Any, *, wire_format: str | None = None) -> Any:
    """Accept YYYY-MM-DD or DD-MM-YYYY; emit wire_format or ISO by default."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return value

    parsed: Optional[datetime] = None
    if _DATE_ISO.match(s[:10]):
        try:
            parsed = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            parsed = None
    elif _DATE_DMY.match(s[:10]):
        try:
            parsed = datetime.strptime(s[:10], "%d-%m-%Y")
        except ValueError:
            parsed = None

    if parsed is None:
        return value

    fmt = (wire_format or "").upper().replace("DD", "%d").replace("MM", "%m").replace("YYYY", "%Y")
    # wire_format comes as 'dd-MM-yyyy' from Java — handle both styles
    if wire_format:
        javaish = wire_format
        try:
            # Convert Java SimpleDateFormat-ish to strftime
            py = (
                javaish.replace("yyyy", "%Y")
                .replace("YYYY", "%Y")
                .replace("dd", "%d")
                .replace("DD", "%d")
                .replace("MM", "%m")
            )
            return parsed.strftime(py)
        except Exception:
            pass
        if "DD-MM-YYYY" in wire_format.upper() or wire_format.lower().startswith("dd-"):
            return parsed.strftime("%d-%m-%Y")
    return parsed.strftime("%Y-%m-%d")


def is_valid_date_string(value: Any) -> bool:
    s = str(value).strip() if value is not None else ""
    if _DATE_ISO.match(s) or _DATE_DMY.match(s):
        return True
    if _DATETIME_ISO.match(s):
        return True
    return False


def truncate_for_llm(obj: Any, max_chars: int = 8000) -> Any:
    """Keep respond/planner prompts from overflowing on huge API payloads."""
    try:
        text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    except Exception:
        text = str(obj)
    if len(text) <= max_chars:
        return obj if not isinstance(obj, str) else text
    truncated = text[:max_chars] + "...[truncated]"
    if isinstance(obj, str):
        return truncated
    return truncated


def split_compound_query(message: str) -> list[str]:
    """Split multi-intent user turns for multi-query retrieval."""
    text = (message or "").strip()
    if not text:
        return []
    # Split on " and also ", " as well as ", "; ", and standalone " and " between clauses
    parts = re.split(
        r"\b(?:and also|as well as|then also)\b|;|\n",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = [p.strip(" ,.") for p in parts if p and len(p.strip()) > 3]
    if len(cleaned) <= 1:
        # Secondary: "X and Y" when both sides look like actions
        m = re.split(r"\band\b", text, maxsplit=1, flags=re.IGNORECASE)
        if len(m) == 2 and len(m[0].split()) <= 12 and len(m[1].split()) <= 12:
            left, right = m[0].strip(), m[1].strip()
            actionish = ("show", "get", "check", "apply", "view", "list", "my", "find")
            if any(w in left.lower() for w in actionish) and any(w in right.lower() for w in actionish):
                return [left, right]
        return [text]
    return cleaned[:4]
