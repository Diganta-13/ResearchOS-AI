# ResearchOS AI

**Autonomous Personal AI Research Operating System**  
*Codename: JARVIS-Academic | Specification Version: 2.1.0*

---

## 1. Executive Overview

ResearchOS AI is a unified, locally hosted personal AI agent engineered to manage an academic researcher's complete lifecycle: literature analysis, IEEE/ACM LaTeX writing, experiment monitoring, bibliography management, and automated reasoning.

### Hardware Execution Envelope
* **Host CPU**: Intel Core i7-8665U (4 physical cores, 8 threads, AVX2, 15W TDP nominal).
* **Inference Strategy**: Strictly **CPU-first**. Ollama and vector embeddings are constrained to 4 execution threads (`OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4`) to prevent thermal throttling and reserve 4 logical threads for the OS, GUI, and IDE.
* **Host RAM**: 16 GB DDR4 (15.82 GiB physical). Combined agent runtime and local model memory footprint is budgeted to never exceed **10.50 GiB**, preserving $\ge 5.30\text{ GiB}$ for the OS and external tools. Small quantized models (1.5B–3B parameters) are deployed and benchmarked prior to any 7B evaluation.
* **Dedicated GPU**: AMD Radeon Pro WX3200 4GB (Polaris architecture). Windows lacks ROCm support for Polaris; GPU execution is reserved strictly for display rendering, GUI compositing, and video decoding.

---

## 2. Storage Partitioning & Isolation Policy

All persistent data, model weights, embeddings, databases, package caches, and temporary artifacts reside strictly on **Drive D:** to eliminate capacity exhaustion hazards on Drive C:.

### Capacity & Reservation Accounting (Strict GiB Units)

| Storage Metric | Capacity (GiB) | Status & Compliance |
| :--- | :---: | :--- |
| **Drive C: Free Space** | **48.16 GiB** | Protected ($\ge 15.00\text{ GiB}$ safety threshold enforced; zero tool caches permitted) |
| **Drive D: Free Space** | **135.30 GiB** | Primary workspace ($\ge 130.00\text{ GiB}$ pre-installation floor satisfied) |
| **Mandatory Pre-Installation Floor** | **130.00 GiB** | Enforced prior to Phase 1 dependency installation |
| **Baseline Lifecycle Footprint** | **45.00 GiB** | Local models (~28 GiB), embeddings (~1.5 GiB), DB/FTS5 (~3.5 GiB), caches/venv (~2.5 GiB), docs (~9.5 GiB) |
| **Heavy-Usage Peak Footprint** | **65.00 GiB** | Multi-model evaluation + large academic corpus ingestion |
| **Internal Operational Reserve Policy** | **50.00 GiB** | Preserved free space floor on Drive D: during active runtime |
| **Expected Remaining Space (Baseline)** | **90.30 GiB** | $135.30\text{ GiB} - 45.00\text{ GiB} = \mathbf{90.30\text{ GiB}}$ ($+40.30\text{ GiB}$ above reserve) |
| **Expected Remaining Space (Heavy-Use)**| **70.30 GiB** | $135.30\text{ GiB} - 65.00\text{ GiB} = \mathbf{70.30\text{ GiB}}$ ($+20.30\text{ GiB}$ above reserve) |

All directory redirects are configured in `config/storage_paths.yaml`:
```powershell
$env:OLLAMA_MODELS        = "D:\Projects\ResearchOS-AI\storage\.ollama\models"
$env:HF_HOME              = "D:\Projects\ResearchOS-AI\storage\.cache\huggingface"
$env:FASTEMBED_CACHE_PATH = "D:\Projects\ResearchOS-AI\storage\.cache\fastembed"
$env:PIP_CACHE_DIR        = "D:\Projects\ResearchOS-AI\storage\.cache\pip"
$env:TEMP                 = "D:\Projects\ResearchOS-AI\storage\.cache\tmp"
$env:TMP                  = "D:\Projects\ResearchOS-AI\storage\.cache\tmp"
```

---

## 3. Architecture & Security Model

### Deterministic State Machine Engine (`engine.py`)
Phase 1 implements a deterministic Finite State Machine (FSM) managing structured task lifecycles (`INITIALIZING` $\rightarrow$ `ANALYZING` $\rightarrow$ `PLANNING` $\rightarrow$ `AWAITING_APPROVAL` $\rightarrow$ `EXECUTING` $\rightarrow$ `VERIFYING` $\rightarrow$ `COMPLETED`).  
* **Scope Definition**: The FSM is the **Phase 1 agent orchestration foundation**, not a complete autonomous AI agent.
* **Zero External Graph Bloat**: Written in pure Python and Pydantic v2 without heavy third-party agent graph frameworks, keeping memory overhead $< 5\text{ MB}$.

### Security & Subprocess Isolation
* **Untrusted Code Execution Disabled**: Arbitrary shell execution and unvetted dynamic evaluation (`eval`, `exec`) are strictly prohibited. Subprocess execution is restricted to allowlisted executables (`git.exe`, `pdflatex.exe`, `python.exe`) using static argument validation, `shell=False`, timeouts, and path containment within `D:\Projects\ResearchOS-AI`.
* **Application Authorization vs. OS Sandboxing**: Application-level Human-in-the-Loop (HITL) approval workflows enforce user confirmation before any consequential operation. Application approvals do not constitute OS-level process sandboxing; kernel-level job objects and isolation boundaries will be introduced in Phase 3.

