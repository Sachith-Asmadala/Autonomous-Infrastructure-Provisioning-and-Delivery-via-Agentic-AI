# ============================================================
# Smart DevOps Assistant - Developer Makefile
# ============================================================

.DEFAULT_GOAL := help

.PHONY: qa-setup qa qa-backend qa-browser qa-security

## Install the existing project plus the QA-only browser/report dependencies.
qa-setup: setup
	$(PIP) install -r qa/requirements.txt

## Run all isolated QA stages, including passive ZAP (requires Docker daemon).
qa:
	$(BACKEND_PY) -m qa.run

## Backend regression suite, coverage and QA harness tests.
qa-backend:
	$(BACKEND_PY) -m qa.run --suite backend

## Selenium with real application services and deterministic external tools.
qa-browser:
	$(BACKEND_PY) -m qa.run --suite browser --no-zap

## Controlled auth/RBAC tests plus local passive ZAP baseline.
qa-security:
	$(BACKEND_PY) -m qa.run --suite security

SHELL := /bin/sh
PYTHON ?= python3.11
BACKEND_DIR := backend
FRONTEND_DIR := frontend
DESKTOP_DIR := desktop
BACKEND_VENV := $(BACKEND_DIR)/venv
BACKEND_PY := $(BACKEND_VENV)/bin/python
PIP := $(BACKEND_PY) -m pip
NPM := npm
COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo ""; fi)
SUBMISSION_DIR := dist-submission
SUBMISSION_ZIP := $(SUBMISSION_DIR)/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI-clean.zip
SUBMISSION_INCLUDE := \
	.env.example .python-version \
	README.md AGENTS.md Makefile docker-compose.yml scripts \
	backend/.env.example backend/app backend/tests backend/requirements.txt \
	backend/run_backend.py backend/pyinstaller.spec \
	frontend/.env.example frontend/src frontend/package.json frontend/package-lock.json \
	frontend/capacitor.config.ts frontend/android \
	desktop docs

.PHONY: help init-env setup backend-install frontend-install dev dev-build backend frontend train-model \
	test test-backend test-frontend lint lint-backend lint-frontend format format-backend format-frontend \
	build docker-build clean docker-down docker-logs reset github-e2e-checklist \
	desktop-dev desktop-setup-win build-frontend build-backend-exe desktop-start desktop-build-win desktop-mode desktop-check \
	mobile-install mobile-build mobile-sync mobile-open-android mobile-apk-debug mobile-check \
	prepare-submission prepare-submission-dry-run

## Show all available commands.
help:
	@echo "Smart DevOps Assistant commands"
	@echo ""
	@echo "Setup:"
	@echo "  make init-env           Create backend/frontend .env files from examples"
	@echo "  make setup              Install backend and frontend dependencies"
	@echo "  make backend-install    Create backend venv and install requirements.txt"
	@echo "  make frontend-install   Install frontend npm dependencies"
	@echo ""
	@echo "Run:"
	@echo "  make dev                Start full project with Docker Compose"
	@echo "  make dev-build          Build and start full project with Docker Compose"
	@echo "  make backend            Start FastAPI locally on http://localhost:8000"
	@echo "  make frontend           Start Vite locally on http://localhost:5173"
	@echo "  make train-model        Train the CI/CD failure classification model"
	@echo "  make github-e2e-checklist"
	@echo "                          Print safe real-GitHub demo verification checklist"
	@echo "  make desktop-mode       Print local desktop environment variables"
	@echo "  make desktop-setup-win  Run the Windows desktop setup script"
	@echo "  make desktop-dev        Run backend, Vite, and Electron in desktop mode"
	@echo "  make desktop-start      Start Electron from the built frontend"
	@echo "  make desktop-build-win  Build the Windows installer with electron-builder"
	@echo "  make mobile-install     Install Capacitor/mobile dependencies"
	@echo "  make mobile-build       Build React app in mobile mode"
	@echo "  make mobile-sync        Sync web build to Android project"
	@echo "  make mobile-open-android"
	@echo "                          Open Android project in Android Studio"
	@echo "  make mobile-apk-debug   Build Android debug APK"
	@echo ""
	@echo "Quality:"
	@echo "  make test               Run backend and frontend tests where configured"
	@echo "  make test-backend       Run backend pytest suite"
	@echo "  make test-frontend      Run frontend tests if package.json defines test"
	@echo "  make lint               Run configured backend/frontend linters"
	@echo "  make format             Run configured backend/frontend formatters"
	@echo "  make build              Build frontend production bundle"
	@echo "  make qa-setup           Install project and QA-only dependencies"
	@echo "  make qa                 Run isolated backend, Selenium, security and passive ZAP"
	@echo "  make qa-backend         Backend regression, coverage and QA harness checks"
	@echo "  make qa-browser         Selenium browser checks (ZAP explicitly not executed)"
	@echo "  make qa-security        Controlled security tests and local passive ZAP"
	@echo "  make build-frontend     Build frontend with desktop production env"
	@echo "  make build-backend-exe  Build packaged backend executable with PyInstaller"
	@echo "  make desktop-check      Verify desktop build prerequisites"
	@echo "  make mobile-check       Verify mobile build prerequisites"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build       Build Docker images"
	@echo "  make docker-down        Stop Docker Compose services"
	@echo "  make docker-logs        Show Docker Compose logs"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              Remove caches, builds, and local dependency installs"
	@echo "  make reset              Stop containers and remove caches/builds/dependencies"
	@echo "  make prepare-submission-dry-run"
	@echo "                          Preview files included in the clean submission ZIP"
	@echo "  make prepare-submission Create dist-submission clean ZIP without secrets/caches"

## Create local env files from examples without overwriting existing files.
init-env:
	@if [ -f "$(BACKEND_DIR)/.env" ]; then \
		echo "$(BACKEND_DIR)/.env already exists; leaving it unchanged."; \
	elif [ -f "$(BACKEND_DIR)/.env.example" ]; then \
		cp "$(BACKEND_DIR)/.env.example" "$(BACKEND_DIR)/.env"; \
		echo "Created $(BACKEND_DIR)/.env from $(BACKEND_DIR)/.env.example."; \
	else \
		echo "No $(BACKEND_DIR)/.env.example found; skipping backend env."; \
	fi
	@if [ -f "$(FRONTEND_DIR)/.env" ]; then \
		echo "$(FRONTEND_DIR)/.env already exists; leaving it unchanged."; \
	elif [ -f "$(FRONTEND_DIR)/.env.example" ]; then \
		cp "$(FRONTEND_DIR)/.env.example" "$(FRONTEND_DIR)/.env"; \
		echo "Created $(FRONTEND_DIR)/.env from $(FRONTEND_DIR)/.env.example."; \
	else \
		echo "No $(FRONTEND_DIR)/.env.example found; skipping frontend env."; \
	fi

## Install backend and frontend dependencies if their manifests exist.
setup: init-env backend-install frontend-install

## Create backend virtualenv and install Python dependencies.
backend-install:
	@if [ ! -f "$(BACKEND_DIR)/requirements.txt" ]; then echo "No backend/requirements.txt found; skipping backend install."; exit 0; fi
	@$(PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 'Python 3.11 is required. Install Python 3.11 and rerun with PYTHON=python3.11 make backend-install.')"
	$(PYTHON) -m venv $(BACKEND_VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND_DIR)/requirements.txt

## Install frontend npm dependencies inside frontend/.
frontend-install:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found; skipping frontend install."; exit 0; fi
	@cd $(FRONTEND_DIR) && if [ -f package-lock.json ]; then \
		$(NPM) ci || { \
			echo "npm ci failed; removing generated node_modules and retrying."; \
			rm -rf node_modules; \
			$(NPM) ci; \
		}; \
	else \
		$(NPM) install; \
	fi

