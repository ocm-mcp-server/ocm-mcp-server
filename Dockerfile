# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

# Base image pinned by digest (python:3.12-slim). Dependabot's docker ecosystem proposes
# digest bumps; update the tag comment alongside the digest.
# NOTE: pin the multi-arch INDEX digest (docker buildx imagetools inspect python:3.12-slim),
# never a platform manifest digest - an arm64-only pin makes amd64 CI builds fail with
# "exec format error".
FROM python@sha256:3a9d2dd3f18e5c7a9d8de7b3659418a4ab848ccd409fb9e91ef9d7a6a3520ba7

# The MCP Registry validates OCI-package ownership against this label; without
# it the registry refuses to list the image (as of the 0.3.0 publish).
LABEL io.modelcontextprotocol.server.name="io.github.sandeepbazar/ocm-mcp-server"

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
