.PHONY: contracts-test test-runtime run-ops run-runtime run-dashboard e2e demo-check

contracts-test:
	pytest contracts/tests -q

test-runtime:
	pytest voice-runtime/tests -v

run-ops:
	@if [ -d "ops/api" ]; then \
		uvicorn resolvix_ops.app:app --port 8100 --reload; \
	else \
		python voice-runtime/dev/ops_stub.py; \
	fi

run-runtime:
	uvicorn resolvix_runtime.app:app --port 8000 --reload

run-dashboard:
	npm --prefix ops/dashboard run dev

e2e:
	pytest integration/e2e_test.py -v

demo-check: contracts-test test-runtime
	@echo "Checking runtime health..."
	@curl -s http://localhost:8000/healthz || echo "Runtime not running on :8000 (run 'make run-runtime' first)"
