# Frontend dev image for Orient Recruitment Accelerator.
# Production builds should serve the static `dist/` output via the reverse proxy.
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
