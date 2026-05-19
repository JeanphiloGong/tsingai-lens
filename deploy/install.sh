#!/bin/sh
set -eu

REPO="${LENS_REPO:-JeanphiloGong/tsingai-lens}"
RAW_BASE="${LENS_RAW_BASE:-https://raw.githubusercontent.com/$REPO}"
VERSION="${LENS_VERSION:-v0.4.0}"
REF="${LENS_REF:-main}"
TARGET_DIR="${LENS_DEPLOY_DIR:-lens-deploy}"

usage() {
  cat <<'USAGE'
Usage: install.sh [--version vX.Y.Z] [--ref git-ref] [--dir path] [--repo owner/name]

Options:
  --version  Docker image tag to write into .env.
  --ref      Git ref used to download deploy files.
  --dir      Target directory. Defaults to ./lens-deploy.
  --repo     GitHub repository in owner/name form.
USAGE
}

die() {
  printf 'install: %s\n' "$*" >&2
  exit 1
}

need_value() {
  [ "${2:-}" ] || die "$1 requires a value"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      need_value "$1" "${2:-}"
      VERSION="$2"
      shift 2
      ;;
    --ref)
      need_value "$1" "${2:-}"
      REF="$2"
      shift 2
      ;;
    --dir)
      need_value "$1" "${2:-}"
      TARGET_DIR="$2"
      shift 2
      ;;
    --repo)
      need_value "$1" "${2:-}"
      REPO="$2"
      RAW_BASE="https://raw.githubusercontent.com/$REPO"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

download() {
  url="$1"
  output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$output"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$output" "$url"
  else
    die "curl or wget is required"
  fi
}

install_file() {
  file="$1"
  mkdir -p "$TARGET_DIR/$(dirname "$file")"
  download "$RAW_BASE/$REF/deploy/$file" "$TARGET_DIR/$file"
}

mkdir -p "$TARGET_DIR"

for file in \
  compose.yml \
  .env.example \
  backend.env.example \
  README.md \
  install.sh \
  scripts/lens \
  scripts/doctor.sh \
  scripts/upgrade.sh
do
  install_file "$file"
done

chmod +x "$TARGET_DIR/install.sh" \
  "$TARGET_DIR/scripts/lens" \
  "$TARGET_DIR/scripts/doctor.sh" \
  "$TARGET_DIR/scripts/upgrade.sh"

if [ ! -f "$TARGET_DIR/.env" ]; then
  sed "s/^LENS_VERSION=.*/LENS_VERSION=$VERSION/" "$TARGET_DIR/.env.example" > "$TARGET_DIR/.env"
fi

if [ ! -f "$TARGET_DIR/backend.env" ]; then
  cp "$TARGET_DIR/backend.env.example" "$TARGET_DIR/backend.env"
fi

mkdir -p "$TARGET_DIR/data/backend"

cat <<EOF
Lens deploy bundle installed in $TARGET_DIR

Next steps:
  cd $TARGET_DIR
  ./scripts/lens doctor
  ./scripts/lens up

Open:
  http://localhost:$(grep '^LENS_HTTP_PORT=' "$TARGET_DIR/.env" | cut -d= -f2-)
EOF
