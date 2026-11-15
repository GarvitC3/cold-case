PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

dev:
	./dev.sh --sim-wireless
dev-usb:
	./dev.sh
dev-wireless:
	$(PY) -m app --sim-wireless
chaos:
	$(PY) tools/sim_wireless.py --scenario chaos
test:
	$(PY) -m pytest tests -q
audit:
	$(PY) tools/touch_audit.py
.PHONY: dev dev-usb dev-wireless chaos test audit
