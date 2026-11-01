# syntax=docker/dockerfile:1.7
FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Unprivileged nginx: serves the SPA and proxies /api to the backend on the same origin (no CORS).
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV API_UPSTREAM=http://api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
