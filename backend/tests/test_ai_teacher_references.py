from textwrap import dedent

from app.modules.ai_teacher.retrieval import normalize_reference_text


def test_markdown_reference_normalization_matches_editor_text():
    source = dedent("""\
    # 需求

    参与者：**学生**  与系统交互。

    | 角色 | 目标 |
    | --- | --- |
    | 学生 | 提交作业 |

    ```mermaid
    flowchart LR
    A-->B
    ```
    """)
    normalized = normalize_reference_text(source, markdown_source=True)
    assert "需求" in normalized
    assert "参与者： 学生 与系统交互。" in normalized
    assert "学生 | 提交作业" not in normalized
    assert "flowchart LR" in normalized


def test_plain_reference_normalization_collapses_whitespace():
    assert normalize_reference_text("  参与者：\n\t学生　与系统交互。 ") == "参与者： 学生 与系统交互。"
