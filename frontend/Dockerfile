FROM node:22-alpine AS build

ARG PUBLIC_API_BASE_URL=same-origin

WORKDIR /app

ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

ENV NGINX_ENVSUBST_FILTER=^LENS_PUBLIC_URL$
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
