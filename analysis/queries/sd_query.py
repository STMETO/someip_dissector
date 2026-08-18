"""SOME/IP-SD 生命周期记录的一次性分类索引。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from analysis.sd_diagnostic import extract_sd_records

_CATEGORIES = (
    "offers",
    "stop_offers",
    "subscribes",
    "stop_subscribes",
    "subscribe_acks",
    "subscribe_nacks",
)


class SdRecordQuery:
    """提取一次 SD Entry，并按记录类别和 Service ID 建立索引。"""

    def __init__(self, messages: list[dict[str, Any]]):
        extracted = extract_sd_records(messages)
        self._records = {
            category: tuple(extracted.get(category, ())) for category in _CATEGORIES
        }
        self._by_service: dict[str, dict[int, tuple[dict[str, Any], ...]]] = {}
        for category, records in self._records.items():
            buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                buckets[int(record.get("service_id", 0))].append(record)
            self._by_service[category] = {
                service_id: tuple(values) for service_id, values in buckets.items()
            }

    @property
    def all_records(self) -> dict[str, tuple[dict[str, Any], ...]]:
        """返回供兼容诊断构建器读取的全部分类记录。"""
        return self._records

    @property
    def index_stats(self) -> dict[str, int]:
        """返回各类 SD 记录数量。"""
        return {category: len(records) for category, records in self._records.items()}

    def records(
        self,
        category: str,
        service_id: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """按类别读取全部记录，或进一步按 Service ID 读取。"""
        if category not in self._records:
            raise ValueError(f"未知 SD 记录类别: {category}")
        if service_id is None:
            return self._records[category]
        return self._by_service[category].get(service_id, ())


__all__ = ["SdRecordQuery"]
