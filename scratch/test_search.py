import os
import sys
import json

# Add the project root to python path
sys.path.append('d:/XEVYTE-AGENT-main')

from app.agent.tools import APIECatalog

query = "Allocate a laptop to an employee"
results = APIECatalog.search_by_intent(query)
print("=== Search Results for: '{}' ===".format(query))
for r in results:
    print(r.get("endpoint_id"))
