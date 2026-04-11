# Quarry Runbook

## Installation

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies (CPU-only torch, avoids ~2GB CUDA deps)
pip install -e ".[dev]" -c constraints.txt
```

> **Important:** Always include `-c constraints.txt`. Without it, pip will install
> the default CUDA-enabled PyTorch (~2GB of NVIDIA/CUDA packages). If you
> accidentally install without constraints, run:
> ```bash
> pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cpu
> pip uninstall -y cuda-bindings cuda-pathfinder cuda-toolkit nvidia-cublas \
>   nvidia-cuda-cupti nvidia-cuda-nvrtc nvidia-cuda-runtime nvidia-cudnn-cu13 \
>   nvidia-cufft nvidia-cufile nvidia-curand nvidia-cusolver nvidia-cusparse \
>   nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvjitlink nvidia-nvshmem-cu13 \
>   nvidia-nvtx triton
> ```

## Setup

```bash
# 3. Copy config template
cp config.yaml.example config.yaml
# Edit config.yaml with your LLM provider credentials

# 4. Initialize the database
python -m quarry.store init

# 5. Seed companies
python -m quarry.agent.tools seed
```

Expected output:
```
Seeded 29 companies, skipped 0
```

Running `seed` again will skip existing companies:
```
Seeded 0 companies, skipped 29
```

## Seeding Details

The `seed` command reads `seed_data.yaml` from the project root (configurable
via `seed_file` in `config.yaml`). Each entry becomes a `Company` record:

```yaml
- name: OpenAI                    # required
  domain: openai.com              # optional
  careers_url: https://openai.com/careers  # optional
  ats_type: greenhouse            # greenhouse | lever | ashby | generic | unknown
  ats_slug: openai                # ATS board slug (e.g. boards.greenhouse.io/{slug})
  crawl_priority: 8               # 1-10, default 5
  added_reason: Leading AI lab     # optional
```

To add more companies, edit `seed_data.yaml` and re-run `python -m quarry.agent.tools seed`.
Existing companies are skipped by name.

## Running

```bash
# Single search cycle
python -m quarry.agent.agent --run-once

# Continuous scheduler
python -m quarry.agent.scheduler

# Labeling UI
python -m quarry.ui.app
```

## Testing & Linting

```bash
python -m pytest                              # Run all tests
ruff check .                                  # Lint (auto-fix: --fix)
PYTHONPATH=/home/kurtt/job-search pyright quarry/  # Type check
```