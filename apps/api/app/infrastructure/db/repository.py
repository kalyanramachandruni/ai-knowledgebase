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

    # process.steps: old format = list[str], new format = list[dict]
    raw_steps = content.get("process", {}).get("steps", [])
    process_steps = []
    for i, s in enumerate(raw_steps):
        if isinstance(s, str):
            process_steps.append(ProcessStep(name=s, sequence=i))
        else:
            process_steps.append(ProcessStep(
                name=s.get("name", ""),
                sequence=i,
                description=s.get("description", ""),
                responsible_role=s.get("responsible_role", ""),
                inputs=tuple(s.get("inputs", [])),
                outputs=tuple(s.get("outputs", [])),
                decision=s.get("decision"),
                tools_used=tuple(s.get("tools_used", [])),
            ))

    # roles: old format = list[str], new format = list[dict]
    raw_roles = content.get("roles", [])
    roles = []
    for r in raw_roles:
        if isinstance(r, str):
            roles.append(Role(name=r))
        else:
            roles.append(Role(name=r.get("name", ""), responsibilities=tuple(r.get("responsibilities", []))))

    # tools: old format = list[str], new format = list[dict]
    raw_tools = content.get("tools", [])
    tools = []
    for t in raw_tools:
        if isinstance(t, str):
            tools.append(ToolReference(key=t, display_name=t))
        else:
            name = t.get("name", "")
            tools.append(ToolReference(key=name, display_name=name, purpose=t.get("purpose", "")))

    return KnowledgeProductVersion(
        id=row.id,
        product_id=row.product_id,
        semver=SemVer.parse(row.semver),
        status=KnowledgeProductStatus(row.status),
        process_steps=process_steps,
        rules=[
            BusinessRule(condition=r["condition"], action=r["action"], rationale=r.get("rationale", ""))
            for r in content.get("rules", [])
        ],
        policies=[
            Policy(condition=p["condition"], action=p["action"], rationale=p.get("rationale", ""))
            for p in content.get("policies", [])
        ],
        sla=ServiceLevelAgreement(target=sla_content["target"]) if sla_content else None,
        escalations=[
            Escalation(
                after=e.get("after", e.get("trigger", "")),
                escalate_to=e["escalate_to"],
                action=e.get("action", ""),
            )
            for e in content.get("escalations", [])
        ],
        roles=roles,
        tools=tools,
        created_by=row.created_by,
        source_extraction_run_id=row.source_extraction_run_id,
        process_overview=content.get("process_overview") or {},
    )


def _product_to_domain(row: KnowledgeProductModel) -> KnowledgeProduct:
    product = KnowledgeProduct(
        id=row.id,
        product_key=row.product_key,
        name=row.name,
        owner=row.owner,
    )
    product.versions = sorted(
        [_version_to_domain(v) for v in row.versions],
        key=lambda v: (v.semver.major, v.semver.minor, v.semver.patch),
    )
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

    async def get_by_id_for_update(self, product_id: uuid.UUID) -> KnowledgeProduct | None:
        """Like get_by_id but holds a row-level lock until the transaction commits.
        Use when compiling a new version to prevent concurrent semver collisions."""
        product_stmt = (
            select(KnowledgeProductModel)
            .where(KnowledgeProductModel.id == product_id)
            .with_for_update()
        )
        product_row = (await self._session.execute(product_stmt)).scalar_one_or_none()
        if product_row is None:
            return None
        versions_stmt = (
            select(KnowledgeProductVersionModel)
            .where(KnowledgeProductVersionModel.product_id == product_id)
            .order_by(KnowledgeProductVersionModel.created_at)
        )
        version_rows = (await self._session.execute(versions_stmt)).scalars().all()
        # Build domain object directly — avoids touching ORM relationship attributes
        # outside a greenlet context (which causes MissingGreenlet errors).
        product = KnowledgeProduct(
            id=product_row.id,
            product_key=product_row.product_key,
            name=product_row.name,
            owner=product_row.owner,
        )
        product.versions = sorted(
            [_version_to_domain(v) for v in version_rows],
            key=lambda v: (v.semver.major, v.semver.minor, v.semver.patch),
        )
        return product

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
