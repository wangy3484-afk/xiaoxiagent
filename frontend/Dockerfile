FROM node:22-alpine

ENV NODE_ENV=development

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

USER node

EXPOSE 4173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "4173"]
