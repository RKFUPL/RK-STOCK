FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3006
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app ./
EXPOSE 3006
CMD ["npm", "run", "start"]
