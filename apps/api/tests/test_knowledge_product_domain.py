import uuid

import pytest

from app.domain.knowledge_product.entities import KnowledgeProduct
from app.domain.knowledge_product.value_objects import (
    BusinessRule,
    KnowledgeProductStatus,
    Policy,
    ProcessStep,
    Role,
    ServiceLevelAgreement,
    ToolReference,
    VersionBump,
)
from app.domain.shared.base import DomainError


def _make_product() -> KnowledgeProduct:
    product = KnowledgeProduct(product_key="shipment_creation", name="Shipment Creation", owner="Logistics")
    product.compile_new_version(
        process_steps=[ProcessStep("Validate Address", 1), ProcessStep("Select Carrier", 2)],
        rules=[BusinessRule("weight > 30kg", "use freight")],
        policies=[Policy("shipment_value > 1000", "manager approval")],
        sla=ServiceLevelAgreement("2h"),
        escalations=[],
        roles=[Role("Logistics Coordinator")],
        tools=[ToolReference("sap_create_shipment", "SAP")],
        created_by=uuid.uuid4(),
        bump=VersionBump.MAJOR,
    )
    return product


def test_first_version_is_1_0_0():
    product = _make_product()
    assert str(product.current_version.semver) == "1.0.0"
    assert product.current_version.status is KnowledgeProductStatus.DRAFT


def test_minor_bump_increments_minor_and_resets_patch():
    product = _make_product()
    v1_id = product.current_version.id
    product.compile_new_version(
        process_steps=[ProcessStep("Validate Address", 1)],
        rules=[],
        policies=[],
        sla=None,
        escalations=[],
        roles=[],
        tools=[],
        created_by=uuid.uuid4(),
        bump=VersionBump.MINOR,
    )
    assert str(product.current_version.semver) == "1.1.0"
    assert product.current_version.id != v1_id
    assert len(product.versions) == 2


def test_full_lifecycle_transitions_succeed_in_order():
    product = _make_product()
    version_id = product.current_version.id

    product.submit_for_review(version_id)
    assert product.current_version.status is KnowledgeProductStatus.REVIEW

    product.approve(version_id)
    assert product.current_version.status is KnowledgeProductStatus.APPROVED

    product.publish(version_id)
    assert product.current_version.status is KnowledgeProductStatus.PUBLISHED

    product.retire(version_id)
    assert product.current_version.status is KnowledgeProductStatus.RETIRED


@pytest.mark.parametrize(
    "from_status,bad_target",
    [
        (KnowledgeProductStatus.DRAFT, KnowledgeProductStatus.APPROVED),
        (KnowledgeProductStatus.DRAFT, KnowledgeProductStatus.PUBLISHED),
        (KnowledgeProductStatus.PUBLISHED, KnowledgeProductStatus.DRAFT),
        (KnowledgeProductStatus.RETIRED, KnowledgeProductStatus.PUBLISHED),
    ],
)
def test_illegal_transitions_are_rejected(from_status, bad_target):
    product = _make_product()
    version_id = product.current_version.id

    # walk to from_status via the legal path
    path = {
        KnowledgeProductStatus.DRAFT: [],
        KnowledgeProductStatus.REVIEW: [KnowledgeProductStatus.REVIEW],
        KnowledgeProductStatus.APPROVED: [KnowledgeProductStatus.REVIEW, KnowledgeProductStatus.APPROVED],
        KnowledgeProductStatus.PUBLISHED: [
            KnowledgeProductStatus.REVIEW,
            KnowledgeProductStatus.APPROVED,
            KnowledgeProductStatus.PUBLISHED,
        ],
        KnowledgeProductStatus.RETIRED: [
            KnowledgeProductStatus.REVIEW,
            KnowledgeProductStatus.APPROVED,
            KnowledgeProductStatus.PUBLISHED,
            KnowledgeProductStatus.RETIRED,
        ],
    }[from_status]
    for step in path:
        product.transition(version_id, step)

    with pytest.raises(DomainError):
        product.transition(version_id, bad_target)


def test_to_canonical_dict_matches_sample_shape():
    product = _make_product()
    content = product.current_version.to_canonical_dict(
        product_key=product.product_key, name=product.name, owner=product.owner
    )
    assert content["metadata"]["id"] == "shipment_creation"
    assert content["process"]["steps"] == ["Validate Address", "Select Carrier"]
    assert content["rules"] == [{"condition": "weight > 30kg", "action": "use freight"}]
    assert content["sla"] == {"target": "2h"}
