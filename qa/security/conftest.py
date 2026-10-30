import os

import pytest
import requests


@pytest.fixture
def api():
    base = os.environ["QA_BASE_URL"]
    ready = requests.get(base + "/__qa/ready", timeout=5)
    ready.raise_for_status()
    assert ready.json() == {"isolated_qa": True, "run_id": os.environ["QA_RUN_ID"]}
    requests.post(base + "/__qa/control", json={}, timeout=5,
                  headers={"X-QA-Control": os.environ["QA_CONTROL_TOKEN"]}).raise_for_status()
    with requests.Session() as client:
        yield client, base


def login(client, base, username="qa-member"):
    response = client.post(base + "/api/v1/auth/login", timeout=10,
                           json={"email": f"{username}@example.com", "password": os.environ["QA_TEST_PASSWORD"]})
    assert response.status_code == 200
    return response
