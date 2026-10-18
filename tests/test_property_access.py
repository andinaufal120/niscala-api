"""Which properties a user may reach, by role, ownership and assignment."""

from uuid import uuid4

import pytest
from sqlalchemy import delete


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def get_property(db_session, user, property_id):
    from app.access import get_accessible_property

    return get_accessible_property(db_session, user, property_id)


def listed(db_session, user):
    from app.access import accessible_properties

    return list(db_session.scalars(accessible_properties(user)))


def listed_ids(db_session, user):
    return [row.id for row in listed(db_session, user)]


def assert_not_found(db_session, user, property_id):
    from app.errors import ApiError

    with pytest.raises(ApiError) as caught:
        get_property(db_session, user, property_id)
    assert caught.value.status_code == 404
    assert caught.value.code == "PROPERTY_NOT_FOUND"
    assert caught.value.field is None


def unassign(db_session, manager, row):
    from app.models import ManagerAssignment

    db_session.execute(
        delete(ManagerAssignment).where(
            ManagerAssignment.manager_id == manager.id,
            ManagerAssignment.property_id == row.id,
        )
    )
    db_session.commit()


# get_accessible_property


def test_owner_gets_their_own_property(db_session, make_user, make_property):
    owner = make_user(role=role("owner"))
    row = make_property(owner)
    found = get_property(db_session, owner, row.id)
    assert found.id == row.id
    assert found.name == "Kos Melati"
    assert found.owner_id == owner.id


def test_owner_cannot_get_another_owners_property(db_session, make_user, make_property):
    owner = make_user(role=role("owner"))
    other = make_user(role=role("owner"))
    assert_not_found(db_session, owner, make_property(other).id)


def test_manager_gets_an_assigned_property(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner)
    assign_manager(manager, row)
    assert get_property(db_session, manager, row.id).id == row.id


