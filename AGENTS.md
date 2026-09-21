# Repository Guidelines

## 项目结构与模块组织

- `backend/app/`：FastAPI 应用（当前业务路由主要在 `main.py`）、SQLAlchemy 模型、配置与安全工具；`storage.py` 对接阿里云 OSS，`worker.py` 处理后台任务，`archive_exports.py` 生成异步 ZIP 导出。
- `backend/migrations/versions/`：按顺序保存 Alembic 数据库迁移；持久化模型变化时应同步新增迁移。
- `backend/tests/`：pytest 接口及业务流程测试。
- `frontend/src/`：Vue 3 页面（`views/shell/` 为主要业务页面）、组件、路由、Pinia 会话状态、API 客户端和全局样式。
- `frontend/tests/e2e/`：Playwright 端到端测试。
- `docs/`：架构、接口、部署和验收文档，部分早期方案仅供历史参考；`scripts/`：Windows 本地初始化、启动和停止脚本；根目录 `start-server.bat`：Windows 服务器托管前端构建产物的入口。

## 构建、测试与开发命令

除特别说明外，均在仓库根目录运行：

- `.\scripts\init-local.ps1`：初始化 SQL Server、Python 环境、依赖、数据库迁移及基础数据。
- `.\scripts\start-local.bat`：启动 API、后台任务和 Vite 开发服务器，访问 `http://localhost:8080`。
- `.\scripts\stop-local.ps1`：停止本地服务。
- `cd frontend; npm run dev`：仅启动前端开发服务器。
- `cd frontend; npm run build`：生成前端生产构建。
- `.\start-server.bat`：Windows 服务器启动 API 并托管 `frontend\dist`（需先构建前端）。
- `docker compose --profile test build`：构建隔离的测试镜像。
- `docker compose --profile test run --rm test-api pytest -q`：运行后端测试。

项目约定跳过所有 E2E 测试，不运行 Playwright 测试命令。


## 编码风格与命名规范

Python 使用 4 空格缩进并遵循现有 PEP 8 风格：函数采用 `snake_case`，模型采用 `PascalCase`，常量采用全大写。JavaScript 和 Vue 使用 2 空格缩进、单引号、不写分号；变量使用 `camelCase`，组件文件使用 `PascalCase`，例如 `ShellView.vue`。API 路由统一位于 `/api/v1` 下，并沿用现有结构化错误响应。目前未配置格式化或 lint 工具，提交前应对照相邻代码检查风格和导入顺序。

## 测试规范

后端测试命名为 `test_*.py`，Playwright 测试命名为 `*.spec.js`。接口变更应覆盖权限、参数校验、数据库副作用及状态码；用户流程或响应式界面变化可补充浏览器测试用例，但按项目约定不运行 E2E。需要数据库的后端测试必须使用 Compose 的独立测试环境，禁止连接开发数据库。目前没有强制覆盖率门槛，但所有行为变更都应有回归测试。

## 提交与拉取请求规范

近期提交信息以简短祈使句为主，并逐步采用 `feat:` 前缀。建议统一使用 Conventional Commits，如 `feat:`、`fix:`、`test:`、`docs:`，且每个提交只处理一个主题。拉取请求应说明行为及数据库结构变化、列出验证命令、关联相关 Issue；可见界面变更需附截图。新增环境变量、迁移或部署步骤必须明确标注。

## 安全与配置提示

不要提交凭据、上传文件或本地环境数据。修改接口时必须保留会话、CSRF、权限和文件访问校验。正式部署前务必修改文档中的默认教师密码。
