FROM golang:1.27.1-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/user-service ./cmd/user-service
RUN CGO_ENABLED=0 GOBIN=/out go install -tags='no_clickhouse no_duckdb no_libsql no_mssql no_mysql no_sqlite3 no_vertica no_ydb' github.com/pressly/goose/v3/cmd/goose@v3.24.3

FROM alpine:3.22
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/user-service /app/user-service
COPY --from=build /out/goose /usr/local/bin/goose
COPY migrations /app/migrations
USER 65532:65532
EXPOSE 8097 50057
ENTRYPOINT ["/app/user-service"]
