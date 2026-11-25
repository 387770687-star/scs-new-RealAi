#!/bin/zsh
set -euo pipefail
repo_dir="${0:A:h}"
cd "$repo_dir"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "此启动器用于 macOS。Windows 请运行 Start-RealAi-Dev.bat。"
  exit 1
fi
for command_name in node npm uv; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    print -u2 "请先安装运行工具：brew install node uv"
    exit 1
  fi
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("请使用 Node.js 22 或更高版本。"); process.exit(1); }'
no_electron=false
setup_only=false
forward_args=()
for arg in "$@"; do
  case "$arg" in
    --no-electron) no_electron=true; forward_args+=("$arg") ;;
    --setup-only) setup_only=true ;;
    *) forward_args+=("$arg") ;;
  esac
done
print "战略规划域多源多模态知识大脑 · Mac 启动"
node scripts/ensure-config.js
if ! node -e 'require("./apps/web/node_modules/esbuild").transformSync("let ready = true"); require("./apps/web/node_modules/rollup");' >/dev/null 2>&1; then
  print "[setup] 安装当前 Mac 的 Web 依赖…"
  npm --prefix apps/web ci --ignore-scripts
  node apps/web/node_modules/esbuild/install.js
fi
if [[ "$no_electron" == false ]] && ! node -e 'const fs=require("fs"),path=require("path"); const p=require.resolve("electron",{paths:[path.resolve("apps/desktop")]}); process.exit(fs.existsSync(require(p)) ? 0 : 1)' >/dev/null 2>&1; then
  print "[setup] 安装 Electron 桌面端…"
  npm ci --ignore-scripts
  ELECTRON_MIRROR="${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}" node scripts/install-electron-mac.js
fi
backend_dir="$repo_dir/services/deerflow/backend"
if ! "$backend_dir/.venv/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12)' >/dev/null 2>&1; then
  if [[ -e "$backend_dir/.venv" ]]; then
    mv "$backend_dir/.venv" "$backend_dir/.venv.backup.$(date +%Y%m%d%H%M%S)"
  fi
  uv venv --python 3.12 "$backend_dir/.venv"
fi
print "[setup] 按 uv.lock 同步 Python 依赖…"
requirements_file="$(mktemp "${TMPDIR:-/tmp}/realai-requirements.XXXXXX")"
trap 'rm -f "$requirements_file"' EXIT
(
  cd "$backend_dir"
  uv export --frozen --no-dev --format requirements-txt --output-file "$requirements_file" --quiet
  UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-120}" uv pip install --no-deps \
    --python .venv/bin/python \
    --index-url "${REALAI_PYPI_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}" \
    -r "$requirements_file"
  uv pip check --python .venv/bin/python
)
export UV_NO_SYNC=1
export PYTHONPYCACHEPREFIX="${XDG_CACHE_HOME:-$HOME/.cache}/realai/pycache"
mkdir -p "$PYTHONPYCACHEPREFIX"
if [[ "$setup_only" == true ]]; then
  print "[setup] 安装完成。运行 ./Start-RealAi-Web.command 打开浏览器版。"
  exit 0
fi
node -e 'const p=require("./scripts/ports"); console.log(`工作台：${p.vueFrontendUrl()}/ · 后端：${p.gatewayUrl()}/`)'
node scripts/dev-all.js "${forward_args[@]}"