def test_manager_cannot_get_an_unassigned_property(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    assigned = make_property(owner, name="Assigned")
    other = make_property(owner, name="Other")
    assign_manager(manager, assigned)
    assert_not_found(db_session, manager, other.id)


def test_manager_loses_access_as_soon_as_the_assignment_is_removed(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner)
    assign_manager(manager, row)
    assert get_property(db_session, manager, row.id).id == row.id
    unassign(db_session, manager, row)
    assert_not_found(db_session, manager, row.id)


def test_manager_cannot_get_a_property_of_an_owner_with_no_assignment(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    other_owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    assign_manager(manager, make_property(owner))
    assert_not_found(db_session, manager, make_property(other_owner).id)


def test_soft_deleted_property_is_not_found_for_its_owner(
    db_session, make_user, make_property
):
    owner = make_user(role=role("owner"))
    assert_not_found(db_session, owner, make_property(owner, deleted=True).id)


def test_soft_deleted_property_is_not_found_for_an_assigned_manager(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner, deleted=True)
    assign_manager(manager, row)
    assert_not_found(db_session, manager, row.id)


def test_view_only_property_is_still_returned_to_its_owner(
    db_session, make_user, make_property
):
    owner = make_user(role=role("owner"))
    row = make_property(owner, view_only=True)
    found = get_property(db_session, owner, row.id)
    assert found.id == row.id
    assert found.view_only is True


def test_view_only_property_is_still_returned_to_an_assigned_manager(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner, view_only=True)
    assign_manager(manager, row)
    assert get_property(db_session, manager, row.id).id == row.id


@pytest.mark.parametrize("name", ["owner", "manager", "tenant", "admin"])
def test_unknown_property_id_is_not_found(db_session, make_user, name):
    assert_not_found(db_session, make_user(role=role(name)), uuid4())


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_tenant_and_admin_never_get_a_property(
    db_session, make_user, make_property, name
):
    owner = make_user(role=role("owner"))
    row = make_property(owner)
    assert_not_found(db_session, make_user(role=role(name)), row.id)


def test_not_found_is_identical_for_missing_foreign_and_deleted_properties(
    db_session, make_user, make_property
):
    from app.errors import ApiError

    owner = make_user(role=role("owner"))
    other = make_user(role=role("owner"))
    ids = [uuid4(), make_property(other).id, make_property(owner, deleted=True).id]
    seen = set()
    for property_id in ids:
        with pytest.raises(ApiError) as caught:
            get_property(db_session, owner, property_id)
        seen.add(
            (
                caught.value.status_code,
                caught.value.code,
                caught.value.field,
                caught.value.message,
            )
        )
    assert len(seen) == 1


# accessible_properties


def test_owner_lists_only_their_own_properties(db_session, make_user, make_property):
    owner = make_user(role=role("owner"))
    other = make_user(role=role("owner"))
    mine = make_property(owner, name="Mine")
    make_property(other, name="Theirs")
    assert listed_ids(db_session, owner) == [mine.id]


def test_owner_without_properties_lists_nothing(db_session, make_user, make_property):
    owner = make_user(role=role("owner"))
    make_property(make_user(role=role("owner")))
    assert listed(db_session, owner) == []


def test_owner_listing_excludes_soft_deleted_properties(
    db_session, make_user, make_property
):
    owner = make_user(role=role("owner"))
    kept = make_property(owner, name="Kept")
    make_property(owner, name="Gone", deleted=True)
    assert listed_ids(db_session, owner) == [kept.id]


def test_owner_listing_includes_view_only_properties(
    db_session, make_user, make_property
):
    owner = make_user(role=role("owner"))
    row = make_property(owner, view_only=True)
    assert listed_ids(db_session, owner) == [row.id]


def test_manager_lists_only_assigned_properties(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    assigned = make_property(owner, name="Assigned")
    make_property(owner, name="Not assigned")
    assign_manager(manager, assigned)
    assert listed_ids(db_session, manager) == [assigned.id]


def test_manager_without_assignments_lists_nothing(
    db_session, make_user, make_property
):
    make_property(make_user(role=role("owner")))
    assert listed(db_session, make_user(role=role("manager"))) == []


def test_manager_listing_stops_including_a_property_once_unassigned(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner)
    assign_manager(manager, row)
    assert listed_ids(db_session, manager) == [row.id]
    unassign(db_session, manager, row)
    assert listed(db_session, manager) == []


def test_manager_listing_excludes_soft_deleted_properties(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    kept = make_property(owner, name="Kept")
    gone = make_property(owner, name="Gone", deleted=True)
    assign_manager(manager, kept)
    assign_manager(manager, gone)
    assert listed_ids(db_session, manager) == [kept.id]


def test_manager_listing_includes_properties_of_two_owners(
    db_session, make_user, make_property, assign_manager
):
    manager = make_user(role=role("manager"))
    first = make_property(make_user(role=role("owner")), name="A first")
    second = make_property(make_user(role=role("owner")), name="B second")
    assign_manager(manager, first)
    assign_manager(manager, second)
    assert listed_ids(db_session, manager) == [first.id, second.id]


def test_manager_does_not_see_other_properties_of_an_owner_they_work_for(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    assigned = make_property(owner, name="Assigned")
    make_property(owner, name="Sibling")
    assign_manager(manager, assigned)
    assert listed_ids(db_session, manager) == [assigned.id]


def test_two_managers_each_see_only_their_own_assignments(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    one = make_user(role=role("manager"))
    two = make_user(role=role("manager"))
    first = make_property(owner, name="First")
    second = make_property(owner, name="Second")
    assign_manager(one, first)
    assign_manager(two, second)
    assert listed_ids(db_session, one) == [first.id]
    assert listed_ids(db_session, two) == [second.id]


def test_property_assigned_to_several_managers_is_listed_once_for_each(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    one = make_user(role=role("manager"))
    two = make_user(role=role("manager"))
    row = make_property(owner)
    assign_manager(one, row)
    assign_manager(two, row)
    assert listed_ids(db_session, one) == [row.id]
    assert listed_ids(db_session, two) == [row.id]


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_tenant_and_admin_list_nothing(
    db_session, make_user, make_property, assign_manager, name
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    row = make_property(owner)
    assign_manager(manager, row)
    assert listed(db_session, make_user(role=role(name))) == []


def test_listing_is_ordered_by_name(db_session, make_user, make_property):
    owner = make_user(role=role("owner"))
    names = ["Kos Cempaka", "Kos Anggrek", "Kos Bakung"]
    for name in names:
        make_property(owner, name=name)
    assert [row.name for row in listed(db_session, owner)] == sorted(names)


def test_listing_orders_equal_names_by_id(
    db_session, make_user, make_property, assign_manager
):
    manager = make_user(role=role("manager"))
    rows = [make_property(make_user(role=role("owner"))) for _ in range(4)]
    for row in rows:
        assign_manager(manager, row)
    assert listed_ids(db_session, manager) == sorted(row.id for row in rows)


def test_manager_listing_is_ordered_by_name(
    db_session, make_user, make_property, assign_manager
):
    owner = make_user(role=role("owner"))
    manager = make_user(role=role("manager"))
    for name in ["Kos Cempaka", "Kos Anggrek", "Kos Bakung"]:
        assign_manager(manager, make_property(owner, name=name))
    assert [row.name for row in listed(db_session, manager)] == [
        "Kos Anggrek",
        "Kos Bakung",
        "Kos Cempaka",
    ]


def test_accessible_properties_is_a_select_that_can_be_narrowed(
    db_session, make_user, make_property
):
    from sqlalchemy import select

    from app.access import accessible_properties
    from app.models import Property

    owner = make_user(role=role("owner"))
    make_property(owner, name="Kos Anggrek")
    wanted = make_property(owner, name="Kos Bakung")
    query = accessible_properties(owner)
    assert isinstance(query, type(select(Property)))
    narrowed = query.where(Property.name == "Kos Bakung")
    assert [row.id for row in db_session.scalars(narrowed)] == [wanted.id]
