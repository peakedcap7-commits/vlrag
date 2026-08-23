FROM python:3.12-slim

ARG TARGETARCH
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN test "$TARGETARCH" = "amd64" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY tools ./tools
RUN curl --fail --location --retry 5 --retry-delay 2 --retry-all-errors \
        --connect-timeout 15 \
        --output "/tmp/torch-2.6.0+cpu-cp312-cp312-linux_x86_64.whl" \
        "https://download.pytorch.org/whl/cpu/torch-2.6.0%2Bcpu-cp312-cp312-linux_x86_64.whl" \
    && pip install "/tmp/torch-2.6.0+cpu-cp312-cp312-linux_x86_64.whl" \
    && rm -f "/tmp/torch-2.6.0+cpu-cp312-cp312-linux_x86_64.whl" \
    && pip install ".[graph]"

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
