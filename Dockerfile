# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

# Base image pinned by digest (python:3.12-slim). Dependabot's docker ecosystem proposes
# digest bumps; update the tag comment alongside the digest.
FROM python@sha256:55842c72c6b3584d06ec84c731fc516b30b8a53ad262ebd085e47ab568b3bfc1

WORKDIR /app

# Install dependencies from the hash-pinned lock first (reproducible, tamper-evident),
# then the package itself with no further dependency resolution.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

# The server needs a kubeconfig mounted read-only and the usual env:
#   docker run -v ~/.kube/config:/kube/config:ro \
#     -e KUBECONFIG=/kube/config \
#     -e OCM_MCP_HUB_CONTEXT=... -e OCM_MCP_SPOKE_CONTEXTS=... \
#     ghcr.io/sandeepbazar/ocm-mcp-server
RUN useradd --create-home app
USER app
ENV OCM_MCP_HOME=/home/app/.ocm-mcp

ENTRYPOINT ["ocm-mcp-server"]
