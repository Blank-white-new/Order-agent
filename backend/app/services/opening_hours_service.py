from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class OpeningHoursService:
    def __init__(self, uow_factory) -> None:
        self.uow_factory = uow_factory

    def is_branch_open(self, branch_id: int, at: datetime) -> bool:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        with self.uow_factory() as uow:
            branch = uow.tenants.get_branch_by_id(branch_id)
            if not branch:
                return False
            local = at.astimezone(ZoneInfo(branch.timezone))
            local_date = local.date()
            previous_date = local_date - timedelta(days=1)
            slots = uow.operations.list_hours(branch.id, local.weekday(), local_date)
            previous_slots = uow.operations.list_hours(branch.id, (local.weekday() - 1) % 7, previous_date)
            if any(slot.effective_date == local_date and slot.is_closed for slot in slots):
                return False
            current = local.timetz().replace(tzinfo=None)
            for slot in slots:
                if slot.is_closed:
                    continue
                if slot.start_time <= slot.end_time:
                    if slot.start_time <= current < slot.end_time:
                        return True
                elif current >= slot.start_time:
                    return True
            for slot in previous_slots:
                if not slot.is_closed and slot.start_time > slot.end_time and current < slot.end_time:
                    return True
            return False
