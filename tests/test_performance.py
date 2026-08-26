"""
Category 10: Performance Testing
Benchmarks execution times and latencies for catalog search, token crypto,
guardrails checks, date parsing, and JWT validation.
"""

import pytest
import time
from app.agent.tools import APIECatalog, search_api_catalog, resolve_relative_date
from app.agent.confirmation import generate_confirmation_token, verify_confirmation_token
from app.agent.engine import is_stalling_response
from app.auth.jwt_handler import validate_and_extract_token
from app.auth.guardrails import check_input_safety


def test_perf_catalog_search_speed():
    """Verify catalog search_by_intent finishes well within 50ms."""
    queries = [
        "apply for sick leave",
        "clock in attendance",
        "submit expense claim",
        "raise a ticket for hardware",
        "view my performance goals"
    ]
    
    start = time.perf_counter()
    for q in queries:
        APIECatalog.search_by_intent(q)
    elapsed = (time.perf_counter() - start) / len(queries)
    
    assert elapsed < 0.05, f"Catalog search average latency too high: {elapsed*1000:.2f}ms"


def test_perf_confirmation_token_crypto_speed(employee_claims):
    """Verify confirmation token generation + decryption takes < 20ms."""
    action = {"endpoint_id": "applyLeave", "method": "POST", "body": {"days": 2}}
    emp_id = employee_claims["employeeId"]
    
    start = time.perf_counter()
    for _ in range(50):
        t = generate_confirmation_token(action, emp_id)
        verify_confirmation_token(t, emp_id)
    elapsed = (time.perf_counter() - start) / 50
    
    assert elapsed < 0.02, f"Token crypto round-trip too slow: {elapsed*1000:.2f}ms"


def test_perf_guardrails_check_speed():
    """Verify guardrails safety check takes < 5ms."""
    text = "Could you please help me submit my travel reimbursement for 4500 rs?"
    
    start = time.perf_counter()
    for _ in range(100):
        check_input_safety(text)
    elapsed = (time.perf_counter() - start) / 100
    
    assert elapsed < 0.005, f"Guardrails check too slow: {elapsed*1000:.2f}ms"


def test_perf_jwt_validation_speed(employee_token):
    """Verify JWT decoding and claims extraction takes < 10ms."""
    start = time.perf_counter()
    for _ in range(50):
        validate_and_extract_token(employee_token)
    elapsed = (time.perf_counter() - start) / 50
    
    assert elapsed < 0.01, f"JWT validation too slow: {elapsed*1000:.2f}ms"


def test_perf_stalling_detection_speed():
    """Verify regex stalling check takes < 1ms."""
    text = "Please hold on for a moment while I retrieve your details."
    
    start = time.perf_counter()
    for _ in range(100):
        is_stalling_response(text)
    elapsed = (time.perf_counter() - start) / 100
    
    assert elapsed < 0.001, f"Stalling detection too slow: {elapsed*1000:.2f}ms"
