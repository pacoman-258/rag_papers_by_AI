#!/usr/bin/env python3
"""Render repository workflow diagrams as SVG and PNG assets.

The SVG is the editable source of truth. PNG export uses macOS built-in
renderers so the docs do not need a new Python or Node dependency.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import tempfile
from pathlib import Path


WIDTH = 1920
HEIGHT = 1080
OUT_DIR = Path(__file__).resolve().parent
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", '
    '"Noto Sans CJK SC", "Microsoft YaHei", Arial, sans-serif'
)


WORKFLOWS = [
    {
        "slug": "search-workflow",
        "title": "搜索工作流",
        "kicker": "Search Workflow",
        "subtitle": "从用户问题到可追溯回答：查询规划、多源召回、重排、回答与助手上下文同步。",
        "accent": "#2f8f83",
        "secondary": "#3f6fa8",
        "stages": [
            {
                "title": "用户问题",
                "body": ["自然语言问题", "可带过滤条件", "选择模型配置"],
                "artifact": "Request",
            },
            {
                "title": "查询规划",
                "body": ["query_chat 改写", "拆解检索意图", "用户可确认微调"],
                "artifact": "Plan",
            },
            {
                "title": "多源召回",
                "body": ["本地向量库", "arXiv / WoS", "元数据关键词"],
                "artifact": "Candidates",
            },
            {
                "title": "重排与证据",
                "body": ["embedding + rerank", "去重与排序", "论文卡片与片段"],
                "artifact": "Evidence",
            },
            {
                "title": "流式回答",
                "body": ["answer_chat 生成", "引用论文来源", "同步 Live2D 上下文"],
                "artifact": "Answer",
            },
        ],
        "left_panel": {
            "title": "关键产物",
            "items": ["候选论文列表、检索日志、重排分数", "回答上下文会被最近一次 QA 与助手层引用", "配置优先级：请求体 > runtime_settings > 环境变量"],
        },
        "right_panel": {
            "title": "可靠性边界",
            "items": ["外部源失败时保留本地检索链路", "回答必须绑定检索证据，不能凭空补论文", "API key 只写不回显，只返回 has_api_key 状态"],
        },
    },
    {
        "slug": "citation-trace-workflow",
        "title": "引用溯源工作流",
        "kicker": "Citation Trace Workflow",
        "subtitle": "从源论文参考文献出发召回全局 Top15，再由副模型评审、主模型综合生成最终 Top5。",
        "accent": "#c95c38",
        "secondary": "#7a5a91",
        "stages": [
            {
                "title": "载入来源",
                "body": ["arXiv 或 PDF", "PDF 文本抽取", "源论文元数据"],
                "artifact": "Target",
            },
            {
                "title": "解析参考文献",
                "body": ["References 切分", "arXiv ID / DOI", "title hint 清洗"],
                "artifact": "Refs",
            },
            {
                "title": "Top15 候选召回",
                "body": ["ID 直接取记录", "标题相似检索", "全局去重排序"],
                "artifact": "Top15",
            },
            {
                "title": "副模型评审",
                "body": ["15 篇全部分析", "方法与相关性", "风险与不确定性"],
                "artifact": "Reports",
            },
            {
                "title": "主模型排序",
                "body": ["综合 15 份报告", "输出最终 Top5", "失败回退规则 Top5"],
                "artifact": "Top5",
            },
        ],
        "left_panel": {
            "title": "证据账本",
            "items": ["每个候选保留来源 reference、召回分、匹配理由", "warnings 标明弱标题、年份异常、疑似误召回", "作者匹配只做极低附加分，不能单独构成证据"],
        },
        "right_panel": {
            "title": "执行边界",
            "items": ["默认只跑一轮 Top15，不自动 round two 扩展", "arXiv 限流或 SSL 问题使用重试与可读提示", "LLM 失败时明确标注 fallback，不伪装成模型判断"],
        },
    },
    {
        "slug": "paper-reader-workflow",
        "title": "精读工作流",
        "kicker": "Paper Reader Workflow",
        "subtitle": "以 PDF 原文页为中心，支持页面浏览、选区翻译、论文追问与助手上下文同步。",
        "accent": "#3f6fa8",
        "secondary": "#c8943f",
        "stages": [
            {
                "title": "载入论文",
                "body": ["arXiv 或本地 PDF", "PDF 校验与重试", "读取标题摘要"],
                "artifact": "Session",
            },
            {
                "title": "原文视图",
                "body": ["按物理页浏览", "页面文本缓存", "保留来源页码"],
                "artifact": "Pages",
            },
            {
                "title": "选区翻译",
                "body": ["选择原文片段", "paper_reader_translation", "页面内浮层展示"],
                "artifact": "Translation",
            },
            {
                "title": "论文追问",
                "body": ["检索相关页片段", "预算内压缩上下文", "paper_reader_chat 回答"],
                "artifact": "QA",
            },
            {
                "title": "助手同步",
                "body": ["整篇论文级上下文", "手动同步选区焦点", "最近对话一并打包"],
                "artifact": "Assistant",
            },
        ],
        "left_panel": {
            "title": "关键产物",
            "items": ["source pages、页缓存、论文级 assistant context", "选区翻译不会替代主精读问答", "刷新或重新载入后获取最新物理页 manifest"],
        },
        "right_panel": {
            "title": "可靠性边界",
            "items": ["PDF 下载失败时提示上传本地文件或稍后重试", "助手回答只能辅助解释，不能替代论文追问接口", "上下文预算由 paper_reader_chat / translation 配置控制"],
        },
    },
    {
        "slug": "research-profile-workflow",
        "title": "用户画像系统",
        "kicker": "Research Profile System",
        "subtitle": "从长期记忆中保守提炼研究偏好，用独立页面管理，并只作为助手层的轻量参考。",
        "accent": "#7a5a91",
        "secondary": "#2f8f83",
        "stages": [
            {
                "title": "互动信号",
                "body": ["搜索与精读问题", "助手对话摘要", "置顶 / 删除动作"],
                "artifact": "Signals",
            },
            {
                "title": "长期记忆",
                "body": ["assistant_memory", "摘要与标签", "向量召回索引"],
                "artifact": "Memory",
            },
            {
                "title": "画像抽取",
                "body": ["研究方向", "常用方法偏好", "置信度与证据"],
                "artifact": "Profile",
            },
            {
                "title": "独立页面",
                "body": ["刷新画像", "查看 / 置顶 / 删除", "未连库时降级"],
                "artifact": "Console",
            },
            {
                "title": "个性化参考",
                "body": ["助手回答轻量参考", "不覆盖论文证据", "保护主搜索链路"],
                "artifact": "Context",
            },
        ],
        "left_panel": {
            "title": "画像原则",
            "items": ["只做保守归纳：兴趣、方法、偏好约束", "画像条目需要可删除、可置顶、可刷新", "长期记忆不可用时前端给出降级提示"],
        },
        "right_panel": {
            "title": "安全边界",
            "items": ["不保存或回显 API key 与本地秘密", "助手不得编造论文、引用或工作流上下文", "画像只影响助手层，不改变主检索与溯源证据"],
        },
    },
]


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def text_block(
    x: int,
    y: int,
    lines: list[str],
    *,
    size: int = 34,
    weight: int = 500,
    color: str = "#2f2a23",
    line_height: int = 44,
    anchor: str = "start",
    opacity: float = 1,
) -> str:
    attrs = (
        f'x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}" opacity="{opacity}"'
    )
    body = []
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        body.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    return f'<text {attrs}>{''.join(body)}</text>'


def pill(x: int, y: int, text: str, fill: str, color: str, width: int) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="42" rx="21" fill="{fill}"/>'
        + text_block(x + width // 2, y + 29, [text], size=20, weight=700, color=color, anchor="middle")
    )


def arrow(x1: int, y: int, x2: int, color: str) -> str:
    head = f"{x2},{y} {x2 - 18},{y - 10} {x2 - 18},{y + 10}"
    return (
        f'<line x1="{x1}" y1="{y}" x2="{x2 - 18}" y2="{y}" stroke="{color}" '
        'stroke-width="5" stroke-linecap="round" opacity="0.82"/>'
        f'<polygon points="{head}" fill="{color}" opacity="0.82"/>'
    )


def stage_card(x: int, y: int, idx: int, stage: dict[str, object], accent: str, secondary: str) -> str:
    title = str(stage["title"])
    body = [str(item) for item in stage["body"]]
    artifact = str(stage["artifact"])
    card_w = 300
    card_h = 430
    lines = [
        f'<rect x="{x + 8}" y="{y + 12}" width="{card_w}" height="{card_h}" rx="26" fill="#000" opacity="0.055"/>',
        f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="26" fill="#fffdf7" stroke="#eadfcc" stroke-width="2"/>',
        f'<rect x="{x}" y="{y}" width="{card_w}" height="12" rx="6" fill="{accent}"/>',
        f'<circle cx="{x + 50}" cy="{y + 62}" r="28" fill="{accent}" opacity="0.95"/>',
        text_block(x + 50, y + 73, [str(idx)], size=30, weight=800, color="#fffdf7", anchor="middle"),
        text_block(x + 88, y + 55, [title], size=31, weight=800, color="#261f18", line_height=38),
        f'<line x1="{x + 30}" y1="{y + 112}" x2="{x + card_w - 30}" y2="{y + 112}" stroke="#eadfcc" stroke-width="2"/>',
    ]
    by = y + 168
    for line in body:
        lines.append(f'<circle cx="{x + 42}" cy="{by - 10}" r="5" fill="{secondary}" opacity="0.88"/>')
        lines.append(text_block(x + 62, by, [line], size=26, weight=500, color="#3f372d", line_height=34))
        by += 58
    lines.append(pill(x + 30, y + card_h - 68, artifact, "#f1e4d1", "#72523a", 240))
    return "\n".join(lines)


def bottom_panel(x: int, y: int, title: str, items: list[str], accent: str) -> str:
    lines = [
        f'<rect x="{x + 8}" y="{y + 10}" width="830" height="240" rx="24" fill="#000" opacity="0.045"/>',
        f'<rect x="{x}" y="{y}" width="830" height="240" rx="24" fill="#fffaf1" stroke="#e8dcc7" stroke-width="2"/>',
        f'<rect x="{x}" y="{y}" width="8" height="240" rx="4" fill="{accent}"/>',
        text_block(x + 40, y + 54, [title], size=31, weight=800, color="#261f18"),
    ]
    by = y + 102
    for item in items:
        lines.append(f'<circle cx="{x + 46}" cy="{by - 10}" r="5" fill="{accent}" opacity="0.86"/>')
        lines.append(text_block(x + 66, by, [item], size=25, weight=500, color="#453d34", line_height=33))
        by += 46
    return "\n".join(lines)


def render_svg(workflow: dict[str, object]) -> str:
    accent = str(workflow["accent"])
    secondary = str(workflow["secondary"])
    stage_xs = [80, 430, 780, 1130, 1480]
    stage_y = 244
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        "<defs>",
        '<linearGradient id="paper-bg" x1="0" x2="1" y1="0" y2="1">',
        '<stop offset="0%" stop-color="#fff8ec"/>',
        '<stop offset="55%" stop-color="#f8efe2"/>',
        '<stop offset="100%" stop-color="#f2e6d6"/>',
        "</linearGradient>",
        "</defs>",
        '<rect width="1920" height="1080" fill="url(#paper-bg)"/>',
        '<circle cx="1710" cy="150" r="210" fill="#ffffff" opacity="0.34"/>',
        '<circle cx="118" cy="942" r="170" fill="#ffffff" opacity="0.26"/>',
        pill(82, 72, "ARXIV-PAPER-RAG", "#261f18", "#fffaf1", 214),
        pill(314, 72, str(workflow["kicker"]), "#eadfcc", "#5d4a38", 290),
        text_block(82, 168, [str(workflow["title"])], size=72, weight=850, color="#221b14", line_height=80),
        text_block(84, 220, [str(workflow["subtitle"])], size=28, weight=500, color="#665a4c", line_height=34),
    ]
    stages = list(workflow["stages"])
    for idx, stage in enumerate(stages, start=1):
        parts.append(stage_card(stage_xs[idx - 1], stage_y, idx, stage, accent, secondary))
        if idx < len(stages):
            parts.append(arrow(stage_xs[idx - 1] + 314, stage_y + 104, stage_xs[idx], secondary if idx % 2 == 0 else accent))
    parts.append(bottom_panel(80, 750, str(workflow["left_panel"]["title"]), list(workflow["left_panel"]["items"]), accent))
    parts.append(bottom_panel(1010, 750, str(workflow["right_panel"]["title"]), list(workflow["right_panel"]["items"]), secondary))
    parts.append(text_block(1780, 1026, ["docs/workflows"], size=22, weight=600, color="#7f705f", anchor="end"))
    parts.append("</svg>")
    return "\n".join(parts)


def export_png(svg_path: Path, png_path: Path) -> bool:
    sips = shutil.which("sips")
    if sips:
        try:
            result = subprocess.run(
                [sips, "-s", "format", "png", str(svg_path), "--out", str(png_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            result = None
        if result and result.returncode == 0 and png_path.exists() and png_path.stat().st_size > 0:
            return True

    qlmanage = shutil.which("qlmanage")
    if qlmanage:
        with tempfile.TemporaryDirectory(dir=OUT_DIR) as tmp:
            tmp_dir = Path(tmp)
            try:
                result = subprocess.run(
                    [qlmanage, "-t", "-s", str(WIDTH), "-o", str(tmp_dir), str(svg_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=20,
                )
            except subprocess.TimeoutExpired:
                result = None
            if result and result.returncode == 0:
                candidates = list(tmp_dir.glob("*.png"))
                if candidates:
                    shutil.copyfile(candidates[0], png_path)
                    return png_path.exists() and png_path.stat().st_size > 0

    chrome_candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    chrome = next((path for path in chrome_candidates if path.exists()), None)
    if chrome:
        with tempfile.TemporaryDirectory(dir=OUT_DIR) as profile:
            command = [
                str(chrome),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--disable-extensions",
                "--metrics-recording-only",
                f"--user-data-dir={profile}",
                f"--window-size={WIDTH},{HEIGHT}",
                f"--screenshot={png_path}",
                svg_path.as_uri(),
            ]
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=18,
                )
            except subprocess.TimeoutExpired:
                return png_path.exists() and png_path.stat().st_size > 0
            if result.returncode == 0 and png_path.exists() and png_path.stat().st_size > 0:
                return True
    return False


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for workflow in WORKFLOWS:
        slug = str(workflow["slug"])
        svg_path = OUT_DIR / f"{slug}.svg"
        png_path = OUT_DIR / f"{slug}.png"
        svg_path.write_text(render_svg(workflow), encoding="utf-8")
        if not export_png(svg_path, png_path):
            failures.append(slug)
        else:
            print(f"rendered {png_path.relative_to(OUT_DIR.parent.parent)}")
    if failures:
        joined = ", ".join(failures)
        raise SystemExit(f"PNG export failed for: {joined}. SVG sources were still written.")


if __name__ == "__main__":
    main()
