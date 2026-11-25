@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title RealAi 本地开发

echo.
echo  RealAi 一键启动（后端 + Vue 前端 + 桌面窗口）
echo  主界面为 Vue；DeerFlow React 已封存（加 --deerflow 可后台启动）
echo  日志均在本窗口；关闭 Electron 或按 Ctrl+C 结束全部服务
echo.

if not exist "apps\web\node_modules" (
  echo [dev] 安装 Vue 前端依赖 npm run web:install ...
  call npm run web:install
)

where node >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js，请先安装 Node 18+
  pause
  exit /b 1
)

where pnpm >nul 2>&1
if errorlevel 1 (
  echo [提示] 未找到 pnpm，尝试 npm install -g pnpm ...
  call npm install -g pnpm
)

if not exist "apps\desktop\node_modules" (
  echo [dev] 安装桌面壳依赖 npm install ...
  call npm install
)

node scripts\dev-all.js %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [dev] 启动失败，退出码 %EXIT_CODE%
  pause
  exit /b %EXIT_CODE%
)

endlocal
