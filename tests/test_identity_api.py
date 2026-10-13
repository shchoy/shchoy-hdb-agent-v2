"""POC identity: the BFF forwards `X-PLG-User` (a staff ID) and plg-api builds the user from it."""

from __future__ import annotations

from tests.conftest import Api


def test_forwarded_staff_id_identifies_the_user_and_their_role(api: Api) -> None:
    response = api.client.get("/me", headers={"X-PLG-User": "S04"})

    assert response.status_code == 200
    assert response.json() == {
        "staff_id": "S04",
        "name": "Marcus Lim",
        "title": "Estate Manager (East)",
        "dept": "Estate Management",
        "role": "estate_manager",
    }


def test_roles_follow_staff_titles(api: Api) -> None:
    roles = {p["staff_id"]: p["role"] for p in api.client.get("/personas").json()}

    assert roles["S01"] == "director"
    assert roles["S02"] == "director"
    assert roles["S03"] == "manager"
    assert roles["S05"] == "officer"
    assert roles["S08"] == "analyst"
    assert roles["S09"] == "legal"
    assert roles["S12"] == "estate_manager"


def test_sign_in_screen_can_list_every_staff_persona(api: Api) -> None:
    personas = api.client.get("/personas").json()

    assert len(personas) == 12
    assert {"staff_id": "S08", "name": "Kelvin Goh"}.items() <= personas[7].items()


def test_creating_a_thread_without_a_user_is_unauthorised(api: Api) -> None:
    assert api.client.post("/threads").status_code == 401


def test_who_am_i_without_a_user_is_unauthorised(api: Api) -> None:
    assert api.client.get("/me").status_code == 401


def test_unknown_staff_id_is_unauthorised(api: Api) -> None:
    response = api.client.post("/threads", headers={"X-PLG-User": "S99"})

    assert response.status_code == 401


def test_runs_require_a_user(api: Api) -> None:
    thread_id = api.create_thread()

    response = api.client.post(f"/threads/{thread_id}/runs", json={"message": "hello"})

    assert response.status_code == 401


def test_openapi_document_publishes_run_events_for_the_web_client(api: Api) -> None:
    doc = api.client.get("/openapi.json").json()

    assert doc["openapi"].startswith("3.1")
    schemas = doc["components"]["schemas"]
    for name in ("RunEvent", "NodeEvent", "TokenEvent", "DoneEvent", "ErrorEvent", "UserCtx"):
        assert name in schemas
    stream = doc["paths"]["/threads/{thread_id}/runs"]["post"]["responses"]["200"]["content"]
    assert stream["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/RunEvent"}
