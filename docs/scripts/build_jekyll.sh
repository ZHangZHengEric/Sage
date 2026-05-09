#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -x /opt/homebrew/opt/ruby@3.2/bin/ruby ]; then
  export PATH="/opt/homebrew/opt/ruby@3.2/bin:$PATH"
fi

bundle exec jekyll build "$@"
