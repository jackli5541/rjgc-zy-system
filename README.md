# 软件工程作业系统

面向高校软件工程课程的作业与教学协作平台，覆盖教师建班、学生组队、选题审核、作业发布与提交、教师评分、组内互评、成绩发布、通知及统计导出等完整教学流程。

项目按照教师端和学生端划分权限。教师可管理教学班、名单、小组、作业、互评活动与成绩；学生可完成组队、选题、作业提交、互评和成绩查询。系统使用服务端会话认证，文件下载与预览均经过权限校验，并为关键写操作保留审计记录。

## 核心功能

- 教学班管理：创建课程，导入 XLSX/CSV 学生名单，维护成员与重置密码
- 小组与选题：建组、申请、邀请、审批、组长移交、退出/解散，以及选题查重和教师审核
- 作业与提交：作业草稿和发布、附件管理、小组/个人作业提交、版本保留与截止前更新
- 评分与互评：当前个人作业支持组内成员对最新提交进行 A-E 评级，教师评级优先；历史一对一百分制互评、成绩发布和版本记录仍保留
- 教学辅助：站内通知、提交看板、批量下载、XLSX/CSV 导出和审计日志
- 文件处理：默认单文件上限 500 MiB；PDF、图片和 Markdown 安全预览；DOCX、PPTX、XLSX 与 ZIP/RAR/7Z 仅通过鉴权接口下载原文件；文件存储使用私有 OSS

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Ant Design Vue、Vue Router、Pinia |
| 后端 | FastAPI、SQLAlchemy、Alembic、Pydantic |
| 数据库 | SQL Server 2014+（开发与测试使用 SQL Server 2022 兼容级别 120） |
| 测试 | Pytest、Playwright |
| 部署 | Docker Compose；生产环境使用 FastAPI、Uvicorn 与 systemd 直接部署 |

## 快速启动

### 环境要求

- Windows 10/11 与 PowerShell 5.1+
- Docker Desktop（需支持 `docker compose`）
- Python 3.13
- Node.js 22 与 npm
- Microsoft ODBC Driver 18 for SQL Server（仅本机运行后端时需要）
- 私有阿里云 OSS Bucket 和具有所需读写权限的凭据；本机运行在 `backend/.env` 中配置 `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET` 等变量，全容器运行通过 Compose 环境变量传入（参考 `backend/.env.example`）

### 方式一：本地开发（推荐）

该模式仅在 Docker 中运行 SQL Server 2022，后端 API、任务进程和前端开发服务器运行在本机，文件存储使用 OSS，支持前端热更新。

```powershell
git clone https://github.com/jackli5541/rjgc-zy-system.git
cd rjgc-zy-system
.\scripts\init-local.ps1
.\scripts\start-local.bat
```

初始化仍使用 PowerShell 脚本；日常启动使用 `start-local.bat` 入口。启动脚本会先自动应用所有待执行的数据库迁移，迁移失败时不会启动服务。开发环境中的 API 和后台任务进程会监听 `backend/app` 下的 Python 文件并自动重启。启动窗口会保持打开，关闭该 CMD 窗口即可停止本地前后端进程。

首次执行 `init-local.ps1` 会启动 SQL Server、创建兼容级别为 120 的数据库、创建 Python 虚拟环境、安装前后端依赖、执行数据库迁移并初始化系统。启动完成后访问：

- Web 页面：<http://localhost:8080>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health/ready>

SQL Server 会继续在后台运行；开发数据库默认映射到本机 `1433` 端口，数据保存在 Docker 卷中。

### 方式二：全容器启动

无需在本机安装 Python 和 Node.js，适合快速体验或排查容器部署问题：

```powershell
docker compose --profile container-app up --build -d
```

容器就绪后访问 <http://localhost:8080>。查看状态和日志：

```powershell
docker compose --profile container-app ps
docker compose --profile container-app logs -f
```

停止服务（保留数据库卷；上传文件存储在 OSS）：

```powershell
docker compose --profile container-app down
```

> `docker compose down -v` 会删除数据库卷；不会删除 OSS 中的文件，仅应在明确需要清空本地数据库时使用。

## 默认账号

系统首次启动只创建一个教师账号，不包含示例课程和学生数据。

| 身份 | 账号 | 密码 |
| --- | --- | --- |
| 教师 | `teacher` | `123456` |

教师创建教学班并确认导入学生名单后，系统会按学号创建学生账号，初始密码与学号相同。正式部署前请修改默认密码。

## 自动化测试

测试使用独立的 SQL Server 容器；文件读写使用测试配置的 OSS 前缀，需与开发和生产前缀隔离。项目约定跳过 E2E，数据库回归只运行后端测试：

```powershell
docker compose --profile test build
docker compose --profile test run --rm test-api pytest -q
```

## 项目结构

```text
.
|-- backend/                 # FastAPI 应用、数据库迁移和后端测试
|-- frontend/                # Vue 3 前端与 Playwright 测试
|-- docs/                    # 架构、实现覆盖和部署文档
|-- scripts/                 # Windows 本地初始化、启动和停止脚本
|-- start-server.bat         # Windows 服务器入口
|-- docker-compose.yml       # 开发数据库、全容器运行和测试编排
`-- PRD-软件工程作业系统.md   # 产品需求文档
```

生产服务器的 Python、SQL Server 与 systemd 直接部署流程见 [服务器直接部署说明](docs/服务器直接部署说明.md)，系统架构见 [系统架构设计](docs/系统架构设计.md)。

Windows 服务器可在构建前端后运行 `.\start-server.bat`。脚本默认托管 `frontend\dist`，也可将独立部署的 dist 目录作为第一个参数，例如 `.\start-server.bat D:\coursework\dist`。
