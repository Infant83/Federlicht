from __future__ import annotations

import base64
import io
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..utils.json_tools import extract_json_object
from ..utils.strings import slugify_url


def read_pdf_with_fitz(
    pdf_path: Path,
    max_pages: int,
    max_chars: int,
    start_page: int = 0,
    auto_extend_pages: int = 0,
    extend_min_chars: int = 0,
) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return "PyMuPDF (pymupdf) is not installed. Cannot read PDF."
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        return f"[error] Failed to load PDF '{pdf_path.name}': {exc}"
    try:
        total_pages = doc.page_count
        start_page = max(0, min(start_page, max(0, total_pages - 1)))
        if max_pages <= 0:
            pages = max(0, total_pages - start_page)
        else:
            pages = min(max_pages, total_pages - start_page)
        chunks: list[str] = []
        for page in range(start_page, start_page + pages):
            try:
                chunks.append(doc.load_page(page).get_text())
            except Exception as exc:
                chunks.append(f"[warn] Failed to read page {page + 1}: {exc}")
        pages_read = pages
        text = "\n".join(chunks)
        if (
            auto_extend_pages
            and extend_min_chars
            and len(text) < extend_min_chars
            and start_page + pages_read < total_pages
        ):
            remaining_pages = total_pages - (start_page + pages_read)
            extra = min(auto_extend_pages, remaining_pages)
            for page in range(start_page + pages_read, start_page + pages_read + extra):
                try:
                    chunks.append(doc.load_page(page).get_text())
                except Exception as exc:
                    chunks.append(f"[warn] Failed to read page {page + 1}: {exc}")
            pages_read += extra
            text = "\n".join(chunks)
        note = ""
        if start_page + pages_read < total_pages:
            first_page = start_page + 1
            last_page = start_page + pages_read
            note = (
                f"\n\n[note] PDF scan truncated: pages {first_page}-{last_page} of {total_pages}. "
                "Increase --max-pdf-pages or use start_page to read more."
            )
        if max_chars > 0:
            if note:
                remaining = max_chars - len(note)
                if remaining <= 0:
                    return note[:max_chars]
                return f"{text[:remaining]}{note}"
            return text[:max_chars]
        return f"{text}{note}"
    finally:
        doc.close()


def extract_pdf_images(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    max_per_pdf: int,
    min_area: int,
) -> list[dict]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    candidates: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return records
    seen: set[int] = set()
    for page_index in range(len(doc)):
        page = doc[page_index]
        images = page.get_images(full=True)
        for img_index, img in enumerate(images):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue
            width = int(base.get("width") or 0)
            height = int(base.get("height") or 0)
            if width and height and width * height < min_area:
                continue
            ext = (base.get("ext") or "png").lower()
            image_bytes = base.get("image", b"")
            if not image_bytes:
                continue
            pil = _pillow_image()
            if pil is not None:
                try:
                    image = pil.open(io.BytesIO(image_bytes))
                except Exception:
                    continue
                if not _image_is_probably_figure(image, min_area):
                    continue
            tag = f"{pdf_rel}#p{page_index + 1}-{img_index + 1}"
            candidates.append(
                {
                    "pdf_path": pdf_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "area": width * height,
                    "tag": tag,
                    "ext": ext,
                    "image": image_bytes,
                }
            )
    if candidates:
        candidates.sort(key=lambda item: item["area"], reverse=True)
        for candidate in candidates[:max_per_pdf]:
            name = f"{slugify_url(candidate['tag'])}.{candidate['ext']}"
            img_path = output_dir / name
            if not img_path.exists():
                try:
                    with img_path.open("wb") as handle:
                        handle.write(candidate["image"])
                except Exception:
                    continue
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": candidate["pdf_path"],
                    "image_path": img_rel,
                    "page": candidate["page"],
                    "width": candidate["width"],
                    "height": candidate["height"],
                    "method": "embedded",
                }
            )
    doc.close()
    return records


def _pillow_image() -> Optional[object]:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    return Image


def encode_image_for_vision(image_path: Path, max_side: int = 1024) -> tuple[str, str]:
    Image = _pillow_image()
    if Image:
        try:
            with Image.open(image_path) as img:
                if max(img.size) > max_side:
                    scale = max_side / max(img.size)
                    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                    img = img.resize(new_size)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                data = buffer.getvalue()
                return base64.b64encode(data).decode("utf-8"), "image/png"
        except Exception:
            pass
    data = image_path.read_bytes()
    mime = "image/png"
    if image_path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    return base64.b64encode(data).decode("utf-8"), mime


