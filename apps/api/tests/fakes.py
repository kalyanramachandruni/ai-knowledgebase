import uuid

from app.domain.knowledge_product.entities import KnowledgeProduct


class FakeKnowledgeProductRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, KnowledgeProduct] = {}

    async def get_by_id(self, product_id: uuid.UUID) -> KnowledgeProduct | None:
        return self.store.get(product_id)

    async def get_by_key(self, product_key: str) -> KnowledgeProduct | None:
        for product in self.store.values():
            if product.product_key == product_key:
                return product
        return None

    async def list(self, *, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0):
        return list(self.store.values())

    async def save(self, product: KnowledgeProduct) -> None:
        self.store[product.id] = product


class FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def record(self, **kwargs) -> None:
        self.entries.append(kwargs)


class FakeEventPublisher:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)
