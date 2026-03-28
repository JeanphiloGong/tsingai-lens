FROM node:20-alpine AS build

ARG PUBLIC_API_BASE_URL=same-origin

WORKDIR /app

ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
