import os
import textwrap
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from models_db import async_session
from services.repositories import get_survey_campaign, latest_survey_campaign, list_survey_artifacts, save_survey_artifact


POSTER_ROOT = Path(os.environ.get("SURVEY_POSTER_DIR", Path(__file__).resolve().parents[1] / "generated" / "survey-posters"))
POSTER_URL_PREFIX = os.environ.get("SURVEY_POSTER_URL_PREFIX", "http://localhost:8000/generated/survey-posters")


async def generate_survey_poster(task_id: str, channel: str = "xiaohongshu", campaign_id: str | None = None) -> dict[str, Any]:
    async with async_session() as session:
        campaign = await get_survey_campaign(session, campaign_id) if campaign_id else await latest_survey_campaign(session, task_id)
        if campaign and campaign.task_id != task_id:
            campaign = None
        if not campaign:
            raise KeyError("survey_campaign")
        artifacts = await list_survey_artifacts(session, campaign.id)
        posts = next((a.content_json for a in artifacts if a.type == "recruitment_post"), {})
        questionnaire = next((a.content_json for a in artifacts if a.type == "questionnaire"), {})

    post = posts.get(channel) if isinstance(posts, dict) else None
    if not isinstance(post, dict):
        post = posts.get("manual", {}) if isinstance(posts, dict) else {}

    title = str(post.get("title") or questionnaire.get("title") or "用户体验调研")
    survey_url = campaign.survey_url or "{survey_url}"
    content = str(post.get("content") or "欢迎参与调研：{survey_url}").replace("{survey_url}", survey_url)
    file_path, preview_url = render_poster(
        title=title,
        content=content,
        survey_url=survey_url,
        task_id=task_id,
        campaign_id=campaign.id,
    )

    artifact = {
        "channel": channel,
        "title": title,
        "content": content,
        "file_path": str(file_path),
        "preview_url": preview_url,
    }
    async with async_session() as session:
        await save_survey_artifact(session, campaign.id, artifact_type="poster", content_json=artifact, status="generated")
        await session.commit()
    return artifact


def render_poster(title: str, content: str, survey_url: str, task_id: str, campaign_id: str) -> tuple[Path, str]:
    POSTER_ROOT.mkdir(parents=True, exist_ok=True)
    width, height = 1242, 1660
    image = Image.new("RGB", (width, height), "#f7f3ee")
    draw = ImageDraw.Draw(image)
    title_font = load_font(74, bold=True)
    subtitle_font = load_font(38, bold=True)
    body_font = load_font(34)
    small_font = load_font(28)
    url_font = load_font(30, bold=True)

    draw.rectangle((0, 0, width, 260), fill="#263238")
    draw.rectangle((0, 260, width, 290), fill="#d0503f")
    draw.rounded_rectangle((86, 150, 1156, 1490), radius=36, fill="#ffffff")
    draw.rounded_rectangle((92, 156, 1150, 1484), radius=32, outline="#263238", width=3)

    draw.text((112, 82), "问卷招募", font=subtitle_font, fill="#f9f1e5")
    draw_wrapped(draw, title, (132, 220), title_font, fill="#263238", max_width=960, line_gap=14, max_lines=3)

    y = 520
    draw.text((132, y), "我们想听听你的真实体验", font=subtitle_font, fill="#d0503f")
    y += 72
    summary = content.replace("\n", " ").strip()
    draw_wrapped(draw, summary, (132, y), body_font, fill="#263238", max_width=950, line_gap=12, max_lines=8)

    y = 1060
    draw.rounded_rectangle((132, y, 1110, y + 220), radius=24, fill="#f7f3ee", outline="#e1d7cc", width=2)
    draw.text((168, y + 34), "问卷链接", font=subtitle_font, fill="#263238")
    draw_wrapped(draw, survey_url, (168, y + 100), url_font, fill="#d0503f", max_width=880, line_gap=8, max_lines=3)

    y = 1340
    draw.rounded_rectangle((132, y, 1110, y + 88), radius=44, fill="#263238")
    draw.text((364, y + 24), "3 分钟填写，感谢你的反馈", font=body_font, fill="#ffffff")
    draw.text((132, 1530), f"Campaign {campaign_id[:8]} · Task {task_id}", font=small_font, fill="#7b746d")

    filename = f"{task_id}-{uuid.uuid4().hex[:8]}.png"
    file_path = POSTER_ROOT / filename
    image.save(file_path, "PNG")
    return file_path, f"{POSTER_URL_PREFIX.rstrip('/')}/{filename}"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    fill: str,
    max_width: int,
    line_gap: int,
    max_lines: int,
) -> int:
    x, y = xy
    lines = wrap_text(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("。,.， ") + "..."
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += bbox[3] - bbox[1] + line_gap
    return y


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    lines: list[str] = []
    current = ""
    for char in normalized:
        candidate = f"{current}{char}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = char
    if current:
        lines.append(current)
    return lines or textwrap.wrap(normalized, width=24)
