.PHONY: help install install-basic install-cv install-ocr install-full
.PHONY: dev test lint format clean
.PHONY: add add-dev remove update show
.PHONY: convert embed process
.PHONY: test-cv test-ocr test-ml
.PHONY: setup-models download-models

# Poetry with local virtual environment
POETRY = poetry
PYTHON = $(POETRY) run python
PIP = $(POETRY) run pip
PYTEST = $(POETRY) run pytest

# NVIDIA library paths for PyTorch bundled cuDNN/cuBLAS (needed for GPU inference)
NVIDIA_PKGS := $(shell $(PYTHON) -c "import nvidia; print(nvidia.__path__[0])" 2>/dev/null)
ifdef NVIDIA_PKGS
export LD_LIBRARY_PATH := $(NVIDIA_PKGS)/cudnn/lib:$(NVIDIA_PKGS)/cublas/lib:$(NVIDIA_PKGS)/cuda_nvrtc/lib
endif

# Default target
help: ## Show this help message
	@echo "RAG Pipeline - Poetry + Local .venv"
	@echo "==================================="
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  make install-basic    # Install core dependencies with Poetry"
	@echo "  make install-full     # Install everything with Poetry (large download!)"
	@echo ""
	@echo "📦 Installation Options:"
	@awk 'BEGIN {FS = ":.*?## "} /^install.*:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "🛠️  Development Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | grep -E "(dev|test|lint|format|clean)"
	@echo ""
	@echo "🔄 Processing Commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | grep -E "(convert|embed|process|models)"
	@echo ""
	@echo "📦 Package Management:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | grep -E "(add|remove|update|show)"
	@echo ""
	@echo "💡 Examples:"
	@echo "  make convert INPUT=docs/ OUTPUT=processed/"
	@echo "  make add PKG=torch                    # Add package with Poetry"
	@echo "  make install-cv                      # Add CV support"
	@echo ""

# Installation commands
install: install-basic ## Install basic dependencies (alias for install-basic)

install-basic: ## Install core dependencies with Poetry in local .venv (fastest)
	@echo "📦 Installing basic RAG dependencies with Poetry..."
	@echo "🔧 Configuring Poetry to use local virtual environment..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	@echo "📦 Installing core dependencies..."
	$(POETRY) install
	@echo "✅ Basic dependencies installed in $(shell pwd)/.venv"
	@echo "📍 Virtual environment: $(shell $(POETRY) env info --path)"
	@echo "💡 For more features: make install-cv, make install-ocr, make install-full"

install-cv: ## Install with computer vision support
	@echo "📦 Installing with computer vision support..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with cv
	@echo "✅ Computer vision dependencies installed!"

install-ocr: ## Install with OCR support (large download)
	@echo "📦 Installing with OCR support (this may take a while)..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with ocr
	@echo "✅ OCR dependencies installed!"

install-video: ## Install with video processing support
	@echo "📦 Installing with video processing support..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with video
	@echo "✅ Video processing dependencies installed!"

install-web: ## Install with web scraping support
	@echo "📦 Installing with web scraping support..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with web
	@echo "✅ Web scraping dependencies installed!"

install-full: ## Install all features (LARGE download - 5GB+)
	@echo "🚨 WARNING: This will download 5GB+ of dependencies!"
	@echo "📦 Installing ALL RAG features with Poetry..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with cv,ocr,video,web
	@echo "✅ Full installation complete! All features available."

install-dev: ## Install with development dependencies
	@echo "📦 Installing with development dependencies..."
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) config virtualenvs.create true
	$(POETRY) install --with dev
	@echo "✅ Development environment ready!"

# Development
dev: ## Start development server
	@echo "🚀 Starting RAG development server..."
	$(PYTHON) -m file_conversion_router.api

dev-api: ## Start FastAPI development server
	@echo "🚀 Starting RAG API server..."
	$(POETRY) run uvicorn file_conversion_router.api:app --reload --port 8001

