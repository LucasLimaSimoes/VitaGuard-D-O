from __future__ import annotations

import hashlib
import json
import shutil
import re
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "real" / "sources.json"


class RealSourceDownloadError(RuntimeError):
    """Raised when the official source cannot be downloaded automatically."""


def _norm_marker(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_real_sources() -> dict:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _target_for(source_id: str) -> tuple[dict, Path]:
    sources = load_real_sources()
    if source_id not in sources:
        raise KeyError(f"Fonte desconhecida: {source_id}")
    meta = sources[source_id]
    target = ROOT / "data" / "real" / meta["target_file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    return meta, target


def validate_real_source(
    source_id: str,
    path: str | Path | None = None,
    *,
    strict: bool = True,
) -> Path:
    meta, target = _target_for(source_id)
    path = Path(path) if path is not None else target
    if not path.exists():
        raise FileNotFoundError(path)

    actual_sha = sha256_file(path)
    expected_sha = meta.get("expected_sha256")
    if expected_sha and actual_sha != expected_sha:
        message = (
            f"SHA-256 diferente do benchmark. Esperado={expected_sha} | atual={actual_sha}. "
            "A fonte oficial pode ter sido substituida/atualizada ou o arquivo enviado nao e o esperado."
        )
        if strict:
            raise RuntimeError(message)
        print("[WARN] " + message)

    try:
        with fitz.open(path) as doc:
            pages = doc.page_count
            # Fingerprint textual: suficiente para validar fontes publicas que podem
            # ser republicadas no mesmo URL sem SHA previamente congelado.
            marker_text = "\n".join(
                doc.load_page(i).get_text("text")
                for i in range(min(doc.page_count, 20))
            )
    except Exception as exc:
        raise RuntimeError(f"O arquivo nao parece ser um PDF valido: {path}") from exc

    expected_pages = meta.get("expected_pages")
    if expected_pages and pages != expected_pages:
        message = f"Numero de paginas inesperado. Esperado={expected_pages} | atual={pages}."
        if strict:
            raise RuntimeError(message)
        print("[WARN] " + message)

    markers = meta.get("expected_text_markers") or []
    if markers:
        normalized_source = _norm_marker(marker_text)
        missing = [m for m in markers if _norm_marker(m) not in normalized_source]
        if missing:
            message = "Marcadores textuais esperados nao encontrados: " + "; ".join(missing)
            if strict:
                raise RuntimeError(message)
            print("[WARN] " + message)
        else:
            print(f"[OK] fingerprint textual: {len(markers)}/{len(markers)} marcadores")

    print(f"[OK] arquivo={path.name} | paginas={pages} | sha256={actual_sha}")
    print(f"[FONTE] {meta['official_page_url']}")
    return path


def install_local_real_source(
    source_id: str,
    local_path: str | Path,
    *,
    strict: bool = True,
) -> Path:
    """Copy a user-downloaded source into data/real and validate it."""
    meta, target = _target_for(source_id)
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(local_path)

    # Validate before copying so a wrong upload never replaces a good cached PDF.
    validate_real_source(source_id, local_path, strict=strict)
    if local_path.resolve() != target.resolve():
        shutil.copy2(local_path, target)
    return validate_real_source(source_id, target, strict=strict)


def download_real_source(
    source_id: str,
    *,
    force: bool = False,
    strict: bool = True,
) -> Path:
    """Download an official document when possible.

    Some insurer sites block cloud/Colab IP ranges with HTTP 403. In that case
    this function raises RealSourceDownloadError so the notebook can switch to
    the manual browser-download + upload path without treating the project as
    broken.
    """
    meta, target = _target_for(source_id)

    if target.exists() and not force:
        print(f"[CACHE PDF] {target.name}")
        return validate_real_source(source_id, target, strict=strict)

    print(f"[DOWNLOAD] {meta['display_name']}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": meta["official_page_url"],
    }
    req = Request(meta["pdf_url"], headers=headers)

    try:
        with urlopen(req, timeout=90) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            # Write to a temporary file first; never leave a partial/captive page
            # under the benchmark filename.
            tmp = target.with_suffix(target.suffix + ".part")
            with tmp.open("wb") as out:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
            if "text/html" in content_type:
                tmp.unlink(missing_ok=True)
                raise RealSourceDownloadError(
                    "A fonte devolveu HTML em vez do PDF (provavel protecao anti-bot)."
                )
            tmp.replace(target)
    except HTTPError as exc:
        target.with_suffix(target.suffix + ".part").unlink(missing_ok=True)
        if exc.code == 403:
            raise RealSourceDownloadError(
                f"{meta.get('insurer', meta.get('display_name', 'A fonte'))} bloqueou o download automatico deste ambiente com HTTP 403. "
                "Isso e uma restricao do servidor ao ambiente Colab, nao uma falha do pipeline."
            ) from exc
        raise RealSourceDownloadError(
            f"Falha HTTP ao baixar a fonte oficial: {exc.code} {exc.reason}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        target.with_suffix(target.suffix + ".part").unlink(missing_ok=True)
        raise RealSourceDownloadError(
            f"Nao foi possivel baixar a fonte oficial automaticamente: {type(exc).__name__}: {exc}"
        ) from exc

    return validate_real_source(source_id, target, strict=strict)
