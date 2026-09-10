# syntax=docker/dockerfile:1
FROM node:22.18.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run typecheck && npm run build

FROM nginx:1.28.0-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/hub.conf.template
COPY entrypoint.sh /usr/local/bin/hub-entrypoint
RUN chmod +x /usr/local/bin/hub-entrypoint
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/hub-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