def analyze_figure_with_vision(model, image_path: Path) -> Optional[dict]:
    payload_b64, mime = encode_image_for_vision(image_path)
    system_prompt = (
        "You are an image analyst. Describe the figure strictly based on what is visible. "
        "Return JSON only with keys: summary (1-2 sentences), type (chart/diagram/table/screenshot/photo/other), "
        "relevance (0-100), recommended (yes/no). If unclear, use summary='unclear'."
    )
    user_content = [
        {"type": "text", "text": "Analyze this figure for a technical report."},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload_b64}"}},
    ]
    try:
        result = model.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
    except Exception as exc:
        return {"summary": "vision_error", "error": str(exc)}
    content = getattr(result, "content", None)
    text = content if isinstance(content, str) else str(content)
    parsed = extract_json_object(text)
    if isinstance(parsed, dict):
        return parsed
    return {"summary": text.strip()[:400]}


def _image_is_probably_figure(image, min_area: int) -> bool:
    width, height = image.size
    if width <= 0 or height <= 0:
        return False
    area = width * height
    if area < min_area:
        return False
    aspect = width / height
    if aspect > 6.0 or aspect < (1 / 6.0):
        return False
    if width < 80 or height < 80:
        return False
    try:
        from PIL import ImageStat  # type: ignore
    except Exception:
        return True
    try:
        thumb = image.resize((128, 128))
        gray = thumb.convert("L")
        hist = gray.histogram()
        total = max(sum(hist), 1)
        white = sum(hist[246:]) / total
        if white > 0.96:
            return False
        stats = ImageStat.Stat(gray)
        if stats.var and stats.var[0] < 30:
            return False
    except Exception:
        return True
    return True


def _crop_whitespace(image, min_area: int) -> Optional[object]:
    try:
        gray = image.convert("L")
        mask = gray.point(lambda x: 0 if x > 245 else 255, "1")
        bbox = mask.getbbox()
    except Exception:
        return image
    if not bbox:
        return None
    left, top, right, bottom = bbox
    margin = 6
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(image.width, right + margin)
    bottom = min(image.height, bottom + margin)
    cropped = image.crop((left, top, right, bottom))
    if cropped.width * cropped.height < min_area:
        return None
    return cropped


def _opencv_backend():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None, None
    return cv2, np


def _detect_figure_regions(image, min_area: int) -> list[tuple[int, int, int, int]]:
    cv2, np = _opencv_backend()
    if cv2 is None or np is None:
        return []
    if image is None:
        return []
    try:
        rgb = np.array(image.convert("RGB"))
    except Exception:
        return []
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    height, width = gray.shape[:2]
    page_area = max(width * height, 1)
    boxes: list[tuple[int, int, int, int]] = []
    min_w = max(int(width * 0.1), 80)
    min_h = max(int(height * 0.08), 80)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < min_area:
            continue
        if w < min_w or h < min_h:
            continue
        aspect = w / h if h else 0.0
        if aspect > 6.0 or aspect < (1 / 6.0):
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: box[2] * box[3], reverse=True)
    if len(boxes) > 1:
        x, y, w, h = boxes[0]
        if (w * h) / page_area > 0.85:
            boxes = boxes[1:]
    return boxes


def extract_image_crops(image, min_area: int, max_regions: int) -> list[object]:
    if image is None:
        return []
    crops: list[object] = []
    regions = _detect_figure_regions(image, min_area)
    if regions:
        margin = 8
        for x, y, w, h in regions:
            left = max(0, x - margin)
            top = max(0, y - margin)
            right = min(image.width, x + w + margin)
            bottom = min(image.height, y + h + margin)
            cropped = image.crop((left, top, right, bottom))
            if cropped.width * cropped.height < min_area:
                continue
            crops.append(cropped)
            if max_regions and len(crops) >= max_regions:
                break
    if not crops:
        cropped = _crop_whitespace(image, min_area)
        if cropped is not None:
            crops.append(cropped)
    return crops


def _pdfium_available() -> bool:
    try:
        __import__("pypdfium2")
    except Exception:
        return False
    return _pillow_image() is not None


def _poppler_available() -> bool:
    return shutil.which("pdftocairo") is not None


def _mupdf_available() -> bool:
    return shutil.which("mutool") is not None


