# AI 教师与 AI 批改共用接口配置

两个模块统一读取公共 `AI_*` 的提供方、模型服务地址、Key、模型和请求超时。业务 API 不变，模块启用开关和输出上限保持独立。本文件保留原路径，替代此前的独立配置说明。

## 环境配置

以下示例放入部署环境的 `.env`，将 Key 替换为真实值，真实凭据不得提交 Git。完整示例见 `backend/.env.example`。

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=
AI_CHAT_MODEL=deepseek-chat
AI_REQUEST_TIMEOUT_SECONDS=60

AI_TEACHER_ENABLED=true
AI_GRADING_ENABLED=true
AI_TEACHER_MAX_OUTPUT_TOKENS=1600
AI_GRADING_MAX_OUTPUT_TOKENS=8192
```

未配置开关时，代码默认两个模块都关闭；上述示例在配置好模型服务后启用两模块。关闭教师不影响批改，关闭批改不影响教师。禁用批改时，新建和重试在入队前返回 503，Worker 不领取 AI 批改任务，其他后台任务照常执行；历史结果仍可查看。

教师保留流式回答方式。批改通过同一个服务和模型生成建议，保持温度 0、JSON 输出；直接调用 DeepSeek 时继续禁用深度思考，并保留原有任务时限。所选模型服务需支持批改使用的 JSON 输出参数。数据库和 OSS 配置不变，OSS 凭据不替代模型 Key。

## 从旧配置迁移

旧 `AI_TEACHER_*`、`AI_GRADING_*` 的 `PROVIDER`、`BASE_URL`、`API_KEY`、`CHAT_MODEL`、`REQUEST_TIMEOUT_SECONDS` 已移除，不再覆盖公共配置，即使仍写在环境文件里也不会生效。选择客户要共用的一套服务，把这些值迁移为公共 `AI_*`；保留两个 `*_ENABLED` 和各自的 `*_MAX_OUTPUT_TOKENS`，教师历史、上下文、引用等其他配置继续有效。

配置会读取仓库根目录和 `backend` 下的 `.env`，同名值以 `backend/.env` 为准，进程环境变量优先。检查所有来源是否有旧的公共值覆盖新配置。不要直接覆盖生产环境整份 `.env`，以免丢失数据库、存储或其他凭据。

统一升级并重启所有 API 与 Worker，使两者使用相同的公共配置。仅保存 `.env` 不会更新已运行进程；仍运行旧代码的 Worker 必须一起升级或停止。共享数据库的其他 Worker 也要统一管理。本次无需数据库迁移。

## 批改面板和前端部署

当前批阅栏顺序为：教师批注、学生互评及其批注、AI 批改、保存/发布操作。AI 面板保持一份，支持等待、生成、失败、建议展示及采用建议。教师模式可编辑时展示；学生互评关闭或没有互评内容时，也不会把面板挪到反馈标题下方。

客户此前实际加载的旧脚本 `AssignmentReviewDrawer-BAGLJMOZ.js` 将面板放在反馈标题下，更新后端无法改变浏览器中的旧界面。

1. 在 `frontend` 执行 `npm run build`。
2. 将整个 `frontend/dist`（含 `index.html` 与 `assets`）部署至实际 `FRONTEND_DIST` 目录；若设置了 `VITE_CDN_BASE`，同步更新对应 CDN 资源。
3. 刷新页面，在 Network 中核对新的入口和批阅 JS 文件名，并确认 AI 批改位于学生批注下方。启动脚本不会自动重建前端。

本次构建同时保留 AI 教师 UUID 匹配修复，兼容 HTTP 环境和旧会话。`AI_TEACHER_ENABLED` 应保持 `true` 才能发送新问题。

## 首次公共配置交付验证（2026-10-19）

以下为公共配置调整时的验证记录；后续重新生成修复、本地服务停止和 OSS 关闭状态见 `AI批改重新生成修复说明.md`。

- 配置、模拟模型调用、批改业务与调度单元测试合计 25 项通过。运行时为 SQLAlchemy 安装了禁止真实连接的拦截器，测试文件在临时目录执行，未加载会重置数据库的集成测试 fixture。没有连接开发数据库或调用真实模型。
- 前端批改展示顺序、任务状态、采用建议、动画和教师 UUID 匹配相关测试合计 29 项通过；生产构建和差异检查通过。未运行 E2E。
- 当前机器没有 Docker，未执行 Compose 隔离数据库的接口集成测试。
- 本次 `frontend/dist/index.html` 引用 `index-D2hkAfux.js`，批阅脚本为 `AssignmentReviewDrawer-BfLgNI1S.js`。后续重新构建时哈希可能变化，以同一次构建的文件为准，不能混用新旧文件。
- 真实 `.env` 和客户服务器均未修改。部署前务必按上文迁移公共配置，否则旧模块专用地址和 Key 将不再生效。
