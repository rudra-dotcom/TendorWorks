import io
from datetime import date
from decimal import Decimal

from conftest import run_project
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from tender.app import create_app
from tender.schemas import SourceDocument


def test_full_workflow_has_reproducible_totals_evidence_and_exports(client, brief):
    result = run_project(client, brief)
    assert result["status"] == "draft", result["findings"]
    assert result["demo"] is True
    assert result["checkpoint"] == 3
    assert result["metrics"]["evidence_coverage"] == 1
    selected = [b for b in result["boq"] if b["selected"]]
    total = sum(Decimal(b["amount"]) for b in selected)
    assert Decimal(result["base_total"]) == total
    for b in selected:
        assert b["evidence_ids"] and b["quantity_calculation_id"] and b["amount_calculation_id"]
    assert any(b["rate_basis"] == "non_scheduled" for b in result["boq"])
    assert len({e["id"] for e in result["evidence"]}) == len(result["evidence"])
    base = f"/api/revisions/{result['revision_id']}/artifacts/"
    workbook = load_workbook(io.BytesIO(client.get(base + "boq.xlsx").content), data_only=False)
    assert {"BOQ", "Sources", "Calculations", "Assumptions", "Findings", "Adjustments"} <= set(
        workbook.sheetnames
    )
    assert "SYNTHETIC" in workbook["BOQ"]["A2"].value
    assert (
        "CONCEPT" in PdfReader(io.BytesIO(client.get(base + "estimate.pdf").content)).pages[0].extract_text()
    )
    drawing = PdfReader(io.BytesIO(client.get(base + "concept.pdf").content))
    assert len(drawing.pages) == 2
    assert client.get(base + "concept.svg").content.startswith(b"<svg")
    assert b"ENTITIES" in client.get(base + "concept.dxf").content
    doc = Document(io.BytesIO(client.get(base + "estimate.docx").content))
    assert doc.tables[0].rows[1].cells[0].text
    assert client.post(f"/api/revisions/{result['revision_id']}/run").status_code == 409


def test_missing_or_wrong_grade_rate_cannot_be_counted_as_zero(client, brief):
    result = run_project(client, {**brief, "specifications": {"rcc.grade": "M40"}})
    assert result["status"] == "incomplete"
    assert result["base_total"] is None
    row = next(b for b in result["boq"] if b["key"] == "rcc")
    assert row["unit_rate"] is None and row["amount"] is None
    assert Decimal(result["known_subtotal"]) > 0
    assert any(f["code"] == "missing_rate" for f in result["findings"])


def test_unknown_authority_needs_clarification(client, brief):
    result = run_project(
        client, {**brief, "authority": "unknown", "description": "Build a public primary school."}
    )
    assert result["status"] == "needs_input"
    assert result["base_total"] is None


def test_cross_authority_and_state_routing(client, brief):
    railway = run_project(
        client, {**brief, "authority": "railway", "description": "Build a railway staff school."}
    )
    assert railway["status"] == "draft"
    state = run_project(
        client, {**brief, "authority": "state_pwd", "state": "Maharashtra", "location": "Pune"}
    )
    assert state["status"] == "draft"
    unavailable = run_project(client, {**brief, "authority": "state_pwd", "state": "Kerala"})
    assert unavailable["status"] == "needs_input"
    bridge = run_project(
        client, {**brief, "authority": "railway", "description": "Build a railway bridge over a river."}
    )
    assert bridge["status"] == "needs_input"


def test_unsupported_design_is_visible(client, brief):
    result = run_project(client, {**brief, "building_type": "hospital"})
    assert result["status"] == "incomplete"
    assert result["design"] is None
    assert result["base_total"] is None
    assert any(f["code"] == "unsupported_design" for f in result["findings"])


def test_changed_dimensions_create_new_revision_and_preserve_old(client, brief):
    first = run_project(client, {**brief, "length": "20", "width": "15"})
    before = client.get(f"/api/revisions/{first['revision_id']}/artifacts/concept.svg").content
    updated = {**brief, "length": "24", "width": "15", "floor_area": "720"}
    response = client.post(f"/api/projects/{first['project_id']}/revisions", json=updated)
    assert response.status_code == 201
    second_id = response.json()["revision_id"]
    client.post(f"/api/revisions/{second_id}/run")
    second = client.get(f"/api/revisions/{second_id}").json()
    assert second["revision"] == 2
    assert second["base_total"] != first["base_total"]
    assert second["design"]["metrics"]["gross_floor_area"] == "720.000"
    assert client.get(f"/api/revisions/{first['revision_id']}/artifacts/concept.svg").content == before
    old_row = next(b for b in first["boq"] if b["key"] == "flooring")
    new_row = next(b for b in second["boq"] if b["key"] == "flooring")
    assert old_row["quantity"] != new_row["quantity"]


