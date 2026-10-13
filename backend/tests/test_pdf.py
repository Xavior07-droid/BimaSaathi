import hashlib
import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.services import pdf as P

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "sample_policies"
CLEAN = (SAMPLES / "01_sanjivani_suraksha_clean.pdf").read_bytes()
BILINGUAL = (SAMPLES / "03_maharashtra_jeevan_raksha_bilingual_en_mr.pdf").read_bytes()
SCANNED = (SAMPLES / "04_nirogi_senior_scanned.pdf").read_bytes()


def make_pdf(page_texts: list[str]) -> bytes:
    d = pymupdf.open()
    for t in page_texts:
        pg = d.new_page()
        if t:
            pg.insert_textbox(pymupdf.Rect(50, 50, 550, 780), t, fontsize=11)
    return d.tobytes()


def test_sha256_matches_hashlib_and_is_stable():
    assert P.sha256_hex(CLEAN) == hashlib.sha256(CLEAN).hexdigest() == P.parse_document(CLEAN).file_hash


def test_sniff_by_magic_bytes_not_extension():
    assert P.sniff_kind(CLEAN) == "pdf"
    assert P.sniff_kind(b"\xff\xd8\xff\xe0abc") == "jpeg"
    assert P.sniff_kind(b"\x89PNG\r\n\x1a\nxxx") == "png"
    assert P.sniff_kind(b"MZ\x90\x00 an exe") is None
    assert P.sniff_kind(b"") is None


def test_text_pdf_is_parsed_and_page_tagged():
    doc = P.parse_document(CLEAN)
    assert doc.kind == "pdf" and doc.page_count == 5 and not doc.is_scanned
    assert not any(p.needs_image for p in doc.pages)
    t = P.tagged_text(doc)
    assert t.startswith("[Page 1]") and "[Page 5]" in t
    assert "5,00,000" in t.split("[Page 2]")[0]          # sum insured sits on page 1
    assert "Rs. 5,000 per day" in t.split("[Page 3]")[1].split("[Page 4]")[0]


def test_only_pages_filter():
    t = P.tagged_text(P.parse_document(CLEAN), only_pages=[2, 4])
    assert "[Page 2]" in t and "[Page 4]" in t and "[Page 3]" not in t


def test_bilingual_pdf_keeps_devanagari():
    t = P.tagged_text(P.parse_document(BILINGUAL))
    assert any("\u0900" <= c <= "\u097f" for c in t)


def test_scanned_pdf_is_detected_and_all_pages_need_images():
    doc = P.parse_document(SCANNED)
    assert doc.is_scanned and doc.page_count == 3
    assert doc.image_page_numbers == [1, 2, 3] and all(p.char_count == 0 for p in doc.pages)
    assert "[Page 2]" in P.tagged_text(doc)              # markers survive even with no text


def test_hybrid_document_flags_only_the_blank_page():
    doc = P.parse_document(make_pdf(["word " * 80, "", "word " * 80]))
    assert doc.image_page_numbers == [2] and not doc.is_scanned


def test_mostly_blank_document_counts_as_scanned():
    assert P.parse_document(make_pdf(["", "", "word " * 80])).is_scanned


def test_render_images_150_dpi_jpeg():
    imgs = P.render_page_images(CLEAN, pages=[1, 3])
    assert [i.number for i in imgs] == [1, 3]
    for i in imgs:
        assert i.mime_type == "image/jpeg" and i.data[:3] == b"\xff\xd8\xff"
        assert (i.width, i.height) == pytest.approx((1240, 1754), abs=3)        # A4 @ 150 DPI
        assert len(i.data) < 600_000
        assert Image.open(io.BytesIO(i.data)).size == (i.width, i.height)


def test_render_scanned_pages_and_bad_page_numbers():
    assert len(P.render_page_images(SCANNED)) == 3
    with pytest.raises(P.PdfError) as e:
        P.render_page_images(CLEAN, pages=[9])
    assert e.value.error_code == "bad_page"


def test_render_cap():
    with pytest.raises(P.PdfError) as e:
        P.render_page_images(CLEAN, max_pages=2)
    assert e.value.error_code == "too_many_pages"


def test_photo_upload_is_one_scanned_page_and_exif_rotation_applied():
    img = Image.new("RGB", (3000, 1500), "white")
    exif = Image.Exif()
    exif[0x0112] = 6                                     # "rotate 90 CW to display"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    doc = P.parse_document(buf.getvalue())
    assert doc.kind == "image" and doc.is_scanned and doc.page_count == 1
    out = P.render_page_images(buf.getvalue())[0]
    assert out.height > out.width and max(out.width, out.height) <= P.MAX_IMAGE_SIDE


def test_png_upload_works():
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, "PNG")
    assert P.parse_document(buf.getvalue()).kind == "image"


@pytest.mark.parametrize("data,code", [
    (b"just some text", "unsupported_type"),
    (b"", "unsupported_type"),
    (b"%PDF-1.7 truncated garbage", "unreadable_file"),
    (b"\xff\xd8\xff garbage", "unreadable_file"),
    (CLEAN[: len(CLEAN) // 3], "unreadable_file"),
])
def test_bad_input_gives_error_codes(data, code):
    with pytest.raises(P.PdfError) as e:
        P.parse_document(data)
    assert e.value.error_code == code and e.value.message


def test_password_protected_pdf():
    d = pymupdf.open(stream=CLEAN, filetype="pdf")
    locked = d.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    with pytest.raises(P.PdfError) as e:
        P.parse_document(locked)
    assert e.value.error_code == "password_protected"


def test_too_many_pages(monkeypatch):
    monkeypatch.setattr(P, "MAX_PAGES", 3)
    with pytest.raises(P.PdfError) as e:
        P.parse_document(CLEAN)
    assert e.value.error_code == "too_many_pages"
