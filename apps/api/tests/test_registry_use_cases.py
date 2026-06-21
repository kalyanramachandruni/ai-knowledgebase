import uuid

import pytest

from app.application.knowledge_product.dto import CompileKnowledgeProductInput, CreateKnowledgeProductInput
from app.application.knowledge_product.exceptions import KnowledgeProductAlreadyExists
from app.application.knowledge_product.use_cases import (
    CompareVersionsUseCase,
    CompileNewVersionUseCase,
    CreateKnowledgeProductUseCase,
    TransitionStatusUseCase,
)
from app.domain.knowledge_product.value_objects import KnowledgeProductStatus, VersionBump
from tests.fakes import FakeAuditLog, FakeKnowledgeProductRepository

USER_ID = uuid.uuid4()


def _compile_input(**overrides) -> CompileKnowledgeProductInput:
    defaults = dict(
        process_steps=["Validate Address", "Select Carrier"],
        rules=[],
        policies=[],
        sla_target="2h",
        escalations=[],
        roles=[],
        tools=[],
        created_by=USER_ID,
        bump=VersionBump.MINOR,
    )
    defaults.update(overrides)
    return CompileKnowledgeProductInput(**defaults)


async def test_create_then_duplicate_key_rejected():
    repo = FakeKnowledgeProductRepository()
    audit = FakeAuditLog()
    use_case = CreateKnowledgeProductUseCase(repo, audit)

    payload = CreateKnowledgeProductInput(
        product_key="shipment_creation", name="Shipment Creation", owner="Logistics", compile_input=_compile_input()
    )
    product = await use_case.execute(payload)
    assert str(product.current_version.semver) == "1.0.0"
    assert len(audit.entries) == 1

    with pytest.raises(KnowledgeProductAlreadyExists):
        await use_case.execute(payload)


async def test_compile_new_version_then_compare():
    repo = FakeKnowledgeProductRepository()
    audit = FakeAuditLog()
    create_use_case = CreateKnowledgeProductUseCase(repo, audit)
    compile_use_case = CompileNewVersionUseCase(repo, audit)
    compare_use_case = CompareVersionsUseCase(repo)

    product = await create_use_case.execute(
        CreateKnowledgeProductInput(
            product_key="shipment_creation", name="Shipment Creation", owner="Logistics", compile_input=_compile_input()
        )
    )
    v1_id = product.current_version.id

    v2 = await compile_use_case.execute(product.id, _compile_input(sla_target="1h"))

    diff = await compare_use_case.execute(product.id, v1_id, v2.id)
    assert diff["sla"] == {"from": {"target": "2h"}, "to": {"target": "1h"}}


async def test_transition_status_use_case_enforces_domain_rules():
    repo = FakeKnowledgeProductRepository()
    audit = FakeAuditLog()
    create_use_case = CreateKnowledgeProductUseCase(repo, audit)
    transition_use_case = TransitionStatusUseCase(repo, audit)

    product = await create_use_case.execute(
        CreateKnowledgeProductInput(
            product_key="shipment_creation", name="Shipment Creation", owner="Logistics", compile_input=_compile_input()
        )
    )
    version_id = product.current_version.id

    await transition_use_case.execute(product.id, version_id, KnowledgeProductStatus.REVIEW, USER_ID)
    reloaded = await repo.get_by_id(product.id)
    assert reloaded.current_version.status is KnowledgeProductStatus.REVIEW

    with pytest.raises(Exception):
        await transition_use_case.execute(product.id, version_id, KnowledgeProductStatus.PUBLISHED, USER_ID)
