# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

# Base image pinned by TAG *and* digest. The tag is load-bearing, not decoration:
# a bare `FROM python@sha256:...` gives Dependabot nothing to track, so it falls
# back to `python:latest` - which silently drifted this image from a ~87-package
# slim base to the ~469-package full one, dragging in HEIF/AVIF codecs and 64
# HIGH CVEs that failed the Trivy gate. Keep the tag on the FROM line.
# NOTE: pin the multi-arch INDEX digest (docker buildx imagetools inspect
# python:3.14-slim), never a platform manifest digest - an arm64-only pin makes
# amd64 CI builds fail with "exec format error".
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

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
