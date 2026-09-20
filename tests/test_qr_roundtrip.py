"""Круг «генерация -> распознавание»: QR приложения читается декодером сканера.

Тест поднимает Node и прогоняет tools/check_qr_roundtrip.js: он берёт матрицу из
нашего app/static/js/qr.js, растеризует её в пиксели и читает тем самым файлом,
который отдаётся сканеру (app/static/js/vendor/jsQR.min.js). Так проверяется не
«похоже на QR», а то, что код с экрана гостя действительно распознаётся кухней.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="нужен Node.js: декодер jsQR исполняется в нём")
def test_qr_roundtrip_through_scanner_decoder() -> None:
    result = subprocess.run(
        [NODE, "tools/check_qr_roundtrip.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"QR не читается декодером сканера:\n{result.stdout[-2000:]}"
    assert "Все QR читаются" in result.stdout


def test_bundled_decoder_is_present_and_intact() -> None:
    """Файл декодера лежит в репозитории, а не подтягивается по ссылке."""
    vendor = ROOT / "app" / "static" / "js" / "vendor" / "jsQR.min.js"
    assert vendor.is_file(), "нет app/static/js/vendor/jsQR.min.js"
    content = vendor.read_text(encoding="utf-8", errors="replace")
    assert len(content) > 50_000, "файл декодера подозрительно мал"
    assert "jsQR" in content or "jsqr" in content, "это не сборка jsQR"
