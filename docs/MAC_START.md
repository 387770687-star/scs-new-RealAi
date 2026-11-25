# Mac 本地运行

此仓库包含 Vue 主界面、Electron 桌面壳、DeerFlow / RealAi 后端、业务 Skill、示例资料和依赖锁文件。浏览器版与桌面版使用同一套功能和本地数据。

## 1. 获取仓库

仓库地址：https://github.com/387770687-star/scs-new-RealAi

仓库公开，直接打开链接即可浏览和下载。点击 [下载源码 ZIP](https://github.com/387770687-star/scs-new-RealAi/archive/refs/heads/main.zip)，或在仓库页面选择 **Code → Download ZIP**。

建议把代码放在 `~/Developer`，让源码、Python 环境和 SQLite 数据库始终保留在本地磁盘。桌面和文稿目录可能由 iCloud 自动转为云端占位文件，进程读文件时会等待下载。

已安装 Homebrew 的 Mac：

```bash
brew install node uv
# Node.js 22 或更高版本；Python 3.12 由 uv 自动准备。
mkdir -p ~/Developer
cd ~/Developer
git clone https://github.com/387770687-star/scs-new-RealAi.git
cd scs-new-RealAi
```

通过 ZIP 获取代码时，把解压出的 `scs-new-RealAi-main` 文件夹放到 `~/Developer`，安装 `node` 和 `uv` 后，在终端进入该文件夹，继续以下启动步骤。Homebrew 安装入口为 https://brew.sh/ 。

## 2. 启动浏览器版

```bash
./Start-RealAi-Web.command
```

启动器会创建本地配置、安装当前 CPU 架构所需的 Web / Python 依赖，再启动两个服务。看到“后端就绪”和“Vue 前端就绪”后，在 Chrome 打开：

- 工作台：http://127.0.0.1:8402/#/workbench
- 知识图谱：http://127.0.0.1:8402/#/knowledge/graph
- 设置：http://127.0.0.1:8402/#/system

终端保持运行。按 `Ctrl+C` 停止本次启动的服务。

## 3. 启动桌面版

```bash
./Start-RealAi-Dev.command
```

首次会额外安装 Electron，随后显示桌面窗口。Apple Silicon 与 Intel Mac 都由安装工具按本机架构下载依赖；本次交付的实机验证使用 Apple Silicon Mac。

仅安装依赖：

```bash
./Start-RealAi-Web.command --setup-only
# 包含 Electron 的安装：
./Start-RealAi-Dev.command --setup-only
```

## 4. 配置模型与知识库

1. 在“模型”或“设置”中填写自己的服务地址、API Key 和服务商实际提供的模型 ID，保存配置。
2. 在“设置”的首次向导中导入附带的管道工程示例，或在“知识库”上传自己的文档、Excel 和图片。
3. 导入示例后，在“知识图谱”点击“重建 Wiki”，查看示例笔记间的双向链接；工作台可继续提问或进入战略规划生成。

界面与本地资料管理可以先启动。问答、写作和联网能力使用各自所需的模型与服务凭据。此仓库提供空密钥模板；当前电脑已有的业务资料、历史会话与报告继续保留在原电脑。如需迁移原有知识库，请由资料所有者另行交付授权的数据目录，再在设置中选择对应 Vault。

## 5. 运行文件与端口

| 内容 | 位置 |
| --- | --- |
| 端口配置 | `config/ports.json` |
| 模型及个人设置 | `config/settings.json`，首次启动生成 |
| 模型环境变量 | `services/deerflow/.env`，首次启动生成 |
| Agent 配置 | `services/deerflow/config.yaml`，首次启动生成 |
| 本地资料、Wiki、报告 | `vault/` 或设置中指定的 Vault |
| 业务会话数据库 | `config/realai_meta.sqlite` |
| 后端虚拟环境 | `services/deerflow/backend/.venv/` |

默认 Gateway 8401、Vue 8402；封存的 DeerFlow React 界面完整保留在源码中，按原项目手册单独启动。

## 6. 安装排查

- **模型调用失败**：检查服务商的余额、Key、Base URL、模型 ID 与网络，页面会显示实际错误。
- **端口占用**：在 `config/ports.json` 修改 `gateway` 与 `vueFrontend`，再启动；同一套正在运行的服务会被复用。
- **Python 下载较慢**：默认使用清华 PyPI 镜像安装 `uv.lock` 中的精确版本；可切换源：

  ```bash
  REALAI_PYPI_INDEX_URL=https://pypi.org/simple ./Start-RealAi-Web.command
  ```

- **Electron 下载较慢**：默认使用 npm 镜像，可通过 `ELECTRON_MIRROR` 指定下载源。启动器校验官方包的校验和，再调用 macOS 自带的解压工具安装。
- **启动命令的权限提示**：在终端执行 `zsh Start-RealAi-Web.command`；Git 克隆会保留 `.command` 的执行权限。
- **Office 原版式预览**：按场景安装 LibreOffice；应用的文档解析、表格读取和原件下载各有独立处理路径。

## 7. 本地验证

```bash
node --test tests/setup.test.js
npm --prefix apps/web run build
curl -fsS http://127.0.0.1:8401/api/realai/health
curl -fsS 'http://127.0.0.1:8402/api/realai/vault/graph?limit=180'
```
