# Source is fetched once through authenticated gh by scripts/dev/runtime.py.
FROM golang:1.22.4-alpine3.20@sha256:ace6cc3fe58d0c7b12303c57afe6d6724851152df55e08057b43990b927ad5e8 AS build
ENV GOMAXPROCS=2 CGO_ENABLED=0 GOPROXY=https://proxy.golang.org
WORKDIR /src
COPY --from=minio_source . .
RUN test "$(cat .dc2-source-commit)" = "20960b6a2ddb9594ee418035b3c7c7fe92ae6a12"
# Archive builds have no .git; supply the actual pinned release identity directly.
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go build -p 1 -tags kqueue -trimpath -ldflags '-s -w -X github.com/minio/minio/cmd.Version=2024-06-13T22:53:53Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2024-06-13T22-53-53Z -X github.com/minio/minio/cmd.CommitID=20960b6a2ddb9594ee418035b3c7c7fe92ae6a12 -X github.com/minio/minio/cmd.ShortCommitID=20960b6a2ddb -X github.com/minio/minio/cmd.CopyrightYear=2024' -o /out/minio .
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
LABEL org.opencontainers.image.revision="20960b6a2ddb9594ee418035b3c7c7fe92ae6a12"
RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/local/bin/minio
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/minio"]
