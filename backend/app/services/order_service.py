from __future__ import annotations

from app.models.schemas import MenuItem
from app.state.session_state import OrderItem, SessionState


class OrderService:
    def add_item(
        self,
        state: SessionState,
        item: MenuItem,
        quantity: int = 1,
        options: list[str] | None = None,
        unit: str | None = None,
        notes: str | None = None,
        spicy_level: str | None = None,
        exclusions: list[str] | None = None,
        source: str | None = None,
    ) -> list[OrderItem]:
        quantity = self._positive_quantity(quantity)
        options = self._dedupe(options or [])
        notes = self._clean_text(notes)
        spicy_level = self._clean_text(spicy_level)
        exclusions = self._dedupe(exclusions or [])
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for entry in order:
            if (
                entry.item_id == item.id
                and sorted(entry.options) == sorted(options)
                and entry.notes == notes
                and entry.spicy_level == spicy_level
                and sorted(entry.exclusions) == sorted(exclusions)
            ):
                entry.quantity += quantity
                return order
        order.append(
            OrderItem(
                item_id=item.id,
                name=item.name,
                price=item.price,
                unit_price_minor=item.base_price_minor if item.base_price_minor is not None else item.price * 100,
                currency=item.currency,
                menu_item_db_id=item.menu_item_db_id,
                menu_version_id=item.menu_version_id,
                quantity=quantity,
                options=options,
                spicy_level=spicy_level,
                exclusions=exclusions,
                notes=notes,
                category=item.category,
                unit=unit,
                source=source,
            )
        )
        return order

    def add_items(self, state: SessionState, specs: list[dict]) -> list[OrderItem]:
        order_state = state.clone()
        for spec in specs:
            item = spec["item"]
            order_state.current_order = self.add_item(
                order_state,
                item,
                quantity=spec.get("quantity", 1),
                options=spec.get("options", []),
                unit=spec.get("unit"),
                notes=spec.get("notes"),
                spicy_level=spec.get("spicy_level"),
                exclusions=spec.get("exclusions", []),
                source=spec.get("source"),
            )
        return order_state.current_order

    def remove_item(self, state: SessionState, item_name: str) -> tuple[list[OrderItem], bool]:
        before = len(state.current_order)
        remaining = [self._copy_order_item(entry) for entry in state.current_order if entry.name != item_name]
        if len(remaining) < before:
            return remaining, True
        substring_matches = [entry for entry in state.current_order if item_name in entry.name]
        if not substring_matches:
            return [self._copy_order_item(entry) for entry in state.current_order], False
        if len(substring_matches) == 1 and substring_matches[0].name != item_name:
            return [self._copy_order_item(entry) for entry in state.current_order], False
        remaining = [self._copy_order_item(entry) for entry in state.current_order if item_name not in entry.name]
        return remaining, len(remaining) != before

    def remove_by_index(self, state: SessionState, index: int) -> tuple[list[OrderItem], bool]:
        if index < 0 or index >= len(state.current_order):
            return [self._copy_order_item(entry) for entry in state.current_order], False
        return [self._copy_order_item(entry) for i, entry in enumerate(state.current_order) if i != index], True

    def remove_category(self, state: SessionState, category: str) -> tuple[list[OrderItem], int]:
        matched = [entry for entry in state.current_order if entry.category == category or category in entry.name]
        remaining = [self._copy_order_item(entry) for entry in state.current_order if entry not in matched]
        return remaining, len(matched)

    def clear_order(self, state: SessionState) -> list[OrderItem]:
        return []

    def update_item(self, state: SessionState, item_name: str, options: list[str]) -> tuple[list[OrderItem], bool]:
        return self.update_options(state, item_name, options)

    def update_options(self, state: SessionState, item_name: str, options: list[str], index: int | None = None) -> tuple[list[OrderItem], bool]:
        updated = False
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for pos, entry in enumerate(order):
            if self._matches_target(pos, entry, item_name, index):
                for option in options:
                    if option not in entry.options:
                        entry.options.append(option)
                updated = True
        return order, updated

    def update_notes(self, state: SessionState, item_name: str, note: str, index: int | None = None) -> tuple[list[OrderItem], bool]:
        note = note.strip()
        if not note:
            return [self._copy_order_item(entry) for entry in state.current_order], False
        updated = False
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for pos, entry in enumerate(order):
            if self._matches_target(pos, entry, item_name, index):
                existing = entry.notes.strip() if entry.notes else ""
                entry.notes = existing if note in existing.split("；") else "；".join(part for part in [existing, note] if part)
                updated = True
        return order, updated

    def update_item_modifiers(
        self,
        state: SessionState,
        item_name: str,
        *,
        spicy_level: str | None = None,
        clear_spicy: bool = False,
        exclusions: list[str] | None = None,
        remove_exclusions: list[str] | None = None,
        note: str | None = None,
        replace_note: bool = False,
        clear_notes: bool = False,
        index: int | None = None,
    ) -> tuple[list[OrderItem], bool]:
        spicy_level = self._clean_text(spicy_level)
        exclusions = self._dedupe(exclusions or [])
        remove_exclusions = self._dedupe(remove_exclusions or [])
        note = self._clean_text(note)
        has_requested_change = any(
            [
                spicy_level,
                clear_spicy,
                exclusions,
                remove_exclusions,
                note,
                replace_note,
                clear_notes,
            ]
        )
        if not has_requested_change:
            return [self._copy_order_item(entry) for entry in state.current_order], False

        updated = False
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for pos, entry in enumerate(order):
            if not self._matches_target(pos, entry, item_name, index):
                continue
            if clear_spicy:
                entry.spicy_level = None
            elif spicy_level:
                entry.spicy_level = spicy_level
            if exclusions:
                entry.exclusions = self._dedupe([*entry.exclusions, *exclusions])
            if remove_exclusions:
                removable = set(remove_exclusions)
                entry.exclusions = [value for value in entry.exclusions if value not in removable]
            if clear_notes:
                entry.notes = None
            elif note:
                if replace_note:
                    entry.notes = note
                else:
                    existing = entry.notes.strip() if entry.notes else ""
                    entry.notes = existing if note in existing.split("；") else "；".join(part for part in [existing, note] if part)
            updated = True
        return order, updated

    def update_quantity(self, state: SessionState, item_name: str, quantity: int, index: int | None = None) -> tuple[list[OrderItem], bool]:
        quantity = self._positive_quantity(quantity)
        updated = False
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for pos, entry in enumerate(order):
            if self._matches_target(pos, entry, item_name, index):
                entry.quantity = quantity
                updated = True
        return order, updated

    def adjust_quantity(self, state: SessionState, item_name: str, delta: int, index: int | None = None) -> tuple[list[OrderItem], bool]:
        updated = False
        order = [self._copy_order_item(entry) for entry in state.current_order]
        for pos, entry in enumerate(order):
            if self._matches_target(pos, entry, item_name, index):
                entry.quantity = max(entry.quantity + delta, 1)
                updated = True
        return order, updated

    def replace_item(
        self,
        state: SessionState,
        old_item_name: str,
        new_item: MenuItem,
        quantity: int = 1,
        options: list[str] | None = None,
        index: int | None = None,
    ) -> tuple[list[OrderItem], bool]:
        options = options or []
        replaced = False
        order: list[OrderItem] = []

        def _is_exact_target(pos: int, entry: OrderItem) -> bool:
            if index is not None:
                return pos == index
            return entry.name == old_item_name

        for pos, entry in enumerate(state.current_order):
            is_target = _is_exact_target(pos, entry)
            if is_target and not replaced:
                order.append(
                    OrderItem(
                        item_id=new_item.id,
                        name=new_item.name,
                        price=new_item.price,
                        unit_price_minor=new_item.base_price_minor if new_item.base_price_minor is not None else new_item.price * 100,
                        currency=new_item.currency,
                        menu_item_db_id=new_item.menu_item_db_id,
                        menu_version_id=new_item.menu_version_id,
                        quantity=quantity or entry.quantity,
                        options=options,
                        category=new_item.category,
                    )
                )
                replaced = True
            elif not is_target:
                order.append(self._copy_order_item(entry))

        if not replaced:
            substring_targets = [
                (pos, entry) for pos, entry in enumerate(state.current_order)
                if old_item_name in entry.name
            ]
            if len(substring_targets) == 1:
                pos, entry = substring_targets[0]
                if entry.name != old_item_name:
                    return [self._copy_order_item(entry) for entry in state.current_order], False
                new_order_item = OrderItem(
                    item_id=new_item.id,
                    name=new_item.name,
                    price=new_item.price,
                    unit_price_minor=new_item.base_price_minor if new_item.base_price_minor is not None else new_item.price * 100,
                    currency=new_item.currency,
                    menu_item_db_id=new_item.menu_item_db_id,
                    menu_version_id=new_item.menu_version_id,
                    quantity=quantity or entry.quantity,
                    options=options,
                    category=new_item.category,
                )
                order = (
                    [self._copy_order_item(e) for e in state.current_order[:pos]]
                    + [new_order_item]
                    + [self._copy_order_item(e) for e in state.current_order[pos + 1:]]
                )
                replaced = True
        return order, replaced

    def summarize_order(self, state: SessionState) -> str:
        if not state.current_order:
            return "你还没点菜。"
        parts = []
        for entry in state.current_order:
            option_text = f"（{','.join(entry.options)}）" if entry.options else ""
            spicy_text = f"（辣度：{entry.spicy_level}）" if entry.spicy_level else ""
            exclusion_text = f"（忌口：不要{'、不要'.join(entry.exclusions)}）" if entry.exclusions else ""
            visible_note = self._visible_note(entry)
            note_text = f"（备注：{visible_note}）" if visible_note else ""
            parts.append(f"{entry.name}{option_text}{spicy_text}{exclusion_text}{note_text} x{entry.quantity}")
        return f"你点了：{'、'.join(parts)}。菜品小计 {self.total_price(state)} 元。"

    def total_price(self, state: SessionState) -> int:
        return sum(entry.price * entry.quantity for entry in state.current_order)

    def subtotal_minor(self, state: SessionState) -> int:
        return sum((entry.unit_price_minor if entry.unit_price_minor is not None else entry.price * 100) * entry.quantity for entry in state.current_order)

    def validate_before_submit(self, state: SessionState) -> tuple[bool, str | None]:
        if not state.current_order:
            return False, "订单里还没有菜品，先点一个再确认。"
        if state.fulfillment_type == "delivery":
            if not state.official_delivery_address:
                return False, "还需要配送地址。"
            if not state.phone:
                return False, "还需要联系电话。"
        return True, None

    def submit_order(self, state: SessionState) -> str:
        return "MOCK-ORDER-0001"

    def _positive_quantity(self, quantity: int | None) -> int:
        return max(int(quantity or 1), 1)

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    def _visible_note(self, item: OrderItem) -> str | None:
        if not item.notes:
            return None
        duplicate_notes = {f"不要{value}" for value in item.exclusions}
        parts = [part.strip() for part in item.notes.split("；") if part.strip()]
        visible = [part for part in parts if part not in duplicate_notes]
        return "；".join(visible) if visible else None

    def _matches_target(self, pos: int, entry: OrderItem, item_name: str, index: int | None) -> bool:
        if index is not None:
            return pos == index
        return entry.name == item_name

    def _copy_order_item(self, item: OrderItem) -> OrderItem:
        if hasattr(item, "model_copy"):
            return item.model_copy(deep=True)
        return item.copy(deep=True)
