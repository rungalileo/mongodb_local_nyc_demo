# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# ---------------------------------------------------------------------------
# Build
#
# NEXT_PUBLIC_* values are inlined into the browser bundle here, which is why
# lib/api.ts deliberately resolves to a *relative* API base in production: the
# published image must not be pinned to one backend hostname.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


# ---------------------------------------------------------------------------
# Runtime: Next.js standalone output (server.js + traced deps only).
# ---------------------------------------------------------------------------
FROM node:22-alpine
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# standalone bundles the server and its traced dependencies; static assets and
# public/ are not included and must be copied alongside it.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

# `node` (uid 1000) ships with the base image.
USER node

EXPOSE 3000

CMD ["node", "server.js"]
