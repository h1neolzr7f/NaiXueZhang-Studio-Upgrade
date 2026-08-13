from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_contains(path: Path, needle: str) -> bool:
    return path.exists() and needle in path.read_text(encoding="utf-8", errors="ignore")


def count_pattern(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(pattern, text))


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def collect_findings(root: Path) -> dict:
    p0: list[str] = []
    p1: list[str] = []
    p2: list[str] = []

    required = [
        "README.md",
        "PRODUCT.md",
        "ROADMAP.md",
        "product_ops.py",
        "routes/product.py",
        "web/ops.html",
        "web/shared/api-client.js",
    ]
    # task_plan.md / findings.md are local agent notes (gitignored). A public
    # clone must pass this gate without those work-state files.
    for rel in required:
        if not (root / rel).exists():
            p0.append(f"缺少必需管理/驾驶舱文件：{rel}")

    server_py = root / "server.py"
    if not file_contains(server_py, "product.router"):
        p0.append("server.py 未接入 product router")
    if not file_contains(server_py, "product.page_router"):
        p0.append("server.py 未接入 /ops page router")

    route_smoke = root / "tests/test_product_route_smoke.py"
    if not route_smoke.exists():
        p0.append("缺少产品路由 smoke 测试")
    if route_smoke.exists() and "test_health_endpoint_is_fast_enough_for_dashboard" not in route_smoke.read_text(encoding="utf-8"):
        p0.append("缺少 /api/product/health 性能回归测试")

    migrated_pages = {
        "web/ops.html": "window.ApiClient.get",
        "web/settings.js": "window.ApiClient.request",
        "web/studio.js": "window.ApiClient.request",
    }
    for rel, marker in migrated_pages.items():
        if not file_contains(root / rel, marker):
            p1.append(f"{rel} 尚未使用共享 ApiClient")

    if line_count(root / "web/app.js") > 4200:
        p1.append("web/app.js 仍超过 4200 行，需要继续拆分 Gallery 前端")
    if line_count(root / "db.py") > 1000:
        p1.append("db.py 仍超过 1000 行，需要拆分 storage/search/repository")
    if count_pattern(root / "web/generated.html", r"\bfetch\s*\(") > 5:
        p1.append("web/generated.html 仍有大量分散 fetch，需迁移到 ApiClient/模块化")
    if line_count(root / "web/pixiv.html") > 1500:
        p1.append("web/pixiv.html 仍是超大页面，需拆分发布工作台")

    # Account import + gallery contract debts
    if not file_contains(root / "pixiv_accounts.py", "def import_accounts_batch"):
        p1.append("缺少 Pixiv 批量导入 import_accounts_batch")
    if not file_contains(root / "routes/pixiv.py", "/api/pixiv/accounts/import"):
        p1.append("缺少 /api/pixiv/accounts/import 路由")
    if not file_contains(root / "web/pixiv.html", "importAccountsBtn"):
        p1.append("Pixiv 页缺少批量导入 UI")
    if not file_contains(root / "tests/test_gallery_core_contract.py", "quick_send_studio"):
        p1.append("缺少图库主链路 quick_send 契约测试")
    if not file_contains(root / "web/shared/motion.css", "prefers-reduced-motion"):
        p2.append("缺少全局 motion 无障碍降级")
    if not file_contains(root / "user_prefs.py", '"quick_send_studio": False'):
        p0.append("user_prefs 默认 quick_send_studio 必须为 False（图库主链路）")

    product = (root / "PRODUCT.md").read_text(encoding="utf-8", errors="ignore") if (root / "PRODUCT.md").exists() else ""
    roadmap = (root / "ROADMAP.md").read_text(encoding="utf-8", errors="ignore") if (root / "ROADMAP.md").exists() else ""
    for keyword in ["Prompt", "角色", "Pipeline", "Pixiv"]:
        if keyword not in product + roadmap:
            p2.append(f"路线图缺少 {keyword} 能力描述")
    if not (root / "web/tag-assets.html").exists():
        p2.append("尚未实现 Prompt/角色/tag 资产视图页面")
    if not (root / "web/pipeline.html").exists():
        p2.append("尚未实现独立 Pipeline 可视化页面")

    # Stage 7 reliability contracts: keep previously fixed operational bugs
    # visible in the same gate instead of relying on separate ad-hoc checks.
    server_text = server_py.read_text(encoding="utf-8", errors="ignore") if server_py.exists() else ""
    if 'allow_origins=["*"]' in server_text:
        p0.append("server.py 不得向任意 Origin 开放本地写接口")
    for origin in ("http://127.0.0.1:8797", "http://localhost:8797"):
        if origin not in server_text:
            p1.append(f"CORS 缺少可信本地 Origin：{origin}")

    start_text = (root / "START_GALLERY.bat").read_text(encoding="utf-8", errors="ignore")
    if "pip install" in start_text or "python -m venv" in start_text:
        p1.append("START_GALLERY.bat 不得在日常启动时安装依赖或创建环境")
    if (
        "gallery_process_guard.ps1" not in start_text
        or "launch_server.vbs" not in start_text
        or not (root / "scripts/gallery_process_guard.ps1").exists()
        or not (root / "scripts/launch_server.vbs").exists()
        or "taskkill" in start_text.lower()
    ):
        p1.append("START_GALLERY.bat 必须验证端口进程归属且不得直接 taskkill")

    for rel in ("web/app.js", "web/app-core.js", "web/pixiv.js"):
        if count_pattern(root / rel, r"\bfetch\s*\("):
            p1.append(f"{rel} 仍有未迁移的同源裸 fetch")
    if not file_contains(root / "web/index.html", "/assets/shared/api-client.js"):
        p1.append("Gallery 入口未加载共享 ApiClient")
    if not file_contains(root / "web/pixiv.html", "/assets/shared/api-client.js"):
        p1.append("Pixiv 入口未加载共享 ApiClient")

    if not file_contains(root / "routes/pixiv.py", "/api/pixiv/upload-selector-probe"):
        p1.append("Pixiv 缺少上传 DOM selector 自检端点")
    if not file_contains(root / "pixiv_web_upload.py", "def probe_pixiv_upload_selectors"):
        p1.append("Pixiv 上传流程未复用统一 selector probe")
    if not (
        file_contains(root / "db_queries.py", '"image_type"')
        and file_contains(root / "db_queries.py", '"author_id"')
    ):
        p1.append("work lite payload 未携带未缓存图片所需的 CDN 路由字段")

    if (root / "web/shared/shared").exists():
        p1.append("存在误生成的 web/shared/shared 重复资源目录")
    if not file_contains(root / ".gitignore", "data/user_prefs.json"):
        p2.append("data/user_prefs.json 尚未排除出版本控制")
    if not (root / "requirements.lock.txt").exists():
        p2.append("缺少可复现的 requirements.lock.txt")

    old_root = r"E:\aitag-mirror"
    for rel in ("README.md", "build_char_tag_db.bat", "setup_web.ps1", "product_ops.py"):
        if file_contains(root / rel, old_root):
            p2.append(f"{rel} 仍包含旧项目绝对路径")

    guard = root / "scripts/check_regression_guards.js"
    if guard.exists():
        try:
            completed = subprocess.run(
                ["node", str(guard)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if completed.returncode != 0:
                p1.append("Regression Guard 未通过")
        except (OSError, subprocess.SubprocessError):
            p1.append("Regression Guard 无法执行")
    else:
        p1.append("缺少 Regression Guard")

    return {
        "ok": not p0 and not p1 and not p2,
        "p0": p0,
        "p1": p1,
        "p2": p2,
        "counts": {"p0": len(p0), "p1": len(p1), "p2": len(p2)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument(
        "--fail-on",
        choices=["p0", "p1", "p2", "none"],
        default="p0",
        help="exit non-zero when findings at or above this severity exist",
    )
    args = parser.parse_args()
    result = collect_findings(ROOT)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Product Quality Gate")
        print(json.dumps(result["counts"], ensure_ascii=False))
        for sev in ("p0", "p1", "p2"):
            print(f"\n{sev.upper()}:")
            for item in result[sev]:
                print(f"- {item}")
    fail_order = {"p0": ("p0",), "p1": ("p0", "p1"), "p2": ("p0", "p1", "p2"), "none": ()}
    should_fail = any(result[sev] for sev in fail_order[args.fail_on])
    return 1 if should_fail else 0


if __name__ == "__main__":
    sys.exit(main())
