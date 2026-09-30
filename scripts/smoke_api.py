"""Exercise the local issuer and actual API without printing access tokens."""

import json
import urllib.error
import urllib.request
from uuid import uuid4


def request(url, *, token=None, payload=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            value = response.read()
            return response.status, json.loads(value) if value else None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    api = "http://localhost:8000"
    tokens = {}
    workspaces = {}
    suffix = uuid4().hex[:8]
    for user in ("alice", "bob"):
        status, data = request("http://localhost:8081/token", payload={"user": user})
        assert status == 200, f"Local issuer failed: {status}"
        tokens[user] = data["access_token"]
        status, data = request(
            api + "/v1/workspaces", token=tokens[user], payload={"name": f"Smoke {user} {suffix}"}
        )
        assert status == 201, f"Workspace creation failed: {status}"
        workspaces[user] = data["id"]
    root = api + f"/v1/workspaces/{workspaces['alice']}/portfolios"
    status, data = request(root, token=tokens["alice"], payload={"name": "Smoke portfolio"})
    assert status == 201, f"Portfolio creation failed: {status}"
    item = data["id"]
    status, _ = request(root + "/" + item, token=tokens["alice"])
    assert status == 200
    status, _ = request(root + "/" + item, token=tokens["bob"])
    assert status == 404, "Cross-tenant read was not denied"
    status, _ = request(root + "/" + item, token=tokens["bob"], method="DELETE")
    assert status == 404, "Cross-tenant delete was not denied"
    status, _ = request(root + "/" + item, token=tokens["alice"], method="DELETE")
    assert status == 204
    print("PASS: signed login, two workspaces, portfolio CRUD, and cross-tenant denial over HTTP.")
    print("Demo workspaces and audit records are retained; the smoke portfolio was deleted.")


if __name__ == "__main__":
    main()
