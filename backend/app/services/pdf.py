"""PDF / image intake (A7): sha256, page-tagged text, page images at 150 DPI, scanned detection.

Everything is in memory: the uploaded bytes are never written to disk. These functions are CPU-bound and
synchronous; async callers should use `await asyncio.to_thread(...)`.

Scanned detection (measured on the 4 sample PDFs): text pages had 312-623 non-whitespace chars/page,
the scanned PDF had 0. A page with fewer than MIN_CHARS_PER_PAGE (100) is flagged `needs_image`;
a document is `is_scanned` when >= 50% of its pages are flagged.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

MIN_CHARS_PER_PAGE = 100       # non-whitespace characters
SCANNED_PAGE_FRACTION = 0.5
MAX_PAGES = 120                # real policy wordings run 40-80 pages
MAX_IMAGE_PAGES = 30           # cap on page images sent/rendered at once (memory + Gemini quota)
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_SIDE = 2000
DEFAULT_DPI = 150

Kind = Literal["pdf", "image"]


class PdfError(Exception):
    """Carries {error_code, message} for the API error shape."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code, self.message = error_code, message


@dataclass
class PageText:
    number: int                 # 1-based, matches the [Page N] marker
    text: str
    char_count: int             # non-whitespace characters
    needs_image: bool


@dataclass
class ParsedDocument:
    kind: Kind
    file_hash: str
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    is_scanned: bool = False

    @property
    def image_page_numbers(self) -> list[int]:
        return [p.number for p in self.pages if p.needs_image]


@dataclass
class PageImage:
    number: int
    mime_type: str
    data: bytes
    width: int
    height: int


# ------------------------------------------------------------------ basics
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_kind(data: bytes) -> Literal["pdf", "jpeg", "png"] | None:
    """Decide by magic bytes. Never trust the client's filename or Content-Type."""
    head = data[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - pymupdf raises several types for corrupt files
        raise PdfError("unreadable_file", "We could not read this PDF. Try a clearer copy or a photo of the pages.") from exc
    if doc.needs_pass:
        raise PdfError("password_protected", "This PDF is password protected. Remove the password and upload again.")
    if doc.page_count == 0:
        raise PdfError("unreadable_file", "This PDF has no pages.")
    if doc.page_count > MAX_PAGES:
        raise PdfError("too_many_pages", f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
    return doc


def _load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise PdfError("unreadable_file", "This image is too large. Upload a smaller photo.")
        img = ImageOps.exif_transpose(img)           # phone photos: respect orientation
        img.load()
    except PdfError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise PdfError("unreadable_file", "We could not read this image.") from exc
    return img.convert("RGB")


# ------------------------------------------------------------------ parse
def parse_document(data: bytes) -> ParsedDocument:
    kind = sniff_kind(data)
    if kind is None:
        raise PdfError("unsupported_type", "Upload a PDF, JPG or PNG file.")
    file_hash = sha256_hex(data)

    if kind in ("jpeg", "png"):
        _load_image(data)                              # validates it really is an image
        page = PageText(number=1, text="", char_count=0, needs_image=True)
        return ParsedDocument(kind="image", file_hash=file_hash, page_count=1, pages=[page], is_scanned=True)

    doc = _open_pdf(data)
    pages: list[PageText] = []
    try:
        for i, pg in enumerate(doc, start=1):
            text = _clean(pg.get_text("text"))
            n = len("".join(text.split()))
            pages.append(PageText(number=i, text=text, char_count=n, needs_image=n < MIN_CHARS_PER_PAGE))
    finally:
        doc.close()
    low = sum(p.needs_image for p in pages)
    return ParsedDocument(kind="pdf", file_hash=file_hash, page_count=len(pages), pages=pages,
                          is_scanned=(low / len(pages)) >= SCANNED_PAGE_FRACTION)


def tagged_text(parsed: ParsedDocument, only_pages: Iterable[int] | None = None) -> str:
    """'[Page 1]\\n...\\n\\n[Page 2]\\n...' so the model can cite pages. Pages without text keep their marker."""
    wanted = set(only_pages) if only_pages is not None else None
    parts = [f"[Page {p.number}]\n{p.text}" for p in parsed.pages if wanted is None or p.number in wanted]
    return "\n\n".join(parts)


# ------------------------------------------------------------------ images
def _encode_jpeg(img: Image.Image, number: int) -> PageImage:
    if max(img.size) > MAX_IMAGE_SIDE:
        img = img.copy()
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, optimize=True)
    return PageImage(number=number, mime_type="image/jpeg", data=buf.getvalue(), width=img.width, height=img.height)


def render_page_images(data: bytes, pages: Iterable[int] | None = None, dpi: int = DEFAULT_DPI,
                       max_pages: int = MAX_IMAGE_PAGES) -> list[PageImage]:
    """JPEG page images (150 DPI by default). `pages` = 1-based numbers (default: all, up to max_pages)."""
    kind = sniff_kind(data)
    if kind in ("jpeg", "png"):
        return [_encode_jpeg(_load_image(data), 1)]
    if kind != "pdf":
        raise PdfError("unsupported_type", "Upload a PDF, JPG or PNG file.")

    doc = _open_pdf(data)
    try:
        numbers = sorted(set(pages)) if pages is not None else list(range(1, doc.page_count + 1))
        bad = [n for n in numbers if not 1 <= n <= doc.page_count]
        if bad:
            raise PdfError("bad_page", f"Page(s) {bad} not in document (1-{doc.page_count}).")
        if len(numbers) > max_pages:
            raise PdfError("too_many_pages", f"Too many pages to render as images ({len(numbers)} > {max_pages}).")
        out = []
        for n in numbers:
            pix = doc[n - 1].get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out.append(_encode_jpeg(img, n))
        return out
    finally:
        doc.close()
