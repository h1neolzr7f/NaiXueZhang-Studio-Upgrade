"""补跑曾 mosaic:skip 的试生成图（仅补缺失打码步骤）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from post_pipeline import GENERATED_DIR, pipeline_item_state, process_image  # noqa: E402
from pixiv_launch import _pipeline_overrides, load_config  # noqa: E402


def _is_primary_stem(stem: str) -> bool:
    return not any(
        marker in stem
        for marker in ("_final", "_up", "_mosaic", "_clean")
    )


def targets() -> list[str]:
    cfg = load_config()
    overrides = _pipeline_overrides(cfg)
    out: list[str] = []
    from generated_layout import iter_pngs

    for png in sorted(iter_pngs(GENERATED_DIR, primary_only=True)):
        if not _is_primary_stem(png.stem):
            continue
        state = pipeline_item_state(png.stem, overrides=overrides)
        if state.get("mosaic_skip") or "mosaic_failed" in (state.get("missing") or []):
            out.append(png.stem)
    return out


def main() -> int:
    cfg = load_config()
    overrides = _pipeline_overrides(cfg)
    ids = targets()
    print(f"待补打码：{len(ids)} 张")
    ok = fail = 0
    for i, stem in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}] {stem} …", flush=True)
        try:
            result = process_image(stem, overrides=overrides, only_missing=True)
            if result.get("ok"):
                ok += 1
                print(f"  OK {result.get('message')}", flush=True)
            else:
                fail += 1
                print(f"  FAIL {result.get('message')}", flush=True)
        except Exception as exc:
            fail += 1
            print(f"  FAIL {exc}", flush=True)
    print(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())