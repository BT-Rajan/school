import pytest
from sqlalchemy import select

from app.models import AuditLog, MfaMethod, Role, User

from .helpers import (
    deliver_mail,
    make_cluster,
    make_school,
    make_user,
    seed_reference,
    signed_in,
    teacher_body,
)


@pytest.fixture
def district(new_client, outbox):
    """Two clusters, each with a Cluster Head and a school, plus an admin."""
    seed_reference()
    admin_client, admin = signed_in(
        new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP, staff_id="A1"
    )
    head_a_client, head_a = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "heada@example.org", staff_id="CHA")
    head_b_client, head_b = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "headb@example.org", staff_id="CHB")
    cluster_a = make_cluster("CA", head_a)
    cluster_b = make_cluster("CB", head_b)
    school_a = make_school(cluster_a, "SA1", "مدرسة الأمل")
    school_b = make_school(cluster_b, "SB1", "Hope School")
    return {
        "admin": admin_client,
        "head_a": head_a_client,
        "head_b": head_b_client,
        "cluster_a": cluster_a,
        "cluster_b": cluster_b,
        "school_a": school_a,
        "school_b": school_b,
        "admin_user": admin,
    }


def test_cluster_head_sees_only_own_cluster(district):
    a = district["head_a"]
    codes = [s["code"] for s in a.get("/api/schools").json()["items"]]
    assert codes == ["SA1"]
    # Another cluster's school by ID is 404, and the denial is audited.
    r = a.get(f"/api/schools/{district['school_b'].id}")
    assert r.status_code == 404
    assert [c["code"] for c in a.get("/api/clusters").json()] == ["CA"]


def test_out_of_scope_access_is_audited(district, db):
    district["head_a"].get(f"/api/schools/{district['school_b'].id}")
    denial = db.execute(select(AuditLog).where(AuditLog.action == "permission.denied")).scalars().first()
    assert denial.entity_type == "school" and denial.entity_id == str(district["school_b"].id)


def test_create_school_in_own_cluster_only(district):
    body = {
        "code": "SA2",
        "name": "New School",
        "address": "Road 2",
        "school_type": "secondary",
        "medium": "english",
        "contact_phone": "+96511111111",
    }
    a = district["head_a"]
    assert a.post("/api/schools", json={**body, "cluster_id": district["cluster_a"].id}).status_code == 201
    r = a.post("/api/schools", json={**body, "code": "SB2", "cluster_id": district["cluster_b"].id})
    assert r.status_code == 404
    r = a.post("/api/schools", json={**body, "cluster_id": district["cluster_a"].id})
    assert r.status_code == 409 and r.json()["error"]["code"] == "code_taken"


def test_optimistic_locking_on_school_update(district):
    a = district["head_a"]
    school = a.get(f"/api/schools/{district['school_a'].id}").json()
    first = a.patch(f"/api/schools/{school['id']}", json={"version": school["version"], "name": "Renamed"})
    assert first.status_code == 200
    stale = a.patch(f"/api/schools/{school['id']}", json={"version": school["version"], "name": "Other"})
    assert stale.status_code == 409
    assert stale.json()["error"]["detail"]["current"]["name"] == "Renamed"


def test_search_folds_arabic_letter_forms(district):
    admin = district["admin"]
    # Stored as "مدرسة الأمل"; searching with a plain alef and taa marbuta written as haa still finds it.
    found = admin.get("/api/schools", params={"q": "مدرسه الامل"}).json()["items"]
    assert [s["code"] for s in found] == ["SA1"]
    assert [s["code"] for s in admin.get("/api/schools", params={"q": "HOPE"}).json()["items"]] == ["SB1"]


def test_teacher_lifecycle(district, outbox):
    a = district["head_a"]
    r = a.post("/api/teachers", json=teacher_body(district["school_a"].id))
    assert r.status_code == 201, r.text
    teacher = r.json()
    assert teacher["designation"]["code"] == "T1"
    assert [s["code"] for s in teacher["subjects"]] == ["MATH", "SCI"]
    assert teacher["cluster"]["code"] == "CA" and teacher["district"] == "KW-01"
    assert teacher["account_status"] == "invited"
    deliver_mail()
    assert any(m.to == "teacher@example.org" and "invite" in m.text.lower() for m in outbox)

    # Duplicate teacher ID or email is rejected.
    dup = a.post("/api/teachers", json=teacher_body(district["school_a"].id, email="other@example.org"))
    assert dup.json()["error"]["code"] == "staff_id_taken"

    # Unknown reference values are rejected.
    bad = a.post(
        "/api/teachers",
        json=teacher_body(district["school_a"].id, staff_id="T-2", email="t2@example.org", subjects=["NOPE"]),
    )
    assert bad.json()["error"]["code"] == "reference_unknown"

    updated = a.patch(
        f"/api/teachers/{teacher['id']}",
        json={"version": teacher["version"], "subjects": ["ARB"], "experience_years": 9},
    )
    assert updated.status_code == 200, updated.text
    assert [s["code"] for s in updated.json()["subjects"]] == ["ARB"]
    assert updated.json()["version"] > teacher["version"]

    # The other cluster's head cannot see the teacher.
    assert district["head_b"].get(f"/api/teachers/{teacher['id']}").status_code == 404


def test_contact_teacher_and_transfer(district):
    a = district["head_a"]
    school_a2 = make_school(district["cluster_a"], "SA2")
    teacher = a.post("/api/teachers", json=teacher_body(district["school_a"].id)).json()
    school = a.put(f"/api/schools/{district['school_a'].id}/contact", json={"teacher_id": teacher["id"]}).json()
    assert school["contact_teacher"]["teacher_id"] == teacher["id"]

    # Cross-cluster transfers are rejected; same-cluster transfers end the contact designation.
    r = a.post(f"/api/teachers/{teacher['id']}/transfer", json={"school_id": district["school_b"].id})
    assert r.status_code == 404
    r = a.post(f"/api/teachers/{teacher['id']}/transfer", json={"school_id": school_a2.id})
    assert r.status_code == 200 and r.json()["school"]["code"] == "SA2"
    assert a.get(f"/api/schools/{district['school_a'].id}").json()["contact_teacher"] is None
    history = a.get(f"/api/schools/{district['school_a'].id}/contacts").json()
    assert history[0]["end_date"] is not None
    assert len(a.get(f"/api/teachers/{teacher['id']}/transfers").json()) == 1


def test_custom_fields_validated(district):
    admin = district["admin"]
    field = admin.post(
        "/api/custom-fields",
        json={
            "entity": "teacher",
            "key": "civil_id",
            "field_type": "text",
            "label_en": "Civil ID",
            "label_ar": "الرقم المدني",
            "required": True,
            "validation": {"max_length": 12},
        },
    )
    assert field.status_code == 201, field.text
    a = district["head_a"]
    missing = a.post("/api/teachers", json=teacher_body(district["school_a"].id))
    assert missing.json()["error"]["code"] == "custom_fields_invalid"
    ok = a.post("/api/teachers", json=teacher_body(district["school_a"].id, custom={"civil_id": "290010112345"}))
    assert ok.status_code == 201 and ok.json()["custom"] == {"civil_id": "290010112345"}
    # Retiring a field hides it but keeps stored values.
    admin.post(f"/api/custom-fields/{field.json()['id']}/retire")
    teacher = a.get(f"/api/teachers/{ok.json()['id']}").json()
    assert teacher["custom"] == {"civil_id": "290010112345"}


def test_custom_field_limit(district):
    admin = district["admin"]
    for i in range(15):
        r = admin.post(
            "/api/custom-fields",
            json={"entity": "school", "key": f"f{i}", "field_type": "yes_no", "label_en": f"F{i}", "label_ar": f"ح{i}"},
        )
        assert r.status_code == 201
    r = admin.post(
        "/api/custom-fields",
        json={"entity": "school", "key": "f15", "field_type": "yes_no", "label_en": "F15", "label_ar": "ح15"},
    )
    assert r.json()["error"]["code"] == "custom_field_limit"


def test_reference_values_are_retired_not_deleted(district):
    admin = district["admin"]
    created = admin.post("/api/reference/subject", json={"code": "ENG", "name_en": "English", "name_ar": "الإنجليزية"})
    assert created.status_code == 201
    admin.post(f"/api/reference-values/{created.json()['id']}/retire")
    codes = [v["code"] for v in admin.get("/api/reference/subject").json()]
    assert "ENG" not in codes
    codes = [v["code"] for v in admin.get("/api/reference/subject", params={"include_retired": True}).json()]
    assert "ENG" in codes
    assert (
        district["head_a"]
        .post("/api/reference/subject", json={"code": "X", "name_en": "X", "name_ar": "س"})
        .status_code
        == 403
    )


def test_two_admin_rule(new_client, outbox):
    """Deactivating an admin is blocked if fewer than two active admins would remain (FR-AD5)."""
    client, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "a1@example.org", mfa=MfaMethod.TOTP)
    second, _ = make_user(Role.DISTRICT_ADMIN, "a2@example.org", mfa=MfaMethod.TOTP)
    r = client.post(f"/api/users/{second.id}/deactivate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_admins"
    third, _ = make_user(Role.DISTRICT_ADMIN, "a3@example.org", mfa=MfaMethod.TOTP)
    assert client.post(f"/api/users/{third.id}/deactivate").status_code == 200


def test_cluster_head_with_clusters_cannot_be_deactivated(district, db):
    head = db.execute(select(User).where(User.email == "heada@example.org")).scalar_one()
    r = district["admin"].post(f"/api/users/{head.id}/deactivate")
    assert r.json()["error"]["code"] == "cluster_head_has_clusters"


def test_cluster_head_vacancy_reassignment(district, db, new_client, outbox):
    """FR-AS8: the admin points the cluster at another Cluster Head."""
    new_head_client, new_head = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "headc@example.org")
    cluster = district["admin"].get(f"/api/clusters/{district['cluster_a'].id}").json()
    r = district["admin"].patch(
        f"/api/clusters/{cluster['id']}", json={"version": cluster["version"], "cluster_head_id": new_head.id}
    )
    assert r.status_code == 200
    assert [s["code"] for s in new_head_client.get("/api/schools").json()["items"]] == ["SA1"]
    assert district["head_a"].get("/api/schools").json()["items"] == []


def test_deactivated_user_is_signed_out(district, new_client, outbox):
    a = district["head_a"]
    sup = a.post(
        "/api/supervisors",
        json={"staff_id": "S1", "name": "Sup", "email": "sup@example.org", "cluster_id": district["cluster_a"].id},
    ).json()
    r = a.post(f"/api/users/{sup['user_id']}/deactivate")
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    assert a.get(f"/api/supervisors/{sup['id']}").json()["status"] == "inactive"
    # Another cluster's head cannot reactivate them.
    assert district["head_b"].post(f"/api/users/{sup['user_id']}/reactivate").status_code == 404


# Permission matrix: every role against the structure endpoints (section 19).

ROLES = [Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR, Role.TEACHER, Role.FORM_AUTHOR]
MATRIX = [
    ("GET", "/api/clusters", {Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD}),
    ("POST", "/api/clusters", {Role.DISTRICT_ADMIN}),
    # Supervisors list only the schools assigned to them, and those schools' teachers.
    ("GET", "/api/schools", {Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR}),
    ("GET", "/api/teachers", {Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR}),
    ("GET", "/api/supervisors", {Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD}),
    ("GET", "/api/admins", {Role.DISTRICT_ADMIN}),
    ("POST", "/api/admins", {Role.DISTRICT_ADMIN}),
    ("GET", "/api/cluster-heads", {Role.DISTRICT_ADMIN}),
    ("GET", "/api/admin/settings", {Role.DISTRICT_ADMIN}),
    ("GET", "/api/admin/status", {Role.DISTRICT_ADMIN}),
    ("GET", "/api/admin/locked-accounts", {Role.DISTRICT_ADMIN}),
    ("POST", "/api/custom-fields", {Role.DISTRICT_ADMIN}),
    ("GET", "/api/exports/schools", {Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD}),
]


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r.value)
def test_permission_matrix(role, new_client, outbox):
    client, _ = signed_in(
        new_client,
        outbox,
        role,
        f"{role.value}@example.org",
        mfa=MfaMethod.TOTP if role in (Role.DISTRICT_ADMIN, Role.FORM_AUTHOR) else MfaMethod.EMAIL,
    )
    for method, path, allowed in MATRIX:
        response = client.request(method, path, json={})
        if role in allowed:
            assert response.status_code not in (401, 403, 404), (method, path, response.status_code)
        else:
            assert response.status_code == 403, (role, method, path, response.status_code)


def test_form_author_sees_no_district_data(new_client, outbox):
    cluster = make_cluster("CX")
    school = make_school(cluster, "SX1")
    client, _ = signed_in(new_client, outbox, Role.FORM_AUTHOR, "author@example.org", mfa=MfaMethod.TOTP)
    assert client.get(f"/api/schools/{school.id}").status_code == 403
    assert client.get("/api/teachers/1").status_code == 404
    assert client.get("/api/supervisors/1").status_code == 404
