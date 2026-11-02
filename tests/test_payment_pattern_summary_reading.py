"""Showing the stored payment pattern summaries, or withholding them."""

import pytest
from payment_summary_support import all_summaries, store_summary


def patterns_url(prop) -> str:
    return f"/properties/{prop.id}/payment-patterns"


def read(client, prop, headers) -> list[dict]:
    response = client.get(patterns_url(prop), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def summary_fields(item) -> tuple:
    return item["summary"], item["summaryWithheld"]


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def subscribed(scene, subscribe_owner):
    subscribe_owner(scene.owner, "basic")


@pytest.fixture
def second_tenant(scene, make_room, make_verified_tenant):
    return make_verified_tenant(make_room(scene.prop, number="A2"), name="Ani Tenant")


# With a subscription


def test_a_stored_summary_is_shown_to_a_subscribed_owner(
    client, database, scene, lease, subscribed, fake_summarizer
):
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == ("Penyewa selalu tepat waktu.", False)


def test_a_stored_summary_is_shown_to_a_manager_of_a_subscribed_owner(
    client, database, scene, lease, subscribed, fake_summarizer
):
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    (item,) = read(client, scene.prop, scene.manager_in.headers)
    assert summary_fields(item) == ("Penyewa selalu tepat waktu.", False)


def test_no_stored_summary_is_none_and_not_withheld_with_a_subscription(
    client, scene, lease, subscribed, fake_summarizer
):
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, False)


# Without a subscription


def test_a_stored_summary_is_withheld_without_a_subscription(
    client, database, scene, lease, fake_summarizer
):
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, True)


def test_a_stored_summary_is_withheld_from_a_manager_without_a_subscription(
    client, database, scene, lease, fake_summarizer
):
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    (item,) = read(client, scene.prop, scene.manager_in.headers)
    assert summary_fields(item) == (None, True)


def test_a_stored_summary_is_withheld_after_the_subscription_expired(
    client,
    database,
    scene,
    lease,
    subscribed,
    expire_subscription,
    fake_summarizer,
):
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    expire_subscription(scene.owner)
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, True)


def test_no_stored_summary_is_none_and_not_withheld_without_a_subscription(
    client, scene, lease, fake_summarizer
):
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, False)


def test_no_stored_summary_is_not_withheld_after_the_subscription_expired(
    client, scene, lease, subscribed, expire_subscription, fake_summarizer
):
    expire_subscription(scene.owner)
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, False)


def test_the_withheld_text_is_not_sent_anywhere_in_the_response(
    client, database, scene, lease, fake_summarizer
):
    store_summary(database, lease, "Rahasia-unik-4417")
    response = client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    assert "Rahasia-unik-4417" not in response.text


# Several tenants


def test_each_tenant_shows_only_their_own_summary(
    client, database, scene, lease, second_tenant, subscribed, fake_summarizer
):
    store_summary(database, lease, "Ringkasan Budi.")
    items = {
        i["tenant"]["name"]: i for i in read(client, scene.prop, scene.owner_in.headers)
    }
    assert summary_fields(items["Budi Tenant"]) == ("Ringkasan Budi.", False)
    assert summary_fields(items["Ani Tenant"]) == (None, False)


def test_each_tenant_is_withheld_on_their_own_summary(
    client, database, scene, lease, second_tenant, fake_summarizer
):
    store_summary(database, lease, "Ringkasan Budi.")
    items = {
        i["tenant"]["name"]: i for i in read(client, scene.prop, scene.owner_in.headers)
    }
    assert summary_fields(items["Budi Tenant"]) == (None, True)
    assert summary_fields(items["Ani Tenant"]) == (None, False)


def test_two_tenants_with_summaries_each_show_their_own(
    client, database, scene, lease, second_tenant, subscribed, fake_summarizer
):
    store_summary(database, lease, "Ringkasan Budi.")
    store_summary(database, second_tenant.lease, "Ringkasan Ani.")
    items = {
        i["tenant"]["name"]: i for i in read(client, scene.prop, scene.owner_in.headers)
    }
    assert items["Budi Tenant"]["summary"] == "Ringkasan Budi."
    assert items["Ani Tenant"]["summary"] == "Ringkasan Ani."


def test_the_summary_of_a_lease_in_another_property_never_shows(
    client,
    database,
    scene,
    lease,
    subscribed,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    fake_summarizer,
):
    stranger_owner = make_user(name="Other Owner")
    room = make_room(make_property(stranger_owner, name="Kos Mawar"), number="Z1")
    stranger = make_verified_tenant(room, name="Dewi Tenant")
    store_summary(database, stranger.lease, "Ringkasan Dewi.")
    (item,) = read(client, scene.prop, scene.owner_in.headers)
    assert summary_fields(item) == (None, False)


def test_the_summary_of_an_ended_lease_never_shows(
    client,
    database,
    scene,
    lease,
    subscribed,
    make_room,
    make_verified_tenant,
    fake_summarizer,
):
    ended = make_verified_tenant(
        make_room(scene.prop, number="A3"), name="Eko Tenant", lease_ended=True
    )
    store_summary(database, ended.lease, "Ringkasan Eko.")
    names = [
        i["tenant"]["name"] for i in read(client, scene.prop, scene.owner_in.headers)
    ]
    assert names == ["Budi Tenant"]


def test_a_summary_does_not_change_the_facts(
    client, database, scene, lease, subscribed, fake_summarizer
):
    (before,) = read(client, scene.prop, scene.owner_in.headers)
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    (after,) = read(client, scene.prop, scene.owner_in.headers)
    for field in (
        "onTimeCount",
        "countedBillCount",
        "averageDaysLate",
        "arrears",
        "atRisk",
    ):
        assert after[field] == before[field]


# Reading changes nothing


def test_reading_never_calls_the_summarizer(
    client, database, scene, lease, subscribed, fake_summarizer
):
    read(client, scene.prop, scene.owner_in.headers)
    store_summary(database, lease, "Penyewa selalu tepat waktu.")
    read(client, scene.prop, scene.owner_in.headers)
    assert fake_summarizer.calls == []


def test_reading_without_a_summary_does_not_generate_one(
    client, database, scene, lease, subscribed, fake_summarizer
):
    read(client, scene.prop, scene.owner_in.headers)
    assert fake_summarizer.calls == []
    assert all_summaries(database) == []


def test_reading_leaves_the_stored_rows_unchanged(
    client, database, scene, lease, second_tenant, subscribed, fake_summarizer
):
    store_summary(database, lease, "Ringkasan Budi.")
    before = all_summaries(database)
    read(client, scene.prop, scene.owner_in.headers)
    read(client, scene.prop, scene.manager_in.headers)
    assert all_summaries(database) == before


def test_reading_without_a_subscription_leaves_the_stored_rows_unchanged(
    client, database, scene, lease, fake_summarizer
):
    store_summary(database, lease, "Ringkasan Budi.")
    before = all_summaries(database)
    read(client, scene.prop, scene.owner_in.headers)
    assert all_summaries(database) == before
    assert fake_summarizer.calls == []