### SQLite Database & Concurrency
* **WAL Mode Persistence**: `PRAGMA journal_mode = WAL;` is executed once during database initialization/migration. Connection factory handles verify WAL mode on connection open.
* **Per-Connection Isolation**: Every connection sets `PRAGMA foreign_keys = ON;`, `PRAGMA busy_timeout = 5000;`, `PRAGMA synchronous = NORMAL;`, and `PRAGMA cache_size = -64000;`.
* **Safe Transaction Rollback Guard**: Transaction rollbacks are guarded with `if conn.in_transaction:` to prevent secondary `OperationalError` exceptions when `BEGIN IMMEDIATE` fails.
* **FTS5 Synchronization**: Full-text search tables are maintained automatically via atomic `AFTER INSERT`, `AFTER DELETE`, and `AFTER UPDATE` triggers.

---

## 4. Single Source of Truth & Dependency Management

`pyproject.toml` defines the single authoritative dependency specification. Transitive dependency locks with cryptographic SHA-256 hashes are compiled using `pip-tools`.

### Toolchain Bootstrap Specifications
* `pip==25.0.1`
* `setuptools==75.8.0`
* `wheel==0.45.1`
* `pip-tools==7.4.4`

### Lockfile Compilation (Windows 11 AMD64, Python 3.12)
```powershell
# 1. Compile runtime lockfile with SHA-256 hashes
.\.venv\Scripts\pip-compile.exe --generate-hashes --allow-unsafe --resolver=backtracking --cache-dir D:\Projects\ResearchOS-AI\storage\.cache\pip --output-file=requirements-lock.txt pyproject.toml

# 2. Compile development lockfile (inherits runtime dependencies + dev extras)
.\.venv\Scripts\pip-compile.exe --extra dev --generate-hashes --allow-unsafe --resolver=backtracking --cache-dir D:\Projects\ResearchOS-AI\storage\.cache\pip --output-file=requirements-dev-lock.txt pyproject.toml
```

### Installation
For local development, install **only** `requirements-dev-lock.txt` (which installs all runtime and dev packages in a single pass), followed by an editable project install:
```powershell
# 1. Single-pass hash-verified installation
.\.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements-dev-lock.txt --cache-dir D:\Projects\ResearchOS-AI\storage\.cache\pip

# 2. Editable package install
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

---

## 5. Verification Procedures

Post-installation verification requires passing all five validation gates:
```powershell
# Gate 1: Dependency tree consistency
.\.venv\Scripts\python.exe -m pip check

# Gate 2: Hash-locked manifest security audit
.\.venv\Scripts\python.exe -m pip_audit --require-hashes -r requirements-dev-lock.txt

# Gate 3: Installed environment security audit
.\.venv\Scripts\python.exe -m pip_audit --local

# Gate 4: Module import verification
.\.venv\Scripts\python.exe -c "import fastapi, starlette, pydantic, pydantic_settings, uvicorn, dotenv, yaml, psutil, pytest, httpx, ruff, pygments; print('ALL MODULES IMPORTED SUCCESSFULLY')"

# Gate 5: Application instantiation verification
.\.venv\Scripts\python.exe -c "from researchos.api.app import app; print(f'FastAPI app instantiated: {app.title}')"
```

---

## 6. Development & Application Startup

### Running the Backend Service
Start the FastAPI application daemon locally:
```powershell
.\.venv\Scripts\python.exe -m uvicorn researchos.api.app:app --host 127.0.0.1 --port 8000 --reload
```

### Running Automated Tests
```powershell
# Execute unit and integration tests with coverage
.\.venv\Scripts\pytest.exe -v --cov=src/researchos tests/unit

# Execute Ruff linting and formatting verification
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
```

---

## 7. Project Structure

```
D:\Projects\ResearchOS-AI\
├── ResearchOS_AI_MASTER_SPEC_v2.md        # Preserved baseline specification
├── ResearchOS_AI_MASTER_SPEC_v2.1.0.md    # Formally amended specification (v2.1.0)
├── pyproject.toml                         # Single authoritative dependency & build definition
├── README.md                              # System architecture & operating manual
├── config/
│   ├── storage_paths.yaml                 # D: drive storage mapping & C: protection redirects
│   └── environment_report.json            # Phase 0 hardware profile
├── scripts/
│   └── verify_env.py                      # Phase 0 physical environment audit script
├── src/
│   └── researchos/
│       ├── __init__.py
│       ├── core/                          # Configuration, logging, security, exceptions
│       ├── memory/                        # SQLite manager, WAL, migrations, FTS5 sync
│       ├── agents/                        # Deterministic state machine orchestrator
│       └── api/                           # FastAPI app factory, routes, health diagnostics
└── tests/
    └── unit/                              # Unit test suite (db, security, config, fts, health)
```

---

## 8. License

*Note: Project license selection is pending formal user assignment. No LICENSE file is generated in Stage 1.*