def select_figure_renderer(choice: str) -> str:
    value = (choice or "auto").strip().lower()
    if value in {"none", "off"}:
        return "none"
    if value == "pdfium":
        return "pdfium" if _pdfium_available() else "none"
    if value == "poppler":
        return "poppler" if _poppler_available() else "none"
    if value == "mupdf":
        return "mupdf" if _mupdf_available() else "none"
    if _pdfium_available():
        return "pdfium"
    if _poppler_available():
        return "poppler"
    if _mupdf_available():
        return "mupdf"
    return "none"


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    renderer: str,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    choice = select_figure_renderer(renderer)
    if choice == "none":
        return []
    try:
        if choice == "pdfium":
            return render_pdf_pages_pdfium(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
        if choice == "poppler":
            return render_pdf_pages_poppler(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
        if choice == "mupdf":
            return render_pdf_pages_mupdf(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
    except Exception:
        return []
    return []


def render_pdf_pages_pdfium(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        return []
    pillow = _pillow_image()
    if pillow is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    try:
        doc = pdfium.PdfDocument(str(pdf_path))
    except Exception:
        return []
    try:
        pages = len(doc)
        scale = max(dpi / 72.0, 0.1)
        for page_index in range(pages):
            if len(records) >= max_pages:
                break
            try:
                page = doc.get_page(page_index)
            except Exception:
                continue
            try:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
            except Exception:
                continue
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            crops = extract_image_crops(image, min_area, max_pages - len(records)) if image else []
            if not crops:
                continue
            for crop_index, cropped in enumerate(crops, start=1):
                tag = f"{pdf_rel}#render-p{page_index + 1}"
                if len(crops) > 1:
                    tag = f"{tag}-f{crop_index}"
                name = f"{slugify_url(tag)}.png"
                img_path = output_dir / name
                try:
                    cropped.save(img_path, format="PNG")
                except Exception:
                    continue
                img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
                records.append(
                    {
                        "pdf_path": pdf_rel,
                        "image_path": img_rel,
                        "page": page_index + 1,
                        "width": int(cropped.width),
                        "height": int(cropped.height),
                        "method": "rendered",
                    }
                )
                if len(records) >= max_pages:
                    break
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return records


def _crop_image_path(image_path: Path, min_area: int) -> Optional[tuple[int, int]]:
    pillow = _pillow_image()
    if pillow is None:
        return None
    Image = pillow
    try:
        image = Image.open(image_path)
    except Exception:
        return None
    cropped = _crop_whitespace(image, min_area)
    if cropped is None:
        return None
    if cropped is not image:
        try:
            cropped.save(image_path, format="PNG")
        except Exception:
            return None
    return int(cropped.width), int(cropped.height)


def render_pdf_pages_poppler(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    if not _poppler_available():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    for page_index in range(max_pages):
        if len(records) >= max_pages:
            break
        tag = f"{pdf_rel}#render-p{page_index + 1}"
        name = f"{slugify_url(tag)}.png"
        img_path = output_dir / name
        prefix = img_path.with_suffix("")
        cmd = [
            "pdftocairo",
            "-f",
            str(page_index + 1),
            "-l",
            str(page_index + 1),
            "-png",
            "-singlefile",
            "-r",
            str(dpi),
            str(pdf_path),
            str(prefix),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not img_path.exists():
            if page_index == 0:
                break
            continue
        pillow = _pillow_image()
        if pillow is None:
            size = _crop_image_path(img_path, min_area)
            if size is None:
                continue
            width, height = size
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "method": "rendered",
                }
            )
            continue
        try:
            image = pillow.open(img_path)
        except Exception:
            continue
        crops = extract_image_crops(image, min_area, max_pages - len(records))
        if not crops:
            continue
        if len(crops) > 1 and img_path.exists():
            try:
                img_path.unlink()
            except Exception:
                pass
        for crop_index, cropped in enumerate(crops, start=1):
            tag = f"{pdf_rel}#render-p{page_index + 1}"
            if len(crops) > 1:
                tag = f"{tag}-f{crop_index}"
            name = f"{slugify_url(tag)}.png"
            crop_path = output_dir / name
            try:
                cropped.save(crop_path, format="PNG")
            except Exception:
                continue
            img_rel = f"./{crop_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": int(cropped.width),
                    "height": int(cropped.height),
                    "method": "rendered",
                }
            )
            if len(records) >= max_pages:
                break
    return records


def render_pdf_pages_mupdf(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    if not _mupdf_available():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    for page_index in range(max_pages):
        if len(records) >= max_pages:
            break
        tag = f"{pdf_rel}#render-p{page_index + 1}"
        name = f"{slugify_url(tag)}.png"
        img_path = output_dir / name
        cmd = [
            "mutool",
            "draw",
            "-r",
            str(dpi),
            "-o",
            str(img_path),
            str(pdf_path),
            str(page_index + 1),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not img_path.exists():
            if page_index == 0:
                break
            continue
        pillow = _pillow_image()
        if pillow is None:
            size = _crop_image_path(img_path, min_area)
            if size is None:
                continue
            width, height = size
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "method": "rendered",
                }
            )
            continue
        try:
            image = pillow.open(img_path)
        except Exception:
            continue
        crops = extract_image_crops(image, min_area, max_pages - len(records))
        if not crops:
            continue
        if len(crops) > 1 and img_path.exists():
            try:
                img_path.unlink()
            except Exception:
                pass
        for crop_index, cropped in enumerate(crops, start=1):
            tag = f"{pdf_rel}#render-p{page_index + 1}"
            if len(crops) > 1:
                tag = f"{tag}-f{crop_index}"
            name = f"{slugify_url(tag)}.png"
            crop_path = output_dir / name
            try:
                cropped.save(crop_path, format="PNG")
            except Exception:
                continue
            img_rel = f"./{crop_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": int(cropped.width),
                    "height": int(cropped.height),
                    "method": "rendered",
                }
            )
            if len(records) >= max_pages:
                break
    return records
