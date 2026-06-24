# Convenience targets for the Standard Bots REST API examples.
# These just wrap the venv + python commands documented in the README.

VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup quickstart list clean

help:
	@echo "Standard Bots REST API examples"
	@echo ""
	@echo "  make setup       Create a virtualenv (.venv) and install requirements"
	@echo "  make quickstart  Run the connect + health-check example (simulator)"
	@echo "  make list        List the available example scripts"
	@echo "  make clean       Remove the virtualenv and Python caches"
	@echo ""
	@echo "After 'make setup', copy .env.example to .env and fill in your"
	@echo "ROBOT_URL and ROBOT_TOKEN, then run any example, e.g.:"
	@echo "  $(PY) src/read_state.py"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ""
	@echo "Setup complete. Next: cp .env.example .env  (then fill in URL + token)."

quickstart:
	$(PY) src/quickstart.py

list:
	@echo "Example scripts (run with: $(PY) src/<name>.py [--live]):"
	@ls -1 src/*.py | grep -v '_client.py' | sed 's#^src/#  #'

clean:
	rm -rf $(VENV)
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
