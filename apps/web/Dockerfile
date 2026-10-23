# syntax=docker/dockerfile:1.7
# Image du frontend Kora (Next.js en mode standalone).

FROM node:24-bookworm-slim AS deps
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json .npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit

FROM deps AS build
COPY . .
RUN npm run build

FROM node:24-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN groupadd --system --gid 10001 kora && useradd --system --uid 10001 --gid kora kora
COPY --from=build --chown=kora:kora /app/.next/standalone ./
COPY --from=build --chown=kora:kora /app/.next/static ./.next/static
COPY --from=build --chown=kora:kora /app/public ./public
USER kora
EXPOSE 3000
CMD ["node", "server.js"]
