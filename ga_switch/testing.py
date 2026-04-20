import time


class ModelTester:
    def __init__(self, service):
        self.service = service

    def run(self, provider_id):
        provider = self.service.store.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")
        family = provider["backend_family"]
        test_cfg = self.service.store.get_test_config(family) or {}
        client = self.service.build_client_from_provider(
            provider,
            route_id=None,
            route_name=f"test:{provider['name']}",
            route_kind="single",
            for_testing=True,
            override={
                "model": test_cfg.get("test_model") or provider.get("model"),
                "api_mode": test_cfg.get("api_mode") or provider.get("api_mode"),
                "reasoning_effort": test_cfg.get("reasoning_effort") if family == "oai" else provider.get("reasoning_effort"),
            },
        )
        prompt = test_cfg.get("prompt") or "Reply with exactly: pong"
        started = time.perf_counter()
        first_chunk_at = None
        raw_text = ""
        response = None
        gen = client.chat([{"role": "user", "content": prompt}], tools=None)
        try:
            while True:
                chunk = next(gen)
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                raw_text += chunk
        except StopIteration as stop:
            response = stop.value
        finished = time.perf_counter()
        backend = client.backend
        latency_ms = int((finished - started) * 1000)
        ttfb_ms = int(((first_chunk_at or finished) - started) * 1000)
        last_error = getattr(backend, "last_error_message", "") or ""
        error_kind = getattr(backend, "last_error_kind", None)
        success = not (raw_text.startswith("Error:") or last_error)
        status = "healthy" if success else "failed"
        if success and latency_ms >= 15000:
            status = "degraded"
        self.service.store.update_provider_health(
            provider_id,
            status=status,
            latency_ms=latency_ms,
            ttfb_ms=ttfb_ms,
            last_error=last_error,
        )
        return {
            "provider_id": provider_id,
            "provider_name": provider["name"],
            "status": status,
            "latency_ms": latency_ms,
            "ttfb_ms": ttfb_ms,
            "last_error": last_error,
            "error_kind": error_kind,
            "raw_text": raw_text[:500],
            "response_repr": repr(response) if response is not None else "",
        }
