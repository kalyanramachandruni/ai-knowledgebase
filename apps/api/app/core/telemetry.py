from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import settings


def setup_telemetry(app: FastAPI) -> None:
    """Wires OpenTelemetry tracing (exported via OTLP to the collector,
    which forwards to Grafana/Tempo or any OTLP-compatible backend) and
    Prometheus metrics. Called once from app.main at import time.

    No-ops the trace exporter if OTEL_EXPORTER_OTLP_ENDPOINT isn't set,
    so local dev without a collector running doesn't fail or hang on
    every span export."""

    if settings.otel_exporter_otlp_endpoint:
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "knowledge-product-studio-api"}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True))
        )
        trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
