# The production build of the frontend, served by Caddy (deploy/Caddyfile).
FROM node:22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && node scripts/check-bundle.mjs

FROM caddy:2
COPY --from=build /app/dist /srv
