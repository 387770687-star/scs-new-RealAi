"""On-demand vision: MiniMax multimodal read + wiki/viz cache."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from realai.evidence.types import EvidenceItem, EvidencePack, make_kb_id
from realai.vault.service import SKIP_DIRS, ensure_vault

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VisionMode = Literal["off", "auto", "force"]

_INTENT_RE = re.compile(
    r"图|表|截图|示意图|看图|识图|读数|图表|照片|图片|图示|曲线|柱状|饼图"
)
_NUMBER_ASK_RE = re.compile(r"数字|数值|多少|读数|占比|比例|增长率|产量|成本|长度|压力|管径")

_ANALYZE_PROMPT = (
    "请分析下列图片，用中文按结构输出：\n"
    "1. 图类型（示意图/柱状图/折线图/表格截图/照片/其他）\n"
    "2. 标题与图例（没有则写无）\n"
    "3. 关键结论（2～5 句）\n"
    "4. 可读数字列表（每行：指标名=数值+单位；看不清写「看不清」）\n"
    "5. 不确定处\n"
    "用户问题（供聚焦）：{query}"
)


def wants_vision_intent(query: str) -> bool:
    return bool(_INTENT_RE.search(query or ""))


def wants_number_from_image(query: str) -> bool:
    return bool(_NUMBER_ASK_RE.search(query or ""))


def find_image_candidates(
    query: str,
    *,
    limit: int = 2,
    extra_paths: list[str] | None = None,
) -> list[Path]:
    root = ensure_vault()
    found: list[Path] = []
    seen: set[str] = set()

    for rel in extra_paths or []:
        rel_n = (rel or "").replace("\\", "/").lstrip("/")
        if not rel_n:
            continue
        p = (root / rel_n).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            continue
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            key = str(p)
            if key not in seen:
                seen.add(key)
                found.append(p)

    tokens = [t for t in (query or "").replace("，", " ").replace(",", " ").split() if len(t) >= 2][
        :8
    ]
    # Also split CJK-ish continuous query into filename substrings of length>=2
    q = (query or "").strip()
    if q and len(q) >= 2 and not tokens:
        tokens = [q[:40]]

    scored: list[tuple[int, Path]] = []
    if tokens:
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            name = p.stem.lower()
            score = sum(1 for t in tokens if t.lower() in name or t in p.stem)
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, p in scored:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            found.append(p)
            if len(found) >= limit:
                break

    return found[:limit]


def viz_cache_path_for_image(image_rel: str) -> Path:
    """wiki/viz/<image_rel>.md next to mirrored path."""
    root = ensure_vault()
    rel = image_rel.replace("\\", "/").lstrip("/")
    # Avoid nested .png.md weirdness: replace suffix with .md under wiki/viz/
    stem = Path(rel)
    cache_rel = Path("wiki") / "viz" / stem.with_suffix(".md")
    return root / cache_rel


def load_viz_cache(image_rel: str) -> dict[str, Any] | None:
    path = viz_cache_path_for_image(image_rel)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = parts[1]
            body = parts[2].lstrip("\n")
            for line in fm.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"').strip("'")
    return {"path": path.as_posix(), "body": body.strip(), "meta": meta, "text": text}


def write_viz_cache(
    image_rel: str,
    analysis: str,
    *,
    model: str = "",
    numbers: list[str] | None = None,
) -> Path:
    root = ensure_vault()
    abs_img = (root / image_rel.replace("\\", "/").lstrip("/")).resolve()
    mtime = ""
    if abs_img.is_file():
        mtime = datetime.fromtimestamp(abs_img.stat().st_mtime, tz=timezone.utc).isoformat()
    cache = viz_cache_path_for_image(image_rel)
    cache.parent.mkdir(parents=True, exist_ok=True)
    nums = numbers or _extract_number_lines(analysis)
    fm = (
        "---\n"
        f'source: "{image_rel.replace(chr(34), "")}"\n'
        f"mtime: \"{mtime}\"\n"
        f'model: "{(model or "").replace(chr(34), "")}"\n'
        f"generated: \"{datetime.now(timezone.utc).isoformat()}\"\n"
        f'kind: "viz"\n'
        "---\n\n"
    )
    title = Path(image_rel).stem
    body = f"# 图片要点：{title}\n\n{analysis.strip()}\n"
    if nums:
        body += "\n## 可读数字\n\n" + "\n".join(f"- {n}" for n in nums) + "\n"
    cache.write_text(fm + body, encoding="utf-8")
    return cache


def _extract_number_lines(text: str) -> list[str]:
    lines: list[str] = []
    in_section = False
    for line in (text or "").splitlines():
        s = line.strip()
        if re.match(r"^4[\.、．)]\s*可读数字", s) or "可读数字" in s and len(s) < 20:
            in_section = True
            continue
        if in_section and re.match(r"^5[\.、．)]", s):
            break
        if in_section and s:
            cleaned = re.sub(r"^[-*•\d\.、．)\s]+", "", s).strip()
            if cleaned:
                lines.append(cleaned[:200])
        elif not in_section and ("=" in s or re.search(r"\d", s)) and len(s) < 120:
            # soft collect labeled numbers outside section
            if re.search(r"\d", s) and any(x in s for x in ("=", "：", ":")):
                lines.append(s[:200])
    # dedupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for n in lines:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:30]


def _rel_of(path: Path) -> str:
    root = ensure_vault()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


async def analyze_single_image(
    path: Path,
    *,
    query: str = "",
    write_cache: bool = True,
) -> EvidenceItem:
    from realai.llm.client import chat_vision

    rel = _rel_of(path)
    prompt = _ANALYZE_PROMPT.format(query=(query or "概括图意并列出可读数字").strip())
    turn = await chat_vision(prompt, [path], role="vision", purpose="vision")
    analysis = (turn.content or "").strip() or "（模型未返回图意）"
    numbers = _extract_number_lines(analysis)
    if write_cache:
        try:
            write_viz_cache(rel, analysis, model=turn.model or "", numbers=numbers)
        except Exception:
            logger.warning("write viz cache failed for %s", rel, exc_info=True)
    return EvidenceItem(
        id=f"viz:{rel}#region:0",
        type="viz",
        source=rel,
        excerpt=analysis[:2000],
        meta={
            "path": rel,
            "model": turn.model,
            "numbers": numbers,
            "from_cache": False,
        },
    )


def evidence_from_cache(image_rel: str, *, as_viz: bool = True) -> EvidenceItem | None:
    cached = load_viz_cache(image_rel)
    if not cached:
        return None
    body = cached.get("body") or ""
    if not body.strip():
        return None
    numbers = _extract_number_lines(body)
    if as_viz:
        return EvidenceItem(
            id=f"viz:{image_rel}#region:0",
            type="viz",
            source=image_rel,
            excerpt=body[:2000],
            meta={
                "path": image_rel,
                "model": (cached.get("meta") or {}).get("model") or "",
                "numbers": numbers,
                "from_cache": True,
            },
        )
    # off mode: expose as kb only (no viz API)
    return EvidenceItem(
        id=make_kb_id(f"wiki/viz/{image_rel}", body[:200]),
        type="kb",
        source=f"wiki/viz/{Path(image_rel).with_suffix('.md').as_posix()}",
        excerpt=body[:2000],
        meta={
            "path": f"wiki/viz/{Path(image_rel).with_suffix('.md').as_posix()}",
            "from_viz_cache": True,
            "image": image_rel,
            "numbers": numbers,
        },
    )


async def analyze_images_on_demand(
    query: str,
    *,
    mode: VisionMode | str = "auto",
    enabled: bool | None = None,
    image_paths: list[str] | None = None,
    limit: int = 2,
) -> tuple[EvidencePack, list[str]]:
    """Return (evidence, trajectory lines). Respects off|auto|force."""
    from realai.config import normalize_vision_mode

    trajectory: list[str] = []
    vmode = normalize_vision_mode(str(mode) if mode is not None else None, enabled=enabled)

    uploads = [p for p in (image_paths or []) if p]
    candidates = find_image_candidates(query, limit=limit, extra_paths=uploads)

    if vmode == "off":
        trajectory.append("视觉：关闭")
        items: list[EvidenceItem] = []
        for p in candidates[:limit]:
            rel = _rel_of(p)
            ev = evidence_from_cache(rel, as_viz=False)
            if ev:
                items.append(ev)
        if items:
            trajectory.append(f"视觉：未调 API，使用导入缓存 {len(items)} 条（kb）")
        return EvidencePack(items=items), trajectory

    need_auto = (
        bool(uploads)
        or wants_vision_intent(query)
        or bool(candidates)
    )
    if vmode == "auto" and not need_auto:
        trajectory.append("视觉：智能跳过")
        return EvidencePack(), trajectory

    if not candidates:
        trajectory.append("视觉：无候选图片")
        return EvidencePack(), trajectory

    items_out: list[EvidenceItem] = []
    api_count = 0
    cache_count = 0
    need_numbers = wants_number_from_image(query) or bool(uploads) or vmode == "force"

    for path in candidates[:limit]:
        rel = _rel_of(path)
        use_cache = vmode == "auto" and not need_numbers and not (
            uploads and rel.replace("\\", "/") in {u.replace("\\", "/").lstrip("/") for u in uploads}
        )
        if use_cache:
            cached = evidence_from_cache(rel, as_viz=True)
            if cached:
                items_out.append(cached)
                cache_count += 1
                continue
        try:
            items_out.append(await analyze_single_image(path, query=query, write_cache=True))
            api_count += 1
        except Exception as exc:
            logger.warning("vision analyze failed %s: %s", rel, exc)
            trajectory.append(f"视觉：读图失败 {rel}（{exc}）")
            # fall back to cache if any
            cached = evidence_from_cache(rel, as_viz=True)
            if cached:
                items_out.append(cached)
                cache_count += 1

    if api_count:
        trajectory.append(f"视觉：读图 {api_count} 张")
    if cache_count:
        trajectory.append(f"视觉：用导入缓存 {cache_count} 张")
    if not api_count and not cache_count and candidates:
        trajectory.append("视觉：未能产出证据")
    return EvidencePack(items=items_out), trajectory


async def preanalyze_imported_image(vault_rel: str, *, query: str = "") -> dict[str, Any]:
    """Import hook: analyze one vault-relative image and write wiki/viz cache."""
    from realai.llm.client import has_api_key

    if not has_api_key():
        return {"ok": False, "skipped": True, "reason": "no_api_key", "path": vault_rel}
    root = ensure_vault()
    path = (root / vault_rel.replace("\\", "/").lstrip("/")).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "reason": "outside_vault", "path": vault_rel}
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        return {"ok": False, "reason": "not_image", "path": vault_rel}
    try:
        item = await analyze_single_image(
            path,
            query=query or f"概括图片 {Path(vault_rel).name} 的图意与可读数字",
            write_cache=True,
        )
        return {
            "ok": True,
            "path": vault_rel,
            "cache": viz_cache_path_for_image(vault_rel).as_posix(),
            "excerpt": item.excerpt[:200],
        }
    except Exception as exc:
        logger.warning("preanalyze failed %s: %s", vault_rel, exc)
        return {"ok": False, "reason": str(exc), "path": vault_rel}
