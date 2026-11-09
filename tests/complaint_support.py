"""Helpers shared by the tests that submit complaints."""

from uuid import uuid4

COMPLAINTS = "/complaints"
DESCRIPTION = "The air conditioner does not cool."


def own_room_id(client, headers) -> str:
    """The id of the room of the caller's first active lease.

    A caller without an active lease, or one who may not read leases, gets a
    random id, so that a submission still names a room and the refusal under
    test is the only one that can happen.
    """
    response = client.get("/me/leases", headers=headers)
    if response.status_code == 200 and response.json()["items"]:
        return response.json()["items"][0]["room"]["id"]
    return str(uuid4())


def submit_complaint(
    client, headers, description: str = DESCRIPTION, room_id: str | None = None
):
    """Submit a complaint for `room_id`, or for the caller's own room by default."""
    if room_id is None:
        room_id = own_room_id(client, headers)
    return client.post(
        COMPLAINTS,
        json={"description": description, "roomId": str(room_id)},
        headers=headers,
    )
