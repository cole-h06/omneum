# Disposable deployment verification only; never use this image in production.
FROM omneum-network:vm-audit
USER root
RUN apt-get update && apt-get install -y --no-install-recommends nginx systemd postgresql postgresql-contrib && rm -rf /var/lib/apt/lists/*
ENV OMNEUM_VM_DISPOSABLE=1
ENTRYPOINT ["python", "/repo/tests/security/vm_deployment.py"]
