# AI 批改本地验证

文件存储使用本地目录，模型使用已配置的 DeepSeek。关闭 OSS 不等于关闭模型网络请求。

仓库根目录 `.env` 与 `backend/.env` 均已设置以下本机配置（不要提交环境文件）：

```dotenv
STORAGE_BACKEND=local
STORAGE_LOCAL_ONLY=true
LOCAL_STORAGE_ROOT=E:/rjgc作业管理系统/data/files
```

`STORAGE_LOCAL_ONLY=true` 禁止创建 OSS 客户端；缺失本地文件不会回退读取 OSS。生产配置默认不启用此开关。

## 不使用历史学生文件的验证

在仓库根目录运行：

```powershell
backend/.venv/Scripts/python.exe scripts/verify-local-ai-grading.py
backend/.venv/Scripts/python.exe scripts/verify-local-ai-grading.py --live
```

第一条只验证本地样例文件读取；第二条将虚构样例及标准发送至已配置模型，不连接数据库、不访问 OSS、不发布成绩。

样例在 `data/files/ai-grading-local-sample/`，结果在 `data/ai-grading-local-result.json`，均被 Git 忽略。样例标准定义缺少一项为 B；提交包含登录与作业提交、缺少权限校验，预期建议 B 并解释缺失项。

页面流程验证：新建独立的本地测试作业，上传样例 `criteria.md` 并标记为“判定标准”，使用测试学生提交 `submission.md`，然后由教师打开该提交，确认能预览，再点击 AI批改。采用建议后由教师自行保存草稿或发布。

## 历史文件恢复

当前历史作业只有数据库文件记录，本地没有对应正式提交与标准正文。仅切换存储配置不会迁移旧文件。

必须使用原始文件备份，按数据库记录的 `storage_path` 放回 `LOCAL_STORAGE_ROOT` 下，保持原始目录和文件名。不要将可编辑草稿、样例或其他学生文件写到历史正式提交路径；没有原始备份时，历史提交不能在不访问原存储的情况下恢复。

恢复后依次确认正式提交预览、评分标准读取，再点击重试。无需为了验证而修改或发布历史成绩。

所有改动保留在工作区；本次未执行 Git 提交或推送。
