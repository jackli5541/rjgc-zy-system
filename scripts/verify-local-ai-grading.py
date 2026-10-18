"""Verify local files + DeepSeek without a database, OSS, or student records."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.ai_grading.service import generate_result, grading_messages, read_text_attachment
from app.settings import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send the synthetic sample to the configured model")
    args = parser.parse_args()
    if settings.storage_backend != "local" or not settings.storage_local_only:
        raise SystemExit("Set STORAGE_BACKEND=local and STORAGE_LOCAL_ONLY=true first")
    sample_root = settings.local_storage_root / "ai-grading-local-sample"
    sample_root.mkdir(parents=True, exist_ok=True)
    samples = {
        "criteria.md": "# 教师评分标准\n完整描述登录、作业提交、权限校验三项功能为 A；缺少一项为 B；只完成一项为 C；存在重大错误为 D；无有效内容为 E。请给出缺失项与定级理由。",
        "submission.md": "# 本地虚构验证作业\n## 登录\n用户使用账号密码登录，系统建立会话。\n## 作业提交\n学生在截止时间前提交作业并获得提交版本编号。\n",
    }
    texts = {}
    for name, content in samples.items():
        path = sample_root / name
        path.write_text(content, encoding="utf-8")
        file = SimpleNamespace(original_name=name, size_bytes=path.stat().st_size, storage_path=path.relative_to(settings.local_storage_root).as_posix())
        texts[name] = read_text_attachment(file, "本地验证材料")
    print("Local file checks passed. OSS disabled. No database or student records used.")
    if not args.live:
        return
    rubric = {"criteria_files": [{"name": "criteria.md", "content": texts["criteria.md"]}]}
    messages = grading_messages(SimpleNamespace(title="本地虚构批改验证", description="按教师标准评价需求完整性"), rubric, texts["submission.md"])
    result = asyncio.run(generate_result(messages, 180))
    output = ROOT / "data" / "ai-grading-local-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"grade": result["suggested_grade"], "grade_reason": result["grade_reason"], "output": str(output)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