dev-convert-api: ## Start standalone conversion API service
	@echo "🚀 Starting conversion API server on port 8010..."
	$(POETRY) run uvicorn file_conversion_router.conversion_api:app --host 0.0.0.0 --port 8010

test: ## Run all tests (excludes OCR/GPU tests)
	@echo "🧪 Running all tests..."
	$(PYTEST) tests -m "not ocr and not gpu"

test-all: ## Run all tests including OCR/GPU
	@echo "🧪 Running all tests (including OCR/GPU)..."
	$(PYTEST) tests -v

test-ocr: ## Run OCR tests (MinerU + WhisperX)
	@echo "🧪 Running OCR tests..."
	$(PYTEST) tests -m ocr -v

# Code quality
lint: ## Run linting checks on RAG files only
	@echo "🔍 Running linting checks on RAG files..."
	$(POETRY) run ruff check .
	$(POETRY) run mypy file_conversion_router --ignore-missing-imports
	@echo "✅ RAG linting completed!"

format: ## Format RAG code only
	@echo "🎨 Formatting RAG code..."
	$(POETRY) run black .
	$(POETRY) run ruff format .
	@echo "✅ RAG code formatted!"

# RAG Processing commands
convert: ## Convert files (use: make convert INPUT=path/to/input OUTPUT=path/to/output)
	@if [ -z "$(INPUT)" ] || [ -z "$(OUTPUT)" ]; then \
		echo "❌ Usage: make convert INPUT=input_path OUTPUT=output_path"; \
		echo "Example: make convert INPUT=docs/ OUTPUT=processed/"; \
		exit 1; \
	fi
	@echo "🔄 Converting files from $(INPUT) to $(OUTPUT)..."
	$(PYTHON) -m file_conversion_router.api --input $(INPUT) --output $(OUTPUT)
	@echo "✅ File conversion completed!"

embed: ## Create embeddings (use: make embed INPUT=processed/ OUTPUT=embeddings/)
	@if [ -z "$(INPUT)" ] || [ -z "$(OUTPUT)" ]; then \
		echo "❌ Usage: make embed INPUT=processed_path OUTPUT=embeddings_path"; \
		echo "Example: make embed INPUT=processed/ OUTPUT=embeddings/"; \
		exit 1; \
	fi
	@echo "🧠 Creating embeddings from $(INPUT) to $(OUTPUT)..."
	$(PYTHON) -m file_conversion_router.embedding.table_create --input $(INPUT) --output $(OUTPUT)
	@echo "✅ Embedding creation completed!"

process: ## Full pipeline (use: make process INPUT=docs/ OUTPUT=final/)
	@if [ -z "$(INPUT)" ] || [ -z "$(OUTPUT)" ]; then \
		echo "❌ Usage: make process INPUT=input_path OUTPUT=output_path"; \
		echo "Example: make process INPUT=docs/ OUTPUT=final/"; \
		exit 1; \
	fi
	@echo "🔄 Running full RAG pipeline..."
	@echo "Step 1: Converting files..."
	$(PYTHON) -m file_conversion_router.api --input $(INPUT) --output $(OUTPUT)/processed
	@echo "Step 2: Creating embeddings..."
	$(PYTHON) -m file_conversion_router.embedding.table_create --input $(OUTPUT)/processed --output $(OUTPUT)/embeddings
	@echo "✅ Full pipeline completed!"

# Model management
download-models: ## Download required models
	@echo "📥 Downloading required models..."
	$(PYTHON) -c "from file_conversion_router.services import download_base_models; download_base_models()"
	@echo "✅ Models downloaded!"

setup-models: ## Setup and verify models
	@echo "🔧 Setting up models..."
	$(PYTHON) -c "from file_conversion_router.services import setup_models; setup_models()"
	@echo "✅ Models setup completed!"

# Package management with Poetry
add: ## Add production dependency (use: make add PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make add PKG=package-name"; exit 1; fi
	@echo "📦 Adding package $(PKG) with Poetry..."
	$(POETRY) add $(PKG)
	@echo "✅ Package $(PKG) added and pyproject.toml updated!"

