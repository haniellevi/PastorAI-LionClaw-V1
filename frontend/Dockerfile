FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY next.config.mjs tsconfig.json .eslintrc.json ./
COPY src ./src
COPY public ./public
ARG NEXT_PUBLIC_API_URL
ARG PASTORAI_FRONTEND_ORIGIN
ARG PASTORAI_RELEASE_SHA
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN test -n "$NEXT_PUBLIC_API_URL" && test -n "$PASTORAI_FRONTEND_ORIGIN" \
    && test ${#PASTORAI_RELEASE_SHA} -eq 40 && npm run build

FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS runtime
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ARG PASTORAI_FRONTEND_ORIGIN
ARG PASTORAI_RELEASE_SHA
LABEL org.opencontainers.image.revision=$PASTORAI_RELEASE_SHA \
      pastorai.api-origin=$NEXT_PUBLIC_API_URL \
      pastorai.frontend-origin=$PASTORAI_FRONTEND_ORIGIN
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
