# Build the native Python extension and the protected evaluator from locked Rust sources.
FROM rust:1.90.0-bookworm AS rust
FROM python:3.13.7-slim-bookworm AS build
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH=/usr/local/cargo/bin:$PATH RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir maturin==1.15.0
WORKDIR /build
COPY Cargo.toml Cargo.lock build.rs pyproject.toml README.md ./
COPY src ./src
COPY omneum ./omneum
RUN maturin build --locked --release --out /wheels && cargo build --locked --release --no-default-features --features daemon --bin omneumd

FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 omneum-ipc && useradd --uid 10001 --gid 10001 --no-create-home network && useradd --uid 10002 --gid 10001 --no-create-home evaluator
COPY deploy/network/requirements.txt /tmp/network-requirements.txt
RUN pip install --no-cache-dir -r /tmp/network-requirements.txt && rm /tmp/network-requirements.txt
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && rm -rf /tmp/wheels
COPY --from=build /build/target/release/omneumd /usr/local/bin/omneumd
COPY deploy/network /opt/omneum-deploy
USER 10001:10001
EXPOSE 8443
CMD ["python", "-m", "omneum.network_api"]