add-dev: ## Add development dependency (use: make add-dev PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make add-dev PKG=package-name"; exit 1; fi
	@echo "📦 Adding development package $(PKG) with Poetry..."
	$(POETRY) add --group dev $(PKG)
	@echo "✅ Development package $(PKG) added!"

add-cv: ## Add computer vision dependency (use: make add-cv PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make add-cv PKG=package-name"; exit 1; fi
	@echo "📦 Adding CV package $(PKG) with Poetry..."
	$(POETRY) add --group cv $(PKG)
	@echo "✅ CV package $(PKG) added!"

add-ocr: ## Add OCR dependency (use: make add-ocr PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make add-ocr PKG=package-name"; exit 1; fi
	@echo "📦 Adding OCR package $(PKG) with Poetry..."
	$(POETRY) add --group ocr $(PKG)
	@echo "✅ OCR package $(PKG) added!"

remove: ## Remove dependency (use: make remove PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make remove PKG=package-name"; exit 1; fi
	@echo "📦 Removing package $(PKG) with Poetry..."
	$(POETRY) remove $(PKG)
	@echo "✅ Package $(PKG) removed and pyproject.toml updated!"

update: ## Update all dependencies
	@echo "⬆️  Updating dependencies with Poetry..."
	$(POETRY) update
	@echo "✅ Dependencies updated and poetry.lock refreshed!"

update-pkg: ## Update specific package (use: make update-pkg PKG=package-name)
	@if [ -z "$(PKG)" ]; then echo "❌ Usage: make update-pkg PKG=package-name"; exit 1; fi
	@echo "⬆️  Updating package $(PKG) with Poetry..."
	$(POETRY) update $(PKG)
	@echo "✅ Package $(PKG) updated!"

show: ## Show package info (use: make show PKG=package-name)
	@if [ -z "$(PKG)" ]; then \
		echo "📊 Showing all dependencies:"; \
		$(POETRY) show; \
	else \
		echo "📊 Showing package info: $(PKG)"; \
		$(POETRY) show $(PKG); \
	fi

show-tree: ## Show dependency tree
	@echo "📊 Dependency tree:"
	$(POETRY) show --tree

show-groups: ## Show available dependency groups
	@echo "📊 Available dependency groups:"
	@echo "  Core: Basic RAG functionality"
	@echo "  cv: Computer vision (opencv, image processing)"
	@echo "  ocr: OCR and document processing (heavy)"
	@echo "  video: Video processing"
	@echo "  web: Web scraping"
	@echo "  dev: Development tools"

export: ## Export requirements.txt for deployment
	@echo "📦 Exporting requirements.txt with Poetry..."
	$(POETRY) export --format=requirements.txt --output=requirements.txt --without-hashes
	@echo "✅ requirements.txt generated from pyproject.toml!"

save-env: ## Save current conda/pip environment snapshot
	@echo "📦 Saving environment snapshot..."
	$(PIP) freeze > yk_env2_requirements.txt
	@echo "✅ Environment saved to yk_env2_requirements.txt ($(shell wc -l < yk_env2_requirements.txt) packages)"

lock: ## Update poetry.lock file
	@echo "🔒 Updating poetry.lock..."
	$(POETRY) lock
	@echo "✅ Lock file updated!"

# Maintenance
clean: ## Clean build artifacts and cache in RAG directory
	@echo "🧹 Cleaning RAG build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf dist/ build/ .coverage htmlcov/ .tox/ .ruff_cache/
	@echo "✅ RAG cleanup completed!"

clean-models: ## Clean downloaded model cache
	@echo "🧹 Cleaning model cache..."
	@rm -rf ~/.cache/huggingface/transformers/
	@rm -rf ~/.cache/torch/hub/
	@echo "✅ Model cache cleaned!"

