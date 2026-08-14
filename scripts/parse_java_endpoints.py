#!/usr/bin/env python3
"""
parse_java_endpoints.py
========================
Auto-discovers every REST endpoint in the Xevyte Connect (Spring Boot) backend
by statically scanning the Java controller source — no compiled classpath,
no running server, no Maven required.

Re-run this any time the Java backend changes:

    python scripts/parse_java_endpoints.py \
        --src /path/to/employee-login-backend2/src/main/java/com/register/example \
        --out app/catalog

It writes two files:
    app/catalog/endpoint_catalog.json   - internal catalog used by the RAG/agent
    app/catalog/openapi_catalog.json    - equivalent OpenAPI 3.0.3 document

Why regex/line-scanning instead of a real Java parser (javalang/JavaParser)?
Spring MVC endpoints are declared through a very small, consistent annotation
vocabulary (@RequestMapping/@GetMapping/@PostMapping/...). A full AST parse
would need the whole Maven classpath resolved (unavailable offline) for zero
extra accuracy on the thing we actually need: annotation + method-signature
text. Paren/brace balancing (not naive regex) is used wherever nesting can
occur (generics, multipart consumes arrays, annotation attributes) so this
holds up on real, messy, 60KB controller files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

MAPPING_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    # bare @RequestMapping at method level (rare, but present) — HTTP verb
    # comes from its method=RequestMethod.X attribute, defaults to GET-ish
    # "ANY" if omitted (Spring maps it to all verbs); we mark those "ANY".
    "RequestMapping": None,
}

# Known SecurityConfig / JwtAuthenticationFilter public path rules, taken
# from Xevyte_Connect-main/employee-login-backend2 SecurityConfig.java and
# JwtAuthenticationFilter.java. Kept as data here (not re-parsed) since the
# security config format is free-form Java and hand-verifying this list once
# is safer than pattern-guessing it from source on every run. Update this
# list if SecurityConfig.java's authorizeHttpRequests(...) block changes.
PUBLIC_EXACT_PATHS = {
    "/api/auth/login",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/change-password",
    "/api/v1/auth/send-otp",
    "/api/v1/auth/verify-otp",
    "/api/daily-entry/trigger-reminders",
    "/api/resignations/trigger-exits",
    "/api/v1/analytics/deep-test",
    "/health",
}
PUBLIC_PREFIXES = (
    "/api/auth/tenant-branding/",
    "/api/auth/global-settings/",
    "/api/candidate-general-settings",
    "/api/shift-transportation/",
    "/api/travel-vendors/",
    "/travel-vendors/",
    "/escort-members/",
    "/api/escort-members/",
    "/api/shifts/",
    "/api/manager-shifts/",
    "/api/v1/applicants/",
    "/api/v1/preonboarding/",
    "/api/v1/calculations/",
    "/api/external/",
)

MULTIPART_HINT = "MultipartFile"

# Keywords used only to *hint* risk metadata stored on the catalog entry.
# The agent's guardrails module (app/guardrails/risk.py) makes the actual
# runtime decision; this is descriptive data, not policy.
DESTRUCTIVE_PATH_HINTS = ("delete", "remove", "purge", "permanent", "older-than")
BULK_PATH_HINTS = ("bulk", "-all", "/all", "batch")
SENSITIVE_MODULE_HINTS = (
    "payroll", "payslip", "salarycomponent", "compensationdetails",
    "bank", "resignation", "clearance", "offerletter", "appointmentletter",
    "itdeclaration", "insurancenominee", "grievance", "exitform",
    "publicexitform", "role", "roleaccess", "moduleaccess", "adminaccess",
)


@dataclass
class Param:
    name: str
    location: str  # path | query | header
    java_type: str
    required: bool = True
    default: Optional[str] = None


@dataclass
class Endpoint:
    id: str
    module: str
    controller_class: str
    method_name: str
    http_method: str
    path: str
    path_params: list = field(default_factory=list)
    query_params: list = field(default_factory=list)
    header_params: list = field(default_factory=list)
    multipart_parts: list = field(default_factory=list)
    request_body_type: Optional[str] = None
    request_body_is_list: bool = False
    request_body_schema: Optional[list] = None
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
    wire_formats: dict = field(default_factory=dict)


def humanize_method_name(name: str) -> str:
    """camelCase / PascalCase -> 'camel Case' style words."""
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", name)
    return s.replace("_", " ").strip().lower()


def find_matching_paren(text: str, open_idx: int) -> int:
    """Given index of an '(' character, return index of its matching ')'.
    Handles nested parens, and ignores parens inside string literals."""
    depth = 0
    i = open_idx
    in_str = False
    while i < len(text):
        c = text[i]
        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1  # unbalanced — caller should treat file as unparseable here


def extract_annotation_args(text: str, ann_start: int) -> tuple[str, int]:
    """Given the index right after '@AnnotationName', return (raw_args, end_idx).
    If the annotation has no parens (bare @GetMapping), raw_args='' and
    end_idx is ann_start."""
    j = ann_start
    while j < len(text) and text[j] in " \t":
        j += 1
    if j < len(text) and text[j] == "(":
        close = find_matching_paren(text, j)
        if close == -1:
            return "", ann_start
        return text[j + 1 : close], close + 1
    return "", ann_start


def parse_mapping_value(raw_args: str) -> list[str]:
    """Extract path string(s) from mapping annotation args, e.g.
    '"/apply"'  ->  ['/apply']
    'value = "/apply", consumes = {...}'  ->  ['/apply']
    '{"/a", "/b"}'  ->  ['/a', '/b']
    ''  ->  [] (maps to controller base path itself)
    """
    if not raw_args.strip():
        return []
    # narrow to the value=/path= segment if attributes are used, else whole thing
    m = re.search(r'(?:value|path)\s*=\s*(\{[^}]*\}|"[^"]*")', raw_args)
    segment = m.group(1) if m else raw_args
    return re.findall(r'"([^"]*)"', segment)


def parse_consumes(raw_args: str) -> tuple[str, bool]:
    if "MULTIPART_FORM_DATA" in raw_args or "multipart/form-data" in raw_args:
        return "multipart/form-data", True
    return "application/json", False


def parse_method_for_verb(raw_args: str) -> str:
    """For bare @RequestMapping(method = RequestMethod.X, ...)."""
    m = re.search(r"RequestMethod\.(\w+)", raw_args)
    if m:
        return m.group(1).upper()
    return "ANY"


def find_next_method_signature(text: str, start: int) -> Optional[tuple[str, str, int, int]]:
    """Scan forward from `start` for the next method signature:
    <modifiers> <ReturnType<Generic>> methodName(params...) {
    Returns (method_name, params_raw, sig_start_idx, open_brace_idx) or None.
    Skips over any interleaving annotations (e.g. @PreAuthorize, @Transactional).
    """
    sig_re = re.compile(
        r"public\s+(?:static\s+)?[\w\.\<\>\[\],\s\?]+?\s+(\w+)\s*\(", re.MULTILINE
    )
    m = sig_re.search(text, start)
    if not m:
        return None
    method_name = m.group(1)
    paren_open = text.index("(", m.start())
    paren_close = find_matching_paren(text, paren_open)
    if paren_close == -1:
        return None
    params_raw = text[paren_open + 1 : paren_close]
    # find the opening brace of the method body after the params close
    brace_idx = text.find("{", paren_close)
    return method_name, params_raw, m.start(), brace_idx


def split_top_level_params(params_raw: str) -> list[str]:
    """Split a Java parameter list on commas that are NOT inside <>, (), or strings."""
    parts = []
    depth_angle = depth_paren = 0
    buf = []
    for c in params_raw:
        if c == "<":
            depth_angle += 1
        elif c == ">":
            depth_angle = max(0, depth_angle - 1)
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren = max(0, depth_paren - 1)
        if c == "," and depth_angle == 0 and depth_paren == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def strip_param_annotations(raw: str) -> tuple[list[tuple[str, str]], str]:
    """Strip leading '@Annotation' / '@Annotation(args)' tokens off a single
    Java parameter declaration. Annotation args here are always flat (no
    nested parens) for @PathVariable/@RequestParam/@RequestBody in this
    codebase, so a non-nesting '[^()]*' is safe and — critically — anchored
    by a real ')' when parens are present, unlike a bare-annotation form
    (no parens at all) which previously had no anchor and let the greedy
    skip eat into the type/name text. Returns (annotations, remaining_tail).
    """
    anns: list[tuple[str, str]] = []
    s = raw.strip()
    ann_re = re.compile(r"^@(\w+)(\(([^()]*)\))?\s*")
    while True:
        m = ann_re.match(s)
        if not m:
            break
        anns.append((m.group(1), m.group(3) or ""))
        s = s[m.end():]
    return anns, s.strip()


def split_type_and_name(tail: str) -> tuple[str, str]:
    """'final Map<String, String> request' -> ('Map<String, String>', 'request').
    Lazy match is safe here (unlike the old pattern) because `tail` has
    already had annotations cleanly stripped — there's exactly one place
    a trailing '<varname>$' can anchor."""
    t = re.sub(r"^final\s+", "", tail.strip())
    m = re.match(r"^(.+?)\s+(\w+)$", t, re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2)
    return t, "value"


def parse_params(params_raw: str, path_template: str) -> tuple[list[Param], list[Param], list[Param], list[dict], Optional[str], bool, bool]:
    """Returns (path_params, query_params, header_params, multipart_parts, request_body_type, body_is_list, has_file_upload)."""
    path_params: list[Param] = []
    query_params: list[Param] = []
    header_params: list[Param] = []
    multipart_parts: list[dict] = []
    body_type: Optional[str] = None
    body_is_list = False
    has_file = False

    declared_path_var_names = set(re.findall(r"\{(\w+)\}", path_template))

    for raw in split_top_level_params(params_raw):
        if not raw or raw == "HttpServletRequest request":
            continue
        if MULTIPART_HINT in raw:
            has_file = True

        anns, tail = strip_param_annotations(raw)
        ann_map = dict(anns)

        if "PathVariable" in ann_map:
            args = ann_map["PathVariable"]
            am = re.search(r'"(\w+)"', args) if args else None
            explicit_name = am.group(1) if am else None
            jtype, varname = split_type_and_name(tail)
            name = explicit_name or varname
            path_params.append(Param(name=name, location="path", java_type=jtype, required=True))

        elif "RequestParam" in ann_map:
            args = ann_map["RequestParam"]
            explicit_name = None
            required = True
            default = None
            if args:
                nm = re.search(r'(?:value|name)\s*=\s*"(\w+)"', args)
                if nm:
                    explicit_name = nm.group(1)
                else:
                    bare = re.match(r'^\s*"(\w+)"\s*$', args)
                    if bare:
                        explicit_name = bare.group(1)
                if re.search(r"required\s*=\s*false", args):
                    required = False
                dv = re.search(r'defaultValue\s*=\s*"([^"]*)"', args)
                if dv:
                    default = dv.group(1)
                    required = False
            jtype, varname = split_type_and_name(tail)
            name = explicit_name or varname
            query_params.append(Param(name=name, location="query", java_type=jtype, required=required, default=default))

        elif "RequestHeader" in ann_map:
            args = ann_map["RequestHeader"]
            explicit_name = None
            required = True
            if args:
                nm = re.search(r'(?:value|name)\s*=\s*"([^"]+)"', args)
                if nm:
                    explicit_name = nm.group(1)
                else:
                    bare = re.match(r'^\s*"([^"]+)"\s*$', args)
                    if bare:
                        explicit_name = bare.group(1)
                if re.search(r"required\s*=\s*false", args):
                    required = False
            jtype, varname = split_type_and_name(tail)
            name = explicit_name or varname
            header_params.append(Param(name=name, location="header", java_type=jtype, required=required))

        elif "RequestPart" in ann_map:
            args = ann_map["RequestPart"]
            explicit_name = None
            required = True
            if args:
                nm = re.search(r'(?:value|name)\s*=\s*"([^"]+)"', args)
                if nm:
                    explicit_name = nm.group(1)
                else:
                    bare = re.match(r'^\s*"([^"]+)"\s*$', args)
                    if bare:
                        explicit_name = bare.group(1)
                if re.search(r"required\s*=\s*false", args):
                    required = False
            jtype, varname = split_type_and_name(tail)
            name = explicit_name or varname
            is_file = "MultipartFile" in jtype
            part_type = "file" if is_file else ("json_dto" if ("DTO" in jtype or "Request" in jtype or "Form" in jtype) else "scalar")
            content_type = "application/octet-stream" if is_file else ("application/json" if part_type == "json_dto" else "text/plain")
            multipart_parts.append({
                "name": name,
                "part_type": part_type,
                "content_type": content_type,
                "required": required,
                "java_type": jtype,
                "description": f"Multipart part '{name}' ({jtype})"
            })
            if is_file:
                has_file = True

        elif "RequestBody" in ann_map:
            jtype, _varname = split_type_and_name(tail)
            list_m = re.match(r"(?:List|java\.util\.List)<\s*([\w\.]+)\s*>", jtype)
            if list_m:
                body_is_list = True
                body_type = list_m.group(1).split(".")[-1]
            elif "<" in jtype:
                head, rest = jtype.split("<", 1)
                body_type = f"{head.split('.')[-1]}<{rest}"
            else:
                body_type = jtype.split(".")[-1]

    seen = {p.name for p in path_params}
    for var in declared_path_var_names:
        if var not in seen:
            path_params.append(Param(name=var, location="path", java_type="String", required=True))

    return path_params, query_params, header_params, multipart_parts, body_type, body_is_list, has_file


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


def build_description(module: str, http_method: str, path: str, method_name: str,
                       path_params: list[Param], query_params: list[Param],
                       body_type: Optional[str], has_file: bool,
                       body_schema: Optional[list] = None) -> str:
    words = humanize_method_name(method_name)
    bits = [f"{http_method} {path}", f"{module} module.", f"Action: {words}."]
    if path_params:
        bits.append("Path params: " + ", ".join(f"{p.name}" for p in path_params) + ".")
    if query_params:
        req = [p.name for p in query_params if p.required]
        opt = [p.name for p in query_params if not p.required]
        if req:
            bits.append("Required query params: " + ", ".join(req) + ".")
        if opt:
            bits.append("Optional query params: " + ", ".join(opt) + ".")
    if body_type:
        bits.append(f"Request body: {body_type}.")
        if body_schema:
            field_names = ", ".join(f["name"] for f in body_schema[:12])
            bits.append(f"Fields: {field_names}.")
    if has_file:
        bits.append("Accepts file upload.")
    return " ".join(bits)


FIELD_RE = re.compile(
    r"(?:private|public)\s+(?!static\b)([\w\.\<\>\[\],\s]+?)\s+(\w+)\s*(?:=[^;]+)?;"
)
CLASS_RE = re.compile(r"(?:public\s+|private\s+|static\s+)*class\s+(\w+)")
STATIC_NESTED_CLASS_RE = re.compile(r"static\s+class\s+(\w+)")


def _find_matching_brace(text: str, brace_start: int) -> int:
    depth = 0
    i = brace_start
    in_str = False
    while i < len(text):
        c = text[i]
        if c == '"' and text[i - 1] != "\\":
            in_str = not in_str
        elif not in_str:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _strip_nested_bodies(body: str) -> str:
    """Blank out any nested 'class ... { ... }' spans so a field scan of the
    OUTER class doesn't also pick up the inner class's fields (they're
    indexed separately under their own class name)."""
    out = body
    while True:
        m = re.search(r"class\s+\w+[^{]*\{", out)
        if not m:
            break
        nested_start = m.end() - 1
        nested_end = _find_matching_brace(out, nested_start)
        if nested_end == -1:
            break
        out = out[: m.start()] + out[nested_end + 1 :]
    return out


def extract_class_fields(java_file: Path, class_filter: Optional[re.Pattern] = None) -> dict[str, list[dict]]:
    """Extract '(private|public) Type name;' fields for classes in a Java
    file. Covers classic getter/setter POJOs, plain-public-field POJOs (e.g.
    PayslipRequest), and Lombok (@Data/@Getter/@Setter) classes alike — all
    of these just declare typed fields, which is all this needs (the shape,
    not the generated accessors). `class_filter`, if given, only indexes
    classes whose name matches (used to pull inner static request DTOs out
    of controller files without also matching the controller class itself).
    """
    text = java_file.read_text(encoding="utf-8", errors="replace")
    result: dict[str, list[dict]] = {}
    scan_re = class_filter or CLASS_RE
    for cm in scan_re.finditer(text):
        class_name = cm.group(1)
        brace_start = text.find("{", cm.end())
        if brace_start == -1:
            continue
        end = _find_matching_brace(text, brace_start)
        if end == -1:
            continue
        body = _strip_nested_bodies(text[brace_start:end])
        fields = []
        for fm in FIELD_RE.finditer(body):
            ftype, fname = fm.group(1).strip(), fm.group(2)
            preceding = body[max(0, fm.start() - 200) : fm.start()]
            wire_format = None
            jf_match = re.search(r'@JsonFormat\([^)]*pattern\s*=\s*"([^"]+)"', preceding)
            if jf_match:
                wire_format = jf_match.group(1)
            field_dict = {"name": fname, "java_type": ftype}
            if wire_format:
                field_dict["wire_format"] = wire_format
            fields.append(field_dict)
        if fields:
            result[class_name] = fields
    return result


def build_schema_index(example_root: Path) -> dict[str, list[dict]]:
    """Scan payload/, dto/, entity/ (all classes) and controller/ (inner
    'static class' request DTOs only) for field schemas, keyed by class
    name."""
    index: dict[str, list[dict]] = {}
    # priority order: entity first (loaded, then overwritten by more specific
    # payload/dto definitions if a name collides — request bodies are almost
    # always payload/dto types, not raw entities)
    for sub in ("entity", "dto", "payload"):
        d = example_root / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.java")):
            try:
                index.update(extract_class_fields(f))
            except Exception:
                continue
    controller_dir = example_root / "controller"
    if controller_dir.exists():
        for f in sorted(controller_dir.glob("*.java")):
            try:
                index.update(extract_class_fields(f, class_filter=STATIC_NESTED_CLASS_RE))
            except Exception:
                continue
    return index


def resolve_schema(body_type: Optional[str], schema_index: dict[str, list[dict]]) -> Optional[list]:
    if not body_type:
        return None
    bare = body_type.split("<")[0].strip()
    return schema_index.get(bare)


def parse_controller_file(path: Path, schema_index: Optional[dict[str, list[dict]]] = None) -> list[Endpoint]:
    schema_index = schema_index or {}
    text = path.read_text(encoding="utf-8", errors="replace")
    class_match = re.search(r"class\s+(\w+)", text)
    controller_class = class_match.group(1) if class_match else path.stem
    module = controller_class.replace("Controller", "")

    # class-level @RequestMapping base path (first one found before the class decl)
    base_path = ""
    class_decl_idx = text.find(f"class {controller_class}")
    header = text[:class_decl_idx] if class_decl_idx != -1 else text
    base_matches = list(re.finditer(r"@RequestMapping\s*(\()", header))
    if base_matches:
        args, _ = extract_annotation_args(header, base_matches[-1].end() - 1)
        vals = parse_mapping_value(args)
        if vals:
            base_path = vals[0]

    endpoints: list[Endpoint] = []
    ann_re = re.compile(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\b")

    for m in ann_re.finditer(text):
        ann_name = m.group(1)
        # skip the class-level @RequestMapping we already consumed
        if class_decl_idx != -1 and m.start() < class_decl_idx:
            continue

        args, ann_end = extract_annotation_args(text, m.end())
        http_method = MAPPING_ANNOTATIONS[ann_name] or parse_method_for_verb(args)
        if ann_name == "RequestMapping" and "RequestMethod" not in args and not parse_mapping_value(args):
            # bare method-level @RequestMapping with nothing useful — skip
            continue

        sub_paths = parse_mapping_value(args) or [""]
        consumes, is_multipart_ann = parse_consumes(args)

        sig = find_next_method_signature(text, ann_end)
        if not sig:
            continue
        method_name, params_raw, sig_start, brace_idx = sig

        # Guard against associating this annotation with some unrelated method
        # far away in the file (e.g. if a private helper sits between two
        # endpoint annotations without its own annotation). Real controllers
        # in this codebase keep annotation directly above the method, so a
        # generous 600-char window is a safe ceiling while still tolerating
        # stacked annotations like @PreAuthorize / @Transactional in between.
        if sig_start - ann_end > 600:
            continue

        between = text[m.start() : sig_start]
        preauth_m = re.search(r'@PreAuthorize\("([^"]+)"\)', between)
        preauthorize = preauth_m.group(1) if preauth_m else None

        line_no = text.count("\n", 0, m.start()) + 1

        for sp in sub_paths:
            full_path = (base_path.rstrip("/") + "/" + sp.lstrip("/")).rstrip("/")
            full_path = "/" + full_path.lstrip("/") if full_path else base_path or "/"
            full_path = re.sub(r"/{2,}", "/", full_path)

            path_params, query_params, header_params, mp_parts, body_type, body_is_list, has_file = parse_params(params_raw, full_path)
            if is_multipart_ann:
                has_file = True
                consumes = "multipart/form-data"

            slug_path = re.sub(r"[{}]", "", full_path).strip("/").replace("/", "_").replace("-", "_") or "root"
            endpoint_id = f"{module.lower()}_{slug_path}_{http_method.lower()}_{method_name.lower()}"[:120]

            ep = Endpoint(
                id=endpoint_id,
                module=module,
                controller_class=controller_class,
                method_name=method_name,
                http_method=http_method,
                path=full_path,
                path_params=[asdict(p) for p in path_params],
                query_params=[asdict(p) for p in query_params],
                header_params=[asdict(p) for p in header_params],
                multipart_parts=mp_parts,
                request_body_type=body_type,
                request_body_is_list=body_is_list,
                request_body_schema=resolve_schema(body_type, schema_index),
                consumes=consumes,
                has_file_upload=has_file,
                auth_required=not is_public_path(full_path),
                preauthorize=preauthorize,
                source_file=str(path),
                source_line=line_no,
                destructive_hint=(http_method == "DELETE") or any(h in full_path.lower() for h in DESTRUCTIVE_PATH_HINTS),
                bulk_hint=any(h in full_path.lower() for h in BULK_PATH_HINTS),
                sensitive_module_hint=any(h in module.lower() for h in SENSITIVE_MODULE_HINTS),
            )
            ep.description = build_description(
                module, http_method, full_path, method_name, path_params, query_params,
                body_type, has_file, ep.request_body_schema
            )
            endpoints.append(ep)

    return endpoints


def dedupe(endpoints: list[Endpoint]) -> list[Endpoint]:
    seen: dict[str, int] = {}
    out: list[Endpoint] = []
    for ep in endpoints:
        key = f"{ep.http_method} {ep.path}"
        if key in seen:
            seen[key] += 1
            ep.id = f"{ep.id}_{seen[key]}"
        else:
            seen[key] = 0
        out.append(ep)
    return out


def to_openapi(endpoints: list[Endpoint]) -> dict:
    paths: dict = {}
    for ep in endpoints:
        item = paths.setdefault(ep.path, {})
        params = []
        for p in ep.path_params:
            params.append({
                "name": p["name"], "in": "path", "required": True,
                "schema": {"type": "string"},
            })
        for p in ep.query_params:
            params.append({
                "name": p["name"], "in": "query", "required": p["required"],
                "schema": {"type": "string", "default": p.get("default")},
            })
        op = {
            "operationId": ep.id,
            "tags": [ep.module],
            "summary": ep.description[:120],
            "description": ep.description,
            "parameters": params,
            "responses": {"200": {"description": "OK"}, "401": {"description": "Unauthorized"}},
            "security": [{"bearerAuth": []}] if ep.auth_required else [],
        }
        if ep.request_body_type:
            if ep.request_body_schema:
                props = {f["name"]: {"type": "string", "x-java-type": f["java_type"]} for f in ep.request_body_schema}
                schema = {"type": "object", "title": ep.request_body_type, "properties": props}
            else:
                schema = {"type": "object", "title": ep.request_body_type}
            if ep.request_body_is_list:
                schema = {"type": "array", "items": schema}
            op["requestBody"] = {
                "required": True,
                "content": {
                    ep.consumes: {"schema": schema}
                },
            }
        item[ep.http_method.lower()] = op

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Xevyte Connect HRMS API (auto-discovered)",
            "version": "1.0.0",
            "description": "Auto-generated from static analysis of the Java Spring Boot controllers. "
                            "Not hand-maintained — regenerate with scripts/parse_java_endpoints.py.",
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            }
        },
        "paths": paths,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="Path to .../com/register/example (controller/ must be inside)")
    ap.add_argument("--out", required=True, help="Output directory for catalog JSON files")
    args = ap.parse_args()

    controller_dir = Path(args.src) / "controller"
    if not controller_dir.exists():
        print(f"ERROR: {controller_dir} not found", file=sys.stderr)
        sys.exit(1)

    schema_index = build_schema_index(Path(args.src))
    print(f"Indexed {len(schema_index)} DTO/entity classes for request-body field resolution")

    all_endpoints: list[Endpoint] = []
    files = sorted(controller_dir.glob("*.java"))
    for f in files:
        try:
            all_endpoints.extend(parse_controller_file(f, schema_index))
        except Exception as e:  # keep going; report at the end
            print(f"WARN: failed to parse {f.name}: {e}", file=sys.stderr)

    all_endpoints = dedupe(all_endpoints)
    all_endpoints.sort(key=lambda e: (e.module, e.path, e.http_method))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = out_dir / "endpoint_catalog.json"
    catalog_path.write_text(json.dumps([asdict(e) for e in all_endpoints], indent=2), encoding="utf-8")

    openapi_path = out_dir / "openapi_catalog.json"
    openapi_path.write_text(json.dumps(to_openapi(all_endpoints), indent=2), encoding="utf-8")

    modules = sorted({e.module for e in all_endpoints})
    print(f"Parsed {len(files)} controller files")
    print(f"Discovered {len(all_endpoints)} endpoints across {len(modules)} modules")
    by_method: dict[str, int] = {}
    for e in all_endpoints:
        by_method[e.http_method] = by_method.get(e.http_method, 0) + 1
    for method, count in sorted(by_method.items()):
        print(f"  {method:8s} {count}")
    print(f"Wrote: {catalog_path}")
    print(f"Wrote: {openapi_path}")


if __name__ == "__main__":
    main()
