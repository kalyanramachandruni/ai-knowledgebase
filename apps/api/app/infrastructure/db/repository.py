from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.knowledge_product.entities import KnowledgeProduct, KnowledgeProductVersion
from app.domain.knowledge_product.value_objects import (
    BusinessRule,
    Escalation,
    KnowledgeProductStatus,
    Policy,
    ProcessStep,
    Role,
    SemVer,
    ServiceLevelAgreement,
    ToolReference,
)
from app.domain.shared.base import utc_now
from app.infrastructure.db.models import KnowledgeProductModel, KnowledgeProductVersionModel


def _version_to_domain(row: KnowledgeProductVersionModel) -> KnowledgeProductVersion:
    content = row.yaml_content
    sla_content = content.get("sla")
    return KnowledgeProductVersion(
        id=row.id,
        product_id=row.product_id,
        semver=SemVer.parse(row.semver),
        status=KnowledgeProductStatus(row.status),
        process_steps=[
            ProcessStep(name=name, sequence=i) for i, name in enumerate(content["process"]["steps"])
        ],
        rules=[BusinessRule(condition=r["condition"], action=r["action"]) for r in content.get("rules", [])],
        policies=[Policy(condition=p["condition"], action=p["action"]) for p in content.get("policies", [])],
        sla=ServiceLevelAgreement(target=sla_content["target"]) if sla_content else None,
        escalations=[
            Escalation(after=e["after"], escalate_to=e["escalate_to"]) for e in content.get("escalations", [])
        ],
        roles=[Role(name=name) for name in content.get("roles", [])],
        tools=[ToolReference(key=key, display_name=key) for key in content.get("tools", [])],
        created_by=row.created_by,
        source_extraction_run_id=row.source_extraction_run_id,
    )


def _product_to_domain(row: KnowledgeProductModel) -> KnowledgeProduct:
    product = KnowledgeProduct(
        id=row.id,
        product_key=row.product_key,
        name=row.name,
        owner=row.owner,
    )
    product.versions = [_version_to_domain(v) for v in row.versions]
    return product


class SqlAlchemyKnowledgeProductRepository:
    """Implements app.domain.knowledge_product.repository.KnowledgeProductRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, product_id: uuid.UUID) -> KnowledgeProduct | None:
        stmt = (
            select(KnowledgeProductModel)
            .where(KnowledgeProductModel.id == product_id)
            .options(selectinload(KnowledgeProductModel.versions))
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _product_to_domain(row) if row else None

    async def get_by_key(self, product_key: str) -> KnowledgeProduct | None:
        stmt = (
            select(KnowledgeProductModel)
            .where(KnowledgeProductModel.product_key == product_key)
            .options(selectinload(KnowledgeProductModel.versions))
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _product_to_domain(row) if row else None

    async def list(
        self, *, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeProduct]:
        stmt = select(KnowledgeProductModel).options(selectinload(KnowledgeProductModel.versions))
        if search:
            stmt = stmt.where(KnowledgeProductModel.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(KnowledgeProductModel.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        products = [_product_to_domain(row) for row in rows]
        if status:
            products = [p for p in products if p.versions and p.current_version.status.value == status]
        return products

    async def save(self, product: KnowledgeProduct) -> None:
        row = await self._session.get(KnowledgeProductModel, product.id)
        if row is None:
            row = KnowledgeProductModel(
                id=product.id, product_key=product.product_key, name=product.name, owner=product.owner
            )
            self._session.add(row)
            await self._session.flush()

        existing_version_ids = set(
            (
                await self._session.execute(
                    select(KnowledgeProductVersionModel.id).where(
                        KnowledgeProductVersionModel.product_id == product.id
                    )
                )
            )
            .scalars()
            .all()
        )

        for version in product.versions:
            content = version.to_canonical_dict(
                product_key=product.product_key, name=product.name, owner=product.owner
            )
            if version.id not in existing_version_ids:
                self._session.add(
                    KnowledgeProductVersionModel(
                        id=version.id,
                        product_id=product.id,
                        semver=str(version.semver),
                        status=version.status.value,
                        yaml_content=content,
                        source_extraction_run_id=version.source_extraction_run_id,
                        created_by=version.created_by,
                    )
                )
            else:
                version_row = await self._session.get(KnowledgeProductVersionModel, version.id)
                version_row.status = version.status.value
                if version.status is KnowledgeProductStatus.PUBLISHED and version_row.published_at is None:
                    version_row.published_at = utc_now()
                if version.status is KnowledgeProductStatus.RETIRED and version_row.retired_at is None:
                    version_row.retired_at = utc_now()

        await self._session.flush()
        row.current_version_id = product.current_version.id
        await self._session.commit()
