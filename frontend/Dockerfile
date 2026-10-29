FROM node:22-slim AS build
WORKDIR /src
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

# Caddy serves the app, proxies /api, and obtains the TLS certificate automatically.
FROM caddy:2.10
COPY --from=build /src/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
