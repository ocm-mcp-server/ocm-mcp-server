# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[tracing]"

# The server needs a kubeconfig mounted read-only and the usual env:
#   docker run -v ~/.kube/config:/kube/config:ro \
#     -e KUBECONFIG=/kube/config \
#     -e OCM_MCP_HUB_CONTEXT=... -e OCM_MCP_SPOKE_CONTEXTS=... \
#     ghcr.io/sandeepbazar/ocm-mcp-server
RUN useradd --create-home app
USER app
ENV OCM_MCP_HOME=/home/app/.ocm-mcp

ENTRYPOINT ["ocm-mcp-server"]