def test_geometry_conflicts_are_not_silently_ignored(client, brief):
    result = run_project(client, {**brief, "length": "20", "width": "10"})
    assert result["status"] == "incomplete"
    assert any(f["code"] == "design_inputs" for f in result["findings"])


def test_optional_items_excluded_until_selected(client, brief):
    base = run_project(client, brief)
    upgraded = run_project(client, {**brief, "selected_options": ["solar"]})
    solar = next(b for b in base["boq"] if b["key"] == "solar")
    assert not solar["selected"]
    assert Decimal(upgraded["base_total"]) - Decimal(base["base_total"]) == Decimal(solar["amount"])


def test_interrupt_survives_application_restart(settings, brief):
    with TestClient(create_app(settings)) as client:
        first = run_project(client, {**brief, "review_design": True})
        assert first["status"] == "awaiting_review"
        assert first["artifacts"]["concept.pdf"]
        assert first["base_total"] is None
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/revisions/{first['revision_id']}/review",
            json={
                "decision": "accept_design",
                "note": "Concept assumptions accepted for preliminary estimating.",
            },
        )
        assert response.status_code == 200, response.text
        result = client.get(f"/api/revisions/{first['revision_id']}").json()
        assert result["status"] == "draft", result["findings"]
        assert all(a["status"] == "accepted" for a in result["assumptions"])
        roles = [t["role"] for t in result["agent_trace"]]
        assert roles.count("quantity_estimator") == 1


def test_checkpoint_one_retrieval_is_persisted_and_advisory(settings, brief):
    settings.rag_enabled = True
    with TestClient(create_app(settings)) as client:
        gateway = client.app.state.gateway
        gateway.index_document(
            SourceDocument(
                id="advisory", title="advisory", version="1", authority="cpwd", state="Delhi",
                kind="specification", effective_from=date(2020, 1, 1),
                text="[Page 1]\nSchool accessibility and fire safety review clause.", trust="approved",
            ),
            "demo",
        )
        first = run_project(client, {**brief, "review_design": True})
        assert first["status"] == "awaiting_review"
        assert any(e["kind"] == "retrieved" for e in first["evidence"])
        retrieved = first["metrics"]["retrieved_chunks"]
        response = client.post(
            f"/api/revisions/{first['revision_id']}/review",
            json={"decision": "accept_design", "note": "Proceed with the preliminary concept."},
        )
        assert response.status_code == 200
        result = client.get(f"/api/revisions/{first['revision_id']}").json()
        assert result["metrics"]["retrieved_chunks"] == retrieved
        assert [trace["role"] for trace in result["agent_trace"]].count("retrieve_context") == 1


def test_feedback_does_not_mutate_rates_or_completed_estimate(client, brief):
    result = run_project(client, brief)
    package = client.get(f"/api/knowledge/packages/{result['pack_id']}").json()
    response = client.post(
        f"/api/revisions/{result['revision_id']}/feedback",
        json={
            "category": "price",
            "item_id": "boq:masonry",
            "comment": "Check against the current approved schedule.",
            "proposed_value": "1",
        },
    )
    assert response.status_code == 201
    reviewed = client.post(
        f"/api/feedback/{response.json()['id']}/review",
        json={
            "decision": "accepted",
            "reason": "Evaluate this proposed correction against held-out estimates.",
        },
    )
    assert reviewed.status_code == 200
    assert client.get(f"/api/knowledge/packages/{result['pack_id']}").json() == package
    assert client.get(f"/api/revisions/{result['revision_id']}").json()["base_total"] == result["base_total"]
    assert (
        client.post(
            f"/api/revisions/{result['revision_id']}/review",
            json={"decision": "mark_reviewed", "note": "Demo is not official."},
        ).status_code
        == 409
    )
