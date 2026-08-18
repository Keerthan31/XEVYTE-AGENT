"""
Data models for the dynamic API catalog.
Each endpoint parsed from the Java OpenAPI spec becomes a CatalogEntry.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    """Controls whether the agent auto-executes or asks for confirmation."""
    SAFE = "safe"           # GET / read-only → auto-execute
    CONFIRM = "confirm"     # POST / PUT / DELETE → show preview, await approval
    BLOCKED = "blocked"     # Admin-only or destructive endpoints the agent must never call


class ParamLocation(str, Enum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class EndpointParameter(BaseModel):
    name: str
    location: ParamLocation
    required: bool = False
    schema_type: str = "string"
    description: str = ""
    default: Any = None
    enum_values: list[str] | None = None


class CatalogEntry(BaseModel):
    """One API endpoint parsed from the Java backend's OpenAPI spec."""
    endpoint_id: str = Field(
        ...,
        description="Unique identifier e.g. 'LeaveController.applyLeave'"
    )
    method: str = Field(..., description="HTTP method: GET, POST, PUT, DELETE")
    path: str = Field(..., description="URL path template e.g. /api/leaves/apply")
    summary: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    parameters: list[EndpointParameter] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    request_body_content_type: str = "application/json"
    response_schema: dict[str, Any] | None = None
    risk_tier: RiskTier = RiskTier.SAFE

    # For semantic search
    search_text: str = Field(
        default="",
        description="Combined text blob for embedding-based search"
    )

    def build_search_text(self) -> str:
        """Combine all descriptive fields into a single searchable string."""
        parts = [
            self.summary,
            self.description,
            self.path,
            " ".join(self.tags),
            self.endpoint_id.replace(".", " ").replace("_", " "),
        ]
        self.search_text = " ".join(p for p in parts if p).lower()
        return self.search_text

    @property
    def is_mutation(self) -> bool:
        return self.method.upper() in ("POST", "PUT", "DELETE", "PATCH")

    def to_tool_description(self) -> str:
        """Human-readable summary for the LLM system prompt."""
        params_str = ""
        if self.parameters:
            param_parts = []
            for p in self.parameters:
                req = " (required)" if p.required else ""
                param_parts.append(f"  - {p.name}: {p.schema_type}{req}")
            params_str = "\n" + "\n".join(param_parts)

        body_str = ""
        if self.request_body_schema:
            body_str = f"\n  Body: {self.request_body_schema}"

        return (
            f"[{self.method}] {self.path}\n"
            f"  ID: {self.endpoint_id}\n"
            f"  Description: {self.summary or self.description or 'N/A'}\n"
            f"  Risk: {self.risk_tier.value}"
            f"{params_str}{body_str}"
        )