clean-outputs: ## Clean processing outputs in RAG directory
	@echo "🧹 Cleaning RAG processing outputs..."
	@rm -rf outputs/ processed/ embeddings/
	@echo "✅ RAG output directories cleaned!"

clean-venv: ## Remove virtual environment
	@echo "🗑️  Removing virtual environment..."
	$(POETRY) env remove --all
	@echo "✅ Virtual environment removed!"

# Virtual environment management
venv-info: ## Show virtual environment information
	@echo "🐍 Virtual Environment Information"
	@echo "================================="
	$(POETRY) env info

venv-activate: ## Show command to activate virtual environment manually
	@echo "🐍 To manually activate the virtual environment, run:"
	@echo "$(POETRY) shell"

venv-path: ## Show virtual environment path
	@echo "📍 Virtual environment path:"
	@$(POETRY) env info --path

venv-recreate: ## Recreate virtual environment
	@echo "🔄 Recreating virtual environment..."
	$(POETRY) env remove --all || true
	$(POETRY) config virtualenvs.in-project true
	$(POETRY) install
	@echo "✅ Virtual environment recreated!"

# Information and debugging
info: ## Show environment and installation info
	@echo "ℹ️  RAG Pipeline Environment"
	@echo "=========================="
	@echo "Python: $(shell python --version 2>/dev/null || echo 'Not found')"
	@echo "Poetry: $(shell $(POETRY) --version 2>/dev/null || echo 'Not found')"
	@echo "PyTorch: $(shell $(PYTHON) -c 'import torch; print(f\"PyTorch {torch.__version__} (CUDA: {torch.cuda.is_available()})\"' 2>/dev/null || echo 'Not installed')"
	@echo "Transformers: $(shell $(PYTHON) -c 'import transformers; print(transformers.__version__)' 2>/dev/null || echo 'Not installed')"
	@echo "OpenCV: $(shell $(PYTHON) -c 'import cv2; print(cv2.__version__)' 2>/dev/null || echo 'Not installed')"
	@echo "Working Directory: $(shell pwd)"
	@echo ""
	@echo "🔧 Virtual Environment:"
	@$(POETRY) env info --path 2>/dev/null || echo "❌ No virtual environment found"
	@echo ""
	@echo "🔧 Feature Status:"
	@echo "Basic: ✅ (always available)"
	@echo "CV: $(shell $(PYTHON) -c 'import cv2' 2>/dev/null && echo '✅ Available' || echo '❌ Not installed')"
	@echo "OCR: $(shell $(PYTHON) -c 'import paddleocr' 2>/dev/null && echo '✅ Available' || echo '❌ Not installed')"

check-deps: ## Check if optional dependencies are installed
	@echo "🔍 Checking optional dependencies..."
	@echo "Computer Vision:"
	@$(PYTHON) -c "import cv2; print('  ✅ OpenCV available')" 2>/dev/null || echo "  ❌ OpenCV not installed (make install-cv)"
	@echo "OCR:"
	@$(PYTHON) -c "import paddleocr; print('  ✅ PaddleOCR available')" 2>/dev/null || echo "  ❌ PaddleOCR not installed (make install-ocr)"
	@echo "Video:"
	@$(PYTHON) -c "import moviepy; print('  ✅ MoviePy available')" 2>/dev/null || echo "  ❌ MoviePy not installed (make install-video)"

# Quick setup workflows
setup-basic: install-basic download-models ## Quick setup with basic features
	@echo "🎉 Basic RAG setup complete!"
	@echo "Try: make convert INPUT=your_docs/ OUTPUT=processed/"

setup-full: install-full download-models ## Complete setup with all features
	@echo "🎉 Full RAG setup complete!"
	@echo "All features available including OCR, CV, and video processing."

# Benchmarking and performance
benchmark: ## Run performance benchmarks
	@echo "⚡ Running performance benchmarks..."
	$(PYTHON) -m file_conversion_router.benchmarks.run_benchmarks
	@echo "✅ Benchmarks completed!"