## Start the full project using Docker Compose.
dev: init-env
	@if [ -z "$(COMPOSE)" ]; then echo "Docker Compose is not available."; exit 1; fi
	$(COMPOSE) up -d

## Build and start the full project using Docker Compose.
dev-build: init-env
	@if [ -z "$(COMPOSE)" ]; then echo "Docker Compose is not available."; exit 1; fi
	$(COMPOSE) up -d --build

## Start FastAPI locally.
backend:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@cd $(BACKEND_DIR) && ../$(BACKEND_PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

## Start the React/Vite frontend locally.
frontend:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found."; exit 1; fi
	@cd $(FRONTEND_DIR) && $(NPM) run dev

## Train the CI/CD failure classification model.
train-model:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@cd $(BACKEND_DIR) && ../$(BACKEND_PY) app/ml/train_failure_model.py

## Run backend and frontend tests where configured.
test: test-backend test-frontend

## Run backend pytest suite.
test-backend:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@cd $(BACKEND_DIR) && ../$(BACKEND_PY) -m pytest tests -q

## Run frontend tests only if package.json defines a test script.
test-frontend:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found; skipping frontend tests."; exit 0; fi
	@cd $(FRONTEND_DIR) && if node -e "process.exit(require('./package.json').scripts && require('./package.json').scripts.test ? 0 : 1)"; then $(NPM) test; else echo "No frontend test script configured; skipping."; fi

## Run configured backend and frontend lint commands.
lint: lint-backend lint-frontend

## Run backend linters if installed in the backend virtualenv.
lint-backend:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing; skipping backend lint."; exit 0; fi
	@cd $(BACKEND_DIR) && if ../$(BACKEND_PY) -m flake8 --version >/dev/null 2>&1; then ../$(BACKEND_PY) -m flake8 app tests --max-line-length=120; else echo "flake8 not installed; skipping."; fi
	@cd $(BACKEND_DIR) && if ../$(BACKEND_PY) -m mypy --version >/dev/null 2>&1; then ../$(BACKEND_PY) -m mypy app --ignore-missing-imports; else echo "mypy not installed; skipping."; fi

## Run frontend lint script if configured.
lint-frontend:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found; skipping frontend lint."; exit 0; fi
	@cd $(FRONTEND_DIR) && if node -e "process.exit(require('./package.json').scripts && require('./package.json').scripts.lint ? 0 : 1)"; then $(NPM) run lint; else echo "No frontend lint script configured; skipping."; fi

## Run configured formatters.
format: format-backend format-frontend

## Run backend formatter if black or ruff is installed.
format-backend:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing; skipping backend format."; exit 0; fi
	@cd $(BACKEND_DIR) && if ../$(BACKEND_PY) -m black --version >/dev/null 2>&1; then ../$(BACKEND_PY) -m black app tests; elif ../$(BACKEND_PY) -m ruff --version >/dev/null 2>&1; then ../$(BACKEND_PY) -m ruff format app tests; else echo "No backend formatter configured; skipping."; fi

## Run frontend formatter script if configured.
format-frontend:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found; skipping frontend format."; exit 0; fi
	@cd $(FRONTEND_DIR) && if node -e "process.exit(require('./package.json').scripts && require('./package.json').scripts.format ? 0 : 1)"; then $(NPM) run format; else echo "No frontend format script configured; skipping."; fi

## Build frontend production bundle.
build:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found; skipping frontend build."; exit 0; fi
	@cd $(FRONTEND_DIR) && $(NPM) run build

## Build frontend for desktop mode.
build-frontend:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found."; exit 1; fi
	@cd $(FRONTEND_DIR) && VITE_DESKTOP_MODE=true VITE_API_BASE_URL=http://127.0.0.1:8000 $(NPM) run build

## Build backend executable for desktop packaging.
build-backend-exe:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@cd $(BACKEND_DIR) && ../$(BACKEND_PY) -m PyInstaller pyinstaller.spec

## Print desktop-mode environment variables for local shells.
desktop-mode:
	@echo "DESKTOP_MODE=true"
	@echo "DISABLE_AUTH=true"
	@echo "VITE_DESKTOP_MODE=true"
	@echo "VITE_API_BASE_URL=http://127.0.0.1:8000"

## Run backend, Vite, and Electron in desktop mode for local development.
desktop-dev:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then echo "Frontend dependencies missing. Run: make frontend-install"; exit 1; fi
	@if [ ! -d "$(DESKTOP_DIR)/node_modules" ]; then cd $(DESKTOP_DIR) && $(NPM) install; fi
	@set -e; \
	(cd $(BACKEND_DIR) && DESKTOP_MODE=true DISABLE_AUTH=true HOST=127.0.0.1 PORT=8000 ../$(BACKEND_PY) run_backend.py) & backend_pid=$$!; \
	(cd $(FRONTEND_DIR) && VITE_DESKTOP_MODE=true VITE_API_BASE_URL=http://127.0.0.1:8000 $(NPM) run dev -- --host 127.0.0.1) & frontend_pid=$$!; \
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' EXIT INT TERM; \
	sleep 4; \
	cd $(DESKTOP_DIR) && ELECTRON_DEV_URL=http://127.0.0.1:5173 $(NPM) start

## Run the easy Windows desktop setup script.
desktop-setup-win:
	@powershell -ExecutionPolicy Bypass -File ./$(DESKTOP_DIR)/setup-windows.ps1

## Start Electron from frontend/dist. Run make build-frontend first.
desktop-start:
	@if [ ! -f "$(FRONTEND_DIR)/dist/index.html" ]; then echo "Frontend build missing. Run: make build-frontend"; exit 1; fi
	@if [ ! -d "$(DESKTOP_DIR)/node_modules" ]; then cd $(DESKTOP_DIR) && $(NPM) install; fi
	@cd $(DESKTOP_DIR) && $(NPM) start

## Build Windows installer. Run this on Windows for a native installer.
desktop-build-win: build-frontend build-backend-exe
	@if [ ! -d "$(DESKTOP_DIR)/node_modules" ]; then cd $(DESKTOP_DIR) && $(NPM) install; fi
	@cd $(DESKTOP_DIR) && $(NPM) run build:win

## Verify desktop build prerequisites without packaging secrets.
desktop-check:
	@if [ ! -x "$(BACKEND_PY)" ]; then echo "Backend venv missing. Run: make backend-install"; exit 1; fi
	@cd $(BACKEND_DIR) && DESKTOP_MODE=true DISABLE_AUTH=true ../$(BACKEND_PY) -c "import app.main; print('backend import ok')"
	@test -f "$(FRONTEND_DIR)/dist/index.html" || { echo "frontend build missing. Run: make build-frontend"; exit 1; }
	@test -d "$(DESKTOP_DIR)" || { echo "desktop folder missing"; exit 1; }
	@test -f "$(DESKTOP_DIR)/package.json" || { echo "desktop Electron package missing"; exit 1; }
	@test -f "$(BACKEND_DIR)/app/ml/failure_model.joblib" || { echo "model file missing"; exit 1; }
	@test -f "$(BACKEND_DIR)/.env.example" || { echo "backend .env.example missing"; exit 1; }
	@test -f "$(FRONTEND_DIR)/.env.example" || { echo "frontend .env.example missing"; exit 1; }
	@if find "$(DESKTOP_DIR)" -path "*/dist/*" -name ".env" -print -quit | grep -q .; then echo "real .env file found in desktop build output"; exit 1; fi
	@echo "desktop check ok"

## Install frontend mobile dependencies.
mobile-install:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found."; exit 1; fi
	@cd $(FRONTEND_DIR) && $(NPM) install

## Build React app in mobile mode.
mobile-build:
	@if [ ! -f "$(FRONTEND_DIR)/package.json" ]; then echo "No frontend/package.json found."; exit 1; fi
	@cd $(FRONTEND_DIR) && $(NPM) run mobile:build

## Sync React build to Capacitor Android project.
mobile-sync:
	@cd $(FRONTEND_DIR) && $(NPM) run mobile:sync

## Open Capacitor Android project in Android Studio.
mobile-open-android:
	@cd $(FRONTEND_DIR) && $(NPM) run mobile:open-android

## Build Android debug APK.
mobile-apk-debug:
	@cd $(FRONTEND_DIR) && $(NPM) run mobile:apk-debug

## Verify mobile build prerequisites without packaging secrets.
mobile-check:
	@test -f "$(FRONTEND_DIR)/package.json" || { echo "frontend package missing"; exit 1; }
	@test -f "$(FRONTEND_DIR)/capacitor.config.ts" || { echo "Capacitor config missing"; exit 1; }
	@test -d "$(FRONTEND_DIR)/android" || { echo "Android platform missing. Run: cd frontend && npm run mobile:init"; exit 1; }
	@grep -q "VITE_API_BASE_URL" "$(FRONTEND_DIR)/.env.example" || { echo "VITE_API_BASE_URL missing from frontend/.env.example"; exit 1; }
	@grep -q "VITE_MOBILE_MODE" "$(FRONTEND_DIR)/.env.example" || { echo "VITE_MOBILE_MODE missing from frontend/.env.example"; exit 1; }
	@if rg -n "ghp_|github_pat_|sk-[A-Za-z0-9]|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY" "$(FRONTEND_DIR)/src" "$(FRONTEND_DIR)/capacitor.config.ts" "$(FRONTEND_DIR)/android" >/tmp/mobile-secret-scan.txt; then cat /tmp/mobile-secret-scan.txt; echo "Potential hardcoded secret found"; exit 1; fi
	@$(MAKE) mobile-build
	@echo "mobile check ok"

## Build Docker images if Docker Compose is available.
docker-build:
	@if [ -z "$(COMPOSE)" ]; then echo "Docker Compose is not available."; exit 1; fi
	$(COMPOSE) build

## Print a safe real-GitHub end-to-end demo checklist.
github-e2e-checklist:
	$(PYTHON) scripts/github_e2e_checklist.py

## Preview files that will be archived for final submission.
prepare-submission-dry-run:
	@echo "Submission dry-run: files that would be archived"
	@set -eu; \
	for path in $(SUBMISSION_INCLUDE); do \
		if [ -e "$$path" ]; then \
			find "$$path" \
				\( -path "*/.git" -o -path "*/__MACOSX" -o -path "*/__pycache__" -o -path "*/.pytest_cache" -o -path "*/.mypy_cache" -o -path "*/.ruff_cache" -o -path "*/htmlcov" -o -path "*/node_modules" -o -path "*/venv" -o -path "*/.venv" -o -path "*/.gradle" -o -path "frontend/dist" -o -path "frontend/build" -o -path "frontend/android/build" -o -path "frontend/android/app/build" -o -path "frontend/android/capacitor-cordova-android-plugins/build" -o -path "desktop/dist" -o -path "desktop/release" -o -path "desktop/out" \) -prune \
				-o -type f \
				! -name ".env" \
				! -name "*.db" \
				! -name "*.sqlite" \
				! -name "*.sqlite3" \
				! -name "*.pyc" \
				! -name ".coverage*" \
				! -name "*.log" \
				! -name "*.tmp" \
				! -name "*.temp" \
				! -name "*~" \
				! -name ".DS_Store" \
				! -name "local.properties" \
				-print; \
		fi; \
	done | sort

## Create clean final submission ZIP without secrets, temp files, caches, databases, or Git metadata.
prepare-submission:
	@command -v zip >/dev/null 2>&1 || { echo "zip is not installed."; exit 1; }
	@rm -rf "$(SUBMISSION_DIR)"
	@mkdir -p "$(SUBMISSION_DIR)"
	@set -eu; \
	existing_paths=""; \
	for path in $(SUBMISSION_INCLUDE); do \
		if [ -e "$$path" ]; then existing_paths="$$existing_paths $$path"; fi; \
	done; \
	if [ -z "$$existing_paths" ]; then echo "No submission files found."; exit 1; fi; \
	zip -qr "$(SUBMISSION_ZIP)" $$existing_paths \
		-x ".git/*" \
		-x "*/.git/*" \
		-x "__MACOSX/*" \
		-x "*/__MACOSX/*" \
		-x ".env" \
		-x "*/.env" \
		-x "*.db" \
		-x "*.sqlite" \
		-x "*.sqlite3" \
		-x "*/__pycache__/*" \
		-x "*.pyc" \
		-x "*/.pytest_cache/*" \
		-x "*/.mypy_cache/*" \
		-x "*/.ruff_cache/*" \
		-x ".coverage*" \
		-x "*/.coverage*" \
		-x "htmlcov/*" \
		-x "*/htmlcov/*" \
		-x "node_modules/*" \
		-x "*/node_modules/*" \
		-x "frontend/dist/*" \
		-x "frontend/build/*" \
		-x "frontend/android/.gradle/*" \
		-x "frontend/android/local.properties" \
		-x "frontend/android/build/*" \
		-x "frontend/android/app/build/*" \
		-x "frontend/android/capacitor-cordova-android-plugins/build/*" \
		-x "desktop/dist/*" \
		-x "desktop/release/*" \
		-x "desktop/out/*" \
		-x "venv/*" \
		-x "*/venv/*" \
		-x ".venv/*" \
		-x "*/.venv/*" \
		-x "*.log" \
		-x "*.tmp" \
		-x "*.temp" \
		-x "*~" \
		-x ".DS_Store" \
		-x "*/.DS_Store"; \
	echo "Created $(SUBMISSION_ZIP)"

## Remove generated caches, build output, and local dependency installs. Keeps source, docs, env files, datasets, models, and DB volumes.
clean:
	@find . \
		\( -path "./.git" -o -path "./$(BACKEND_VENV)" -o -path "./$(FRONTEND_DIR)/node_modules" -o -path "./$(DESKTOP_DIR)/node_modules" -o -path "./.venv" -o -path "./venv" -o -path "./postgres_data" -o -path "./redis_data" \) -prune \
		-o -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" -o -name "htmlcov" \) -prune -exec rm -rf {} +
	@find . \
		\( -path "./.git" -o -path "./$(BACKEND_VENV)" -o -path "./$(FRONTEND_DIR)/node_modules" -o -path "./$(DESKTOP_DIR)/node_modules" -o -path "./.venv" -o -path "./venv" -o -path "./postgres_data" -o -path "./redis_data" \) -prune \
		-o -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".coverage*" -o -name "coverage.xml" -o -name ".DS_Store" -o -name "*.log" \) -delete
	@rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/build
	@rm -rf $(FRONTEND_DIR)/android/.gradle $(FRONTEND_DIR)/android/build $(FRONTEND_DIR)/android/app/build $(FRONTEND_DIR)/android/capacitor-cordova-android-plugins/build
	@rm -rf $(DESKTOP_DIR)/dist $(DESKTOP_DIR)/release $(DESKTOP_DIR)/out
	@rm -rf $(BACKEND_DIR)/dist $(BACKEND_DIR)/build
	@rm -rf dist build htmlcov
	@rm -rf $(FRONTEND_DIR)/node_modules $(DESKTOP_DIR)/node_modules $(BACKEND_VENV) .venv venv
	@echo "Removed generated caches, build outputs, and local dependency installs."

## Stop Docker Compose services.
docker-down:
	@if [ -z "$(COMPOSE)" ]; then echo "Docker Compose is not available."; exit 1; fi
	$(COMPOSE) down

## Show Docker Compose logs.
docker-logs:
	@if [ -z "$(COMPOSE)" ]; then echo "Docker Compose is not available."; exit 1; fi
	$(COMPOSE) logs -f

## Stop containers and remove generated files/dependencies. Does not delete Docker volumes or databases.
reset: docker-down clean
	@echo "Reset complete. Docker volumes and database files were not removed."
