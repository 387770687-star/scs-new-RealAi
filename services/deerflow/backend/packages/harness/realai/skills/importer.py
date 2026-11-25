"""Import Skill packages (zip) into skills/."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from realai.skills.registry import (
    SKILL_FILENAME,
    get_skill,
    parse_skill_markdown,
    save_skill,
    skill_package_dir,
    validate_skill_id,
)

_MAX_FILES = 200
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_PACKAGE_BYTES = 20 * 1024 * 1024


def import_skill_zip(data: bytes) -> list[str]:
    packages: dict[str, dict[str, bytes]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        files = [info for info in zf.infolist() if not info.is_dir()]
        if len(files) > _MAX_FILES:
            raise ValueError(f"Skill 压缩包文件数不能超过 {_MAX_FILES}")
        if sum(info.file_size for info in files) > _MAX_PACKAGE_BYTES:
            raise ValueError("Skill 压缩包解压后不能超过 20MB")

        roots: dict[tuple[str, ...], str] = {}
        for info in files:
            parts = Path(info.filename.replace("\\", "/")).parts
            if not parts or any(part in {"", ".", ".."} for part in parts) or Path(info.filename).is_absolute():
                raise ValueError("压缩包包含非法文件路径")
            if info.file_size > _MAX_FILE_BYTES:
                raise ValueError(f"Skill 单文件不能超过 5MB：{info.filename}")
            if parts[-1] != SKILL_FILENAME or len(parts) < 2:
                continue
            skill_id = parts[-2]
            validate_skill_id(skill_id)
            root = tuple(parts[:-1])
            if skill_id in roots.values() and roots.get(root) != skill_id:
                raise ValueError(f"压缩包内存在重复 Skill：{skill_id}")
            roots[root] = skill_id

        if not roots:
            raise ValueError("压缩包内未找到 <skill-id>/SKILL.md 结构")

        for root, skill_id in roots.items():
            package: dict[str, bytes] = {}
            for info in files:
                parts = Path(info.filename.replace("\\", "/")).parts
                if tuple(parts[: len(root)]) != root:
                    continue
                rel_parts = parts[len(root) :]
                if not rel_parts:
                    continue
                rel = Path(*rel_parts).as_posix()
                package[rel] = zf.read(info)
            packages[skill_id] = package

    for skill_id, package in packages.items():
        if get_skill(skill_id) is not None:
            raise FileExistsError(f"Skill '{skill_id}' 已存在，导入已取消")
        raw = package.get(SKILL_FILENAME)
        if raw is None:
            raise ValueError(f"Skill '{skill_id}' 缺少 {SKILL_FILENAME}")
        rec = parse_skill_markdown(raw.decode("utf-8", errors="replace"), skill_id=skill_id)
        if not rec.valid:
            raise ValueError(f"Skill '{skill_id}' 无效：{'；'.join(rec.errors)}")

    imported: list[str] = []
    for skill_id, package in packages.items():
        raw = package[SKILL_FILENAME].decode("utf-8", errors="replace")
        rec = parse_skill_markdown(raw, skill_id=skill_id)
        save_skill(
            skill_id,
            name=rec.name,
            description=rec.description,
            body=rec.body,
            category="custom",
            overwrite=False,
        )
        root = skill_package_dir(skill_id)
        if root is None:
            raise RuntimeError(f"Skill '{skill_id}' 导入目录创建失败")
        for rel, content in package.items():
            if rel == SKILL_FILENAME:
                continue
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        imported.append(skill_id)

    if not imported:
        raise ValueError("压缩包内未找到 <skill-id>/SKILL.md 结构")
    return imported
