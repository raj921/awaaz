# Single image: Go gateway + stdlib-only Python memory sidecar.
# No pip install step exists because there are no Python dependencies.
FROM golang:1.24-bookworm AS build
WORKDIR /src/backend
COPY backend/go.mod ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -o /api ./cmd/api

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=build /api /app/api
COPY research/memory/*.py /app/memory/
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
ENV PORT=8080 MEMORY_DB=/data/memory.db
EXPOSE 8080
VOLUME /data
CMD ["/app/start.sh"]
