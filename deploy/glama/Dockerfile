# Dedicated local MCP inspection image; the root Dockerfile serves the Network API.
FROM rust:1.97.1-bookworm AS rust
FROM python:3.13.15-slim-bookworm AS build
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH=/usr/local/cargo/bin:$PATH RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir maturin==1.15.0
WORKDIR /build
COPY Cargo.toml Cargo.lock build.rs pyproject.toml README.md LICENSE ./
COPY src ./src
COPY omneum ./omneum
RUN maturin build --locked --release --out /wheels \
    && cargo build --locked --release --no-default-features --features daemon --bin omneumd

FROM python:3.13.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends systemd util-linux && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /tmp/wheels
RUN python -m pip install --no-cache-dir --only-binary=:all: /tmp/wheels/*.whl && rm -rf /tmp/wheels
COPY --from=build /build/target/release/omneumd /opt/omneum-glama/daemon/omneumd
COPY deploy/install-foreground.sh /opt/omneum-glama/daemon/install-foreground.sh
COPY deploy/sysusers.d/omneum.conf /opt/omneum-glama/daemon/sysusers.d/omneum.conf
COPY deploy/glama/start.py /opt/omneum-glama/start.py
CMD ["python", "-I", "/opt/omneum-glama/start.py"]
