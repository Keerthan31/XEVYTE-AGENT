"""
Generic HTTP Request Compiler (spec sections FIX 1, FIX 3, FIX 4, FIX 5)

Constructs fully-specified, contract-driven HTTP requests from a ToolRegistryEntry
(or EndpointSpec) and resolved execution arguments. Handles:
1. Path parameter substitution with URL encoding
2. Query parameter building
3. Header parameter building (including session/identity headers)
4. JSON request bodies
5. Form-urlencoded bodies
6. Multipart form-data with named parts:
   - JSON DTO part (application/json)
   - Scalar form fields (text/plain)
   - File parts (application/octet-stream)
7. Contract-driven date/time wire serialization
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional, Sequence
from urllib.parse import quote

from app.planes.knowledge.tool_registry import ToolRegistryEntry


@dataclass
class CompiledRequest:
    method: str
    url_path: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json_body: Optional[Any] = None
    data: Optional[dict[str, Any]] = None
    files: Optional[list[tuple]] = None


def serialize_wire_value(value: Any, java_type: str | None = None, wire_format: str | None = None) -> Any:
    """FIX 5: Wire value serialization driven by contract metadata.
    Separates internal normalized value from wire-format representation."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str:
        return ""

    from app.agent.param_utils import normalize_date_string

    jtype = (java_type or "").lower()

    if wire_format or ("date" in jtype and "time" not in jtype):
        return normalize_date_string(val_str, wire_format=wire_format)

    if any(t in jtype for t in ("datetime", "instant", "timestamp", "localdatetime")):
        return normalize_date_string(val_str, wire_format=wire_format) if wire_format else val_str

    if jtype in ("boolean", "bool"):
        return str(value).lower() in ("true", "1", "yes")

    return value


class RequestCompiler:
    @staticmethod
    def compile(
        tool: ToolRegistryEntry,
        executable_arguments: dict[str, Any],
        *,
        base_url: str = "",
        bearer_token: str | None = None,
        file_inputs: dict[str, Any] | None = None,
        header_inputs: dict[str, str] | None = None,
    ) -> CompiledRequest:
        path_args = {}
        query_args = {}
        header_args = {}
        body_args = {}
        file_args = file_inputs or {}

        # Categorize inputs according to contract definitions
        path_param_names = {p["name"] for p in tool.required_parameters if p.get("location") == "path"}
        query_param_names = {p["name"] for p in (tool.required_parameters + tool.optional_parameters) if p.get("location") == "query"}
        header_param_names = {p["name"] for p in tool.header_parameters}

        for k, v in executable_arguments.items():
            if k in path_param_names:
                path_args[k] = v
            elif k in query_param_names:
                query_args[k] = v
            elif k in header_param_names:
                header_args[k] = v
            elif k in file_args:
                pass  # handled in file_args
            else:
                body_args[k] = v

        # 1. Build Path
        url_path = tool.endpoint
        for p in tool.required_parameters:
            if p.get("location") == "path":
                pname = p["name"]
                if pname not in path_args or path_args[pname] in (None, ""):
                    raise ValueError(f"Missing required path parameter '{pname}' for {tool.tool_id}")
                wire_val = serialize_wire_value(path_args[pname], p.get("java_type"), tool.wire_formats.get(pname))
                url_path = url_path.replace("{" + pname + "}", quote(str(wire_val), safe=""))

        # 2. Build Query
        params = {}
        for p in (tool.required_parameters + tool.optional_parameters):
            if p.get("location") == "query":
                pname = p["name"]
                if pname in query_args and query_args[pname] not in (None, ""):
                    params[pname] = serialize_wire_value(query_args[pname], p.get("java_type"), tool.wire_formats.get(pname))
                elif p.get("default") is not None:
                    params[pname] = p["default"]
                elif p.get("required"):
                    raise ValueError(f"Missing required query parameter '{pname}' for {tool.tool_id}")

        # 3. Build Headers
        headers = {}
        if tool.auth_required and bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if header_inputs:
            headers.update(header_inputs)
        for hp in tool.header_parameters:
            hp_name = hp["name"]
            if hp_name in header_args and header_args[hp_name] not in (None, ""):
                headers[hp_name] = str(serialize_wire_value(header_args[hp_name], hp.get("java_type")))

        # Content types
        headers["Accept"] = tool.produces or "application/json"

        json_body = None
        data_body = None
        files_tuple_list = None

        # 4. Handle Multipart requests (FIX 3 & FIX 4)
        if tool.has_file_upload or "multipart/form-data" in (tool.consumes or ""):
            files_tuple_list = []
            multipart_parts = tool.multipart_parts

            # Process structured multipart parts
            for part in multipart_parts:
                pname = part["name"]
                ptype = part.get("part_type", "scalar")
                c_type = part.get("content_type", "text/plain")

                if ptype == "file":
                    if pname in file_args:
                        fobj = file_args[pname]
                        if isinstance(fobj, tuple):
                            files_tuple_list.append((pname, fobj))
                        elif hasattr(fobj, "read"):
                            filename = getattr(fobj, "name", pname)
                            files_tuple_list.append((pname, (filename, fobj.read(), c_type)))
                        elif isinstance(fobj, (bytes, str)):
                            files_tuple_list.append((pname, (pname, fobj, c_type)))
                elif ptype == "json_dto":
                    # JSON DTO part
                    dto_data = body_args if body_args else executable_arguments
                    files_tuple_list.append((pname, (None, json.dumps(dto_data), "application/json")))
                elif ptype == "scalar":
                    val = executable_arguments.get(pname)
                    if val is not None:
                        files_tuple_list.append((pname, (None, str(val), "text/plain")))

            # Fallback if files were provided directly without explicit multipart_parts definition
            if not files_tuple_list and file_args:
                for fname, fval in file_args.items():
                    if isinstance(fval, tuple):
                        files_tuple_list.append((fname, fval))
                    elif isinstance(fval, (bytes, str)):
                        files_tuple_list.append((fname, (fname, fval, "application/octet-stream")))

        # 5. Handle standard JSON body or form-data body
        elif tool.http_method in ("POST", "PUT", "PATCH"):
            if tool.consumes == "application/x-www-form-urlencoded":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                data_body = body_args
            else:
                headers["Content-Type"] = "application/json"
                # If tool defines a request_schema, map fields into body
                if body_args:
                    json_body = body_args
                elif executable_arguments and not (path_args or query_args):
                    json_body = executable_arguments

        full_url = (base_url.rstrip("/") + url_path) if base_url else url_path
        return CompiledRequest(
            method=tool.http_method,
            url_path=full_url,
            headers=headers,
            params=params,
            json_body=json_body,
            data=data_body,
            files=files_tuple_list,
        )
