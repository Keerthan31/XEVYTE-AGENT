"""
Loads app/catalog/endpoint_catalog.json (produced by
scripts/parse_java_endpoints.py) into memory and exposes fast lookups the
rest of the agent needs. This is intentionally the ONLY place that knows
the catalog's on-disk shape — everything else asks this module for data.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from app.config import get_settings


@dataclass
class EndpointSpec:
    id: str
    module: str
    controller_class: str
    method_name: str
    http_method: str
    path: str
    path_params: list[dict] = field(default_factory=list)
    query_params: list[dict] = field(default_factory=list)
    header_params: list[dict] = field(default_factory=list)
    multipart_parts: list[dict] = field(default_factory=list)
    request_body_type: Optional[str] = None
    request_body_is_list: bool = False
    request_body_schema: Optional[list[dict]] = None
    consumes: str = "application/json"
    produces: str = "application/json"
    has_file_upload: bool = False
    auth_required: bool = True
    preauthorize: Optional[str] = None
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    destructive_hint: bool = False
    bulk_hint: bool = False
    sensitive_module_hint: bool = False
    wire_formats: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> EndpointSpec:
        """Construct EndpointSpec handling optional/missing/extra keys safely."""
        known_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        spec = cls(**filtered)
        if spec.has_file_upload and not spec.multipart_parts:
            spec.multipart_parts = spec._auto_derive_multipart_parts()
        return spec

    def _auto_derive_multipart_parts(self) -> list[dict]:
        """Auto-derive structured multipart parts from EndpointSpec attributes
        if not explicitly present in the raw catalog JSON."""
        parts = []
        # 1. File parts from query_params with MultipartFile
        for p in self.query_params:
            if p.get("java_type") == "MultipartFile" or p.get("name") in ("file", "files", "document", "attachment", "image"):
                parts.append({
                    "name": p["name"],
                    "part_type": "file",
                    "content_type": "application/octet-stream",
                    "required": p.get("required", False),
                    "java_type": p.get("java_type", "MultipartFile"),
                    "description": f"File part '{p['name']}'",
                })
        # 2. JSON DTO part if request_body_schema or request_body_type exists
        if self.request_body_type or self.request_body_schema:
            dto_name = "dto" if not self.request_body_type else self.request_body_type[0].lower() + self.request_body_type[1:]
            parts.append({
                "name": dto_name,
                "part_type": "json_dto",
                "content_type": "application/json",
                "required": True,
                "java_type": self.request_body_type or "Object",
                "schema": self.request_body_schema or [],
                "description": f"JSON DTO part '{dto_name}' ({self.request_body_type})",
            })
        # 3. Scalar parts from non-file query_params when content is multipart
        for p in self.query_params:
            if p.get("java_type") != "MultipartFile" and p.get("name") not in ("file", "files", "document", "attachment", "image"):
                parts.append({
                    "name": p["name"],
                    "part_type": "scalar",
                    "content_type": "text/plain",
                    "required": p.get("required", False),
                    "java_type": p.get("java_type", "String"),
                    "description": f"Scalar form field '{p['name']}'",
                })
        return parts

    def get_multipart_parts(self) -> list[dict]:
        if not self.multipart_parts and self.has_file_upload:
            self.multipart_parts = self._auto_derive_multipart_parts()
        return self.multipart_parts

    def non_file_query_params(self) -> list[dict]:
        """Returns query parameters excluding MultipartFile parameters."""
        return [p for p in self.query_params if p.get("java_type") != "MultipartFile"]

    def file_query_params(self) -> list[dict]:
        """Returns query parameters that are MultipartFile parameters."""
        return [p for p in self.query_params if p.get("java_type") == "MultipartFile"]

    def embedding_text(self) -> str:
        return self.description

    def as_prompt_block(self) -> str:
        """Rich, LLM-facing rendering of this endpoint used in the planning
        prompt — includes everything needed to construct a correct call."""
        lines = [f"### {self.id}", f"{self.http_method} {self.path}", f"Module: {self.module}"]
        if self.path_params:
            lines.append("Path params: " + ", ".join(f"{p['name']} ({p['java_type']})" for p in self.path_params))
        non_file_q = self.non_file_query_params()
        if non_file_q:
            parts = []
            for p in non_file_q:
                bit = f"{p['name']} ({p['java_type']}"
                if not p.get("required"):
                    bit += ", optional"
                if p.get("default") is not None:
                    bit += f", default={p['default']}"
                bit += ")"
                parts.append(bit)
            lines.append("Query params: " + ", ".join(parts))
        if self.header_params:
            lines.append("Header params: " + ", ".join(f"{p['name']} ({p.get('java_type', 'String')})" for p in self.header_params))
        if self.request_body_type:
            lines.append(f"Request body ({'array of ' if self.request_body_is_list else ''}{self.request_body_type}):")
            if self.request_body_schema:
                for f in self.request_body_schema:
                    lines.append(f"  - {f['name']}: {f['java_type']}")
            else:
                lines.append("  (free-form JSON object — infer reasonable keys from the user's request)")
        mp_parts = self.get_multipart_parts()
        if mp_parts:
            lines.append("Multipart form-data parts:")
            for pt in mp_parts:
                lines.append(f"  - part '{pt['name']}' ({pt['part_type']}, {pt['content_type']}, {'required' if pt.get('required') else 'optional'})")
        elif self.has_file_upload:
            lines.append("Accepts a file upload (multipart/form-data).")
        if not self.auth_required:
            lines.append("No authentication required.")
        if self.preauthorize:
            lines.append(f"Backend authorization rule: {self.preauthorize}")
        return "\n".join(lines)


class CatalogValidationResult(NamedTuple if False else object):
    def __init__(self, valid: bool, endpoint_count: int, errors: list[str]):
        self.valid = valid
        self.endpoint_count = endpoint_count
        self.errors = errors


class Catalog:
    def __init__(self, endpoints: list[EndpointSpec]):
        self._by_id: dict[str, EndpointSpec] = {e.id: e for e in endpoints}
        self._all = endpoints

    @property
    def endpoints(self) -> list[EndpointSpec]:
        return self._all

    def get(self, endpoint_id: str) -> Optional[EndpointSpec]:
        return self._by_id.get(endpoint_id)

    def modules(self) -> list[str]:
        return sorted({e.module for e in self._all})

    def by_module(self, module: str) -> list[EndpointSpec]:
        return [e for e in self._all if e.module.lower() == module.lower()]

    def validate(self) -> CatalogValidationResult:
        """FIX 16: Startup validation of catalog integrity."""
        errors: list[str] = []
        if len(self._all) < 600:
            errors.append(f"Catalog has {len(self._all)} endpoints; expected baseline ~633.")
        seen_ids = set()
        for e in self._all:
            if not e.id:
                errors.append("Endpoint missing required 'id' field.")
            elif e.id in seen_ids:
                errors.append(f"Duplicate endpoint ID found: '{e.id}'")
            seen_ids.add(e.id)

            if not e.path or not e.http_method:
                errors.append(f"Endpoint '{e.id}' missing path or http_method.")

            for p in e.path_params:
                if "name" not in p:
                    errors.append(f"Endpoint '{e.id}' path_param missing 'name'.")
            for q in e.query_params:
                if "name" not in q:
                    errors.append(f"Endpoint '{e.id}' query_param missing 'name'.")

        valid = len(errors) == 0
        return CatalogValidationResult(valid=valid, endpoint_count=len(self._all), errors=errors)

    def __len__(self) -> int:
        return len(self._all)


_lock = threading.Lock()
_catalog: Optional[Catalog] = None


def load_catalog(path: Optional[str] = None) -> Catalog:
    """Load (or reload) the catalog from disk. Thread-safe, cached in
    memory — validates integrity on load per FIX 16."""
    global _catalog
    settings = get_settings()
    catalog_path = Path(path or settings.ENDPOINT_CATALOG_PATH)
    if not catalog_path.exists():
        raise FileNotFoundError(
            f"Endpoint catalog not found at {catalog_path}. Run: "
            f"python scripts/parse_java_endpoints.py --src <path-to-java-source> --out app/catalog"
        )
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    from dataclasses import fields
    endpoints = [EndpointSpec.from_dict(e) for e in raw]
    catalog = Catalog(endpoints)
    val_result = catalog.validate()
    if not val_result.valid:
        # Log warnings or fail if severe mismatch
        import logging
        logger = logging.getLogger(__name__)
        for err in val_result.errors:
            logger.warning("Catalog Integrity Warning: %s", err)
    with _lock:
        _catalog = catalog
    return _catalog


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        return load_catalog()
    return _catalog

