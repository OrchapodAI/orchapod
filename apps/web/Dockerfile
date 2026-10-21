# Production web image for infra/docker-compose.prod.yml (docs/HOSTING.md). Build context: apps/web.
# Next.js bakes NEXT_PUBLIC_* in at build time, so the public URLs (the API's, and the site's own for link previews) are
# build args; without them the build stops rather than ship a localhost fallback.
FROM node:22-alpine

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# CI's pnpm major (lockfile v9)
RUN npm install -g pnpm@9.15.9
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile
COPY . .

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_SITE_URL
RUN test -n "$NEXT_PUBLIC_API_URL" && test -n "$NEXT_PUBLIC_WS_URL" && test -n "$NEXT_PUBLIC_SITE_URL" && pnpm build

EXPOSE 3000
CMD ["node_modules/.bin/next", "start"]
