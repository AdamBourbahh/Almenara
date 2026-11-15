"""Budget guard: close public access to the Cloud Run service once the budget is spent.

Cloud Billing publishes budget notifications to a Pub/Sub topic. When the reported cost
reaches the budget amount, this function removes the ``allUsers`` invoker binding from
the service. Requests are then rejected before any instance starts, so request-driven
spending stops. The action is reversible (see docs/deploy.md).
"""

from __future__ import annotations

import base64
import json
import os

import functions_framework
import google.auth
from google.auth.transport.requests import AuthorizedSession

PUBLIC_MEMBER = "allUsers"
INVOKER_ROLE = "roles/run.invoker"


def budget_exceeded(payload: dict) -> bool:
    cost = float(payload.get("costAmount", 0.0))
    budget = float(payload.get("budgetAmount", 0.0))
    return budget > 0 and cost >= budget


def without_public_access(policy: dict) -> tuple[dict, bool]:
    """Return the policy without the public invoker member and whether it changed."""
    changed = False
    bindings = []
    for binding in policy.get("bindings", []):
        members = list(binding.get("members", []))
        if binding.get("role") == INVOKER_ROLE and PUBLIC_MEMBER in members:
            members.remove(PUBLIC_MEMBER)
            changed = True
        if members:
            bindings.append({**binding, "members": members})
    return {**policy, "bindings": bindings}, changed


@functions_framework.cloud_event
def enforce_budget(event) -> None:
    payload = json.loads(base64.b64decode(event.data["message"]["data"]))
    if not budget_exceeded(payload):
        print(f"Budget not exceeded: {payload.get('costAmount')} of {payload.get('budgetAmount')}.")
        return
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    resource = (f"https://run.googleapis.com/v2/projects/{os.environ['GUARD_PROJECT']}"
                f"/locations/{os.environ['GUARD_REGION']}/services/{os.environ['GUARD_SERVICE']}")
    response = session.get(f"{resource}:getIamPolicy", timeout=30)
    response.raise_for_status()
    policy, changed = without_public_access(response.json())
    if not changed:
        print("Budget exceeded; public access was already closed.")
        return
    session.post(f"{resource}:setIamPolicy", json={"policy": policy}, timeout=30).raise_for_status()
    print(f"Budget exceeded ({payload.get('costAmount')} >= {payload.get('budgetAmount')}): public access closed.")
