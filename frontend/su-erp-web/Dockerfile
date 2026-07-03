# syntax=docker/dockerfile:1
#
# su-erp-web — Next.js production image.
# Build context is this directory (frontend/su-erp-web).
#   docker build -t suerp/web frontend/su-erp-web

# --- builder stage: install deps and produce the production build ----------
FROM node:20-alpine AS builder

WORKDIR /app

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so
# the gateway URL must be present as a build arg (not just runtime env).
ARG NEXT_PUBLIC_GATEWAY_URL=http://localhost:8080
ENV NEXT_PUBLIC_GATEWAY_URL=$NEXT_PUBLIC_GATEWAY_URL

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- runner stage: serve the built app with `next start` -------------------
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app ./

EXPOSE 3000

CMD ["npm", "start"]
