# Glama foreground sandbox only; not the production service deployment.
FROM rust:1.97.1-bookworm@sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97 AS rust
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS build
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH=/usr/local/cargo/bin:$PATH RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir maturin==1.15.0 uv==0.12.10
WORKDIR /build
COPY Cargo.toml Cargo.lock build.rs rust-toolchain.toml pyproject.toml README.md uv.lock ./
COPY src ./src
COPY omneum ./omneum
RUN uv export --locked --no-default-groups --no-dev --no-emit-project --output-file /runtime-requirements.txt \
 && maturin build --locked --release --out /wheels \
 && cargo build --locked --release --no-default-features --features daemon --bin omneumd

FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS runtime
ENV OMNEUM_DISCOVERY_SANDBOX=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMNEUM_CONFIG_DIR=/var/lib/omneum/config
RUN apt-get update && apt-get install -y --no-install-recommends systemd util-linux \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /runtime-requirements.txt /tmp/runtime-requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/runtime-requirements.txt && rm /tmp/runtime-requirements.txt
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && rm -rf /tmp/wheels
COPY --from=build /build/target/release/omneumd /opt/omneum-discovery/omneumd
COPY deploy/install-foreground.sh /opt/omneum-discovery/install-foreground.sh
COPY deploy/sysusers.d/omneum.conf /opt/omneum-discovery/sysusers.d/omneum.conf
COPY deploy/discovery/entrypoint.sh deploy/discovery/omneum-server /opt/omneum-discovery/
RUN chmod 755 /opt/omneum-discovery/entrypoint.sh /opt/omneum-discovery/omneum-server
# Root only provisions/supervises fixed processes. Daemon and MCP use separate non-root UIDs.
ENTRYPOINT ["/opt/omneum-discovery/entrypoint.sh"]

# Local verification only: the default Glama image has no Node.js dependency.
FROM runtime AS probe
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
COPY deploy/discovery/mcpb /opt/omneum-discovery/mcpb
COPY tools/discovery_mcp_probe.py /opt/omneum-discovery/probe.py

FROM runtime AS glama
