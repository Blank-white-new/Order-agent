from __future__ import annotations

from app.db.models import Customer
from app.domain.errors import simulation_data_required


class CustomerService:
    def __init__(self, uow_factory, *, simulation_data_only: bool = True) -> None:
        self.uow_factory = uow_factory
        self.simulation_data_only = simulation_data_only

    def create(self, *, restaurant_id: int, external_reference: str, display_name: str | None, is_synthetic: bool) -> Customer:
        if self.simulation_data_only and not is_synthetic:
            raise simulation_data_required()
        with self.uow_factory() as uow:
            customer = Customer(
                restaurant_id=restaurant_id,
                external_reference=external_reference,
                display_name=display_name,
                is_synthetic=is_synthetic,
            )
            uow.orders.add(customer)
            uow.flush()
            return customer
