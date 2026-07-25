FROM python:3.12-slim
# A pyrit dependency compiles a Rust extension (maturin/pyo3) → a Rust toolchain
# is required; the Debian `cargo` package is too old, so use rustup.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --no-cache-dir pyrit
ENTRYPOINT ["python", "-m", "pyrit.orchestrator.red_teaming_orchestrator"]
