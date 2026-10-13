"""A10: scanned / photo / mixed documents are sent as labelled page images, not as an attached PDF."""
import io

import pymupdf
import pytest
from PIL import Image

from app.services import policy_brain as PB
from app.services.pdf import MAX_IMAGE_PAGES, parse_document
from tests.test_policy_brain import MANIFEST, FakeGemini, answer_from_manifest, bad, pdf_bytes

SCANNED = pdf_bytes(MANIFEST[3]["file"])
CLEAN = pdf_bytes(MANIFEST[0]["file"])
LONG_TEXT = "Policy wording clause text. " * 20          # > 100 non-space chars per page


def _is_image(part):
    return not isinstance(part, str) and part.inline_data.mime_type == "image/jpeg"


def _image_only_pdf(pages: int, side: int = 400) -> bytes:
    """A PDF whose pages are pictures only (no text layer) = what a scan looks like."""
    doc = pymupdf.open()
    buf = io.BytesIO()
    Image.new("RGB", (side, side), "white").save(buf, "JPEG")
    for _ in range(pages):
        pg = doc.new_page()
        pg.insert_image(pg.rect, stream=buf.getvalue())
    out = doc.tobytes()
    doc.close()
    return out


def _mixed_pdf(text_pages: int, blank_pages: int) -> bytes:
    doc = pymupdf.open()
    for _ in range(text_pages):
        doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 550, 800), LONG_TEXT, fontsize=10)
    for _ in range(blank_pages):
        doc.new_page()
    out = doc.tobytes()
    doc.close()
    return out


def test_sample_scanned_pdf_is_detected_as_scanned():
    parsed = parse_document(SCANNED)
    assert parsed.is_scanned and parsed.image_page_numbers == list(range(1, parsed.page_count + 1))


def test_build_input_scanned_sample_is_labelled_images_without_pdf():
    parsed = parse_document(SCANNED)
    inp = PB.build_document_input(SCANNED, parsed)
    assert inp.mode == "page_images" and inp.image_pages == parsed.page_count
    labels = [p for p in inp.parts if isinstance(p, str)]
    images = [p for p in inp.parts if not isinstance(p, str)]
    assert labels == [f"[Page {n}]" for n in range(1, parsed.page_count + 1)]
    assert all(i.inline_data.mime_type == "image/jpeg" for i in images)      # no application/pdf attached
    assert [type(p) is str for p in inp.parts] == [True, False] * parsed.page_count   # label always precedes its image
    assert "read this page from its image" in inp.document_text and "[Page 1]" in inp.document_text


async def test_scanned_sample_end_to_end_request_shape():
    g = FakeGemini([answer_from_manifest(MANIFEST[3])])
    out = await PB.extract_policy(SCANNED, gemini=g)
    contents = g.calls[0]["contents"]
    assert isinstance(contents[-1], str) and f"({out.image_pages} pages)" in contents[-1]   # instructions last
    assert out.input_mode == "page_images" and out.image_pages == MANIFEST[3]["pages"]
    assert sum(_is_image(p) for p in contents) == MANIFEST[3]["pages"]
    assert out.confidence is None


async def test_images_are_rendered_once_across_retries(monkeypatch):
    calls = []
    real = PB.render_page_images
    monkeypatch.setattr(PB, "render_page_images", lambda *a, **k: calls.append(1) or real(*a, **k))
    g = FakeGemini([bad(copay_percent=150), bad(copay_percent=150), answer_from_manifest(MANIFEST[3])])
    out = await PB.extract_policy(SCANNED, gemini=g)
    assert out.used_fallback and len(g.calls) == 3 and len(calls) == 1
    assert g.calls[0]["contents"][:-1] == g.calls[2]["contents"][:-1]        # same images every attempt
    assert "REJECTED" in g.calls[1]["contents"][-1] and "REJECTED" not in g.calls[0]["contents"][-1]


def test_text_pdf_still_attached_as_pdf_with_text():
    inp = PB.build_document_input(CLEAN, parse_document(CLEAN))
    assert inp.mode == "pdf" and inp.image_pages == 0 and len(inp.parts) == 1
    assert inp.parts[0].inline_data.mime_type == "application/pdf" and "No text layer" not in inp.document_text


def test_mostly_text_pdf_with_one_blank_page_keeps_pdf_and_adds_note():
    data = _mixed_pdf(text_pages=3, blank_pages=1)
    parsed = parse_document(data)
    assert not parsed.is_scanned and parsed.image_page_numbers == [4]
    inp = PB.build_document_input(data, parsed)
    assert inp.mode == "pdf_with_image_pages" and inp.parts[0].inline_data.mime_type == "application/pdf"
    assert "[Page 4]\nNo text layer on this page: read it from the attached PDF." in inp.document_text
    assert "Policy wording clause text." in inp.document_text                 # text pages untouched


def test_scanned_pdf_with_a_few_text_pages_keeps_their_text_and_images_for_all():
    data = _mixed_pdf(text_pages=1, blank_pages=3)                            # 75% low-text -> scanned
    parsed = parse_document(data)
    assert parsed.is_scanned
    inp = PB.build_document_input(data, parsed)
    assert inp.mode == "page_images" and inp.image_pages == 4
    assert "Policy wording clause text." in inp.document_text and "[Page 2]\nNo text layer" in inp.document_text


def test_scanned_pdf_over_page_cap_is_sent_natively_not_rejected():
    data = _image_only_pdf(MAX_IMAGE_PAGES + 1, side=50)
    parsed = parse_document(data)
    assert parsed.is_scanned and parsed.page_count == MAX_IMAGE_PAGES + 1
    inp = PB.build_document_input(data, parsed)
    assert inp.mode == "pdf_native_scan" and inp.image_pages == 0
    assert inp.parts[0].inline_data.mime_type == "application/pdf"


def test_heavy_images_fall_back_to_low_dpi_then_to_native_pdf(monkeypatch):
    data = _image_only_pdf(2)
    seen = []
    real = PB.render_page_images

    def fake(d, pages=None, dpi=150, max_pages=30):
        seen.append(dpi)
        imgs = real(d, pages, dpi, max_pages)
        for im in imgs:
            im.data = b"x" * (PB.MAX_IMAGE_PAYLOAD_BYTES // 2 + 1 if dpi == 150 else 10)
        return imgs

    monkeypatch.setattr(PB, "render_page_images", fake)
    inp = PB.build_document_input(data, parse_document(data))
    assert seen == [150, PB.LOW_DPI] and inp.mode == "page_images"          # 2nd try fits

    monkeypatch.setattr(PB, "MAX_IMAGE_PAYLOAD_BYTES", 5)                    # nothing fits -> native PDF
    inp = PB.build_document_input(data, parse_document(data))
    assert inp.mode == "pdf_native_scan"


async def test_scanned_document_cited_page_beyond_range_still_rejected():
    n = MANIFEST[3]["pages"]
    g = FakeGemini([bad(covered=[{"text": "x", "source": {"page": n + 5, "clause": "1"}}]),
                    answer_from_manifest(MANIFEST[3])])
    out = await PB.extract_policy(SCANNED, gemini=g)
    assert out.retried and f"page {n + 5} does not exist" in g.calls[1]["contents"][-1]


def test_prompt_still_describes_image_pages():
    assert "each image is preceded by a `[Page N]` label" in PB.load_prompt("extract_v1").system
