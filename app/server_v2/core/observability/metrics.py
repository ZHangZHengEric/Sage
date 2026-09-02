from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Literal, cast

from prometheus_client import CollectorRegistry, Counter, Gauge, Summary, generate_latest

MetricKind = Literal["counter", "gauge", "summary"]
Metric = Counter | Gauge | Summary


class MetricsRegistry:
    """Small dynamic facade over a process-local Prometheus registry."""

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace.strip("_")
        if not self._namespace:
            raise ValueError("metrics namespace is required")
        self._registry = CollectorRegistry()
        self._lock = Lock()
        self._metrics: dict[str, tuple[MetricKind, tuple[str, ...], Metric]] = {}

    def inc_counter(
        self,
        name: str,
        amount: float = 1.0,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        raw_metric, values = self._metric("counter", name, labels)
        metric = cast(Counter, raw_metric)
        target = metric.labels(**values) if values else metric
        target.inc(amount)

    def inc_gauge(
        self,
        name: str,
        amount: float = 1.0,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        raw_metric, values = self._metric("gauge", name, labels)
        metric = cast(Gauge, raw_metric)
        target = metric.labels(**values) if values else metric
        target.inc(amount)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        raw_metric, values = self._metric("gauge", name, labels)
        metric = cast(Gauge, raw_metric)
        target = metric.labels(**values) if values else metric
        target.set(value)

    def dec_gauge(
        self,
        name: str,
        amount: float = 1.0,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        raw_metric, values = self._metric("gauge", name, labels)
        metric = cast(Gauge, raw_metric)
        target = metric.labels(**values) if values else metric
        target.dec(amount)

    def observe(
        self,
        name: str,
        value: float,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        raw_metric, values = self._metric("summary", name, labels)
        metric = cast(Summary, raw_metric)
        target = metric.labels(**values) if values else metric
        target.observe(value)

    def render_prometheus(self) -> str:
        return generate_latest(self._registry).decode("utf-8")

    def reset(self) -> None:
        with self._lock:
            self._registry = CollectorRegistry()
            self._metrics.clear()

    def _metric(
        self,
        kind: MetricKind,
        name: str,
        labels: Mapping[str, object] | None,
    ) -> tuple[Metric, dict[str, str]]:
        normalized_name = name.strip("_")
        if not normalized_name:
            raise ValueError("metric name is required")
        values = {str(key): str(value) for key, value in (labels or {}).items()}
        label_names = tuple(sorted(values))
        full_name = f"{self._namespace}_{normalized_name}"
        with self._lock:
            existing = self._metrics.get(full_name)
            if existing is None:
                metric_type = {
                    "counter": Counter,
                    "gauge": Gauge,
                    "summary": Summary,
                }[kind]
                metric = metric_type(
                    full_name,
                    f"AIoT metric {full_name}",
                    labelnames=label_names,
                    registry=self._registry,
                )
                self._metrics[full_name] = (kind, label_names, metric)
            else:
                existing_kind, existing_labels, metric = existing
                if existing_kind != kind or existing_labels != label_names:
                    raise ValueError(f"metric {full_name} was already declared with a different schema")
        return metric, values
