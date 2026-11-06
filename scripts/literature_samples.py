"""Generate original, non-scientific PDF fixtures for local parser evaluation.

Run with the isolated experiment environment; requires reportlab, Pillow and
pypdfium2. All text/data are authored for this repository, not user literature.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def table(pdf: canvas.Canvas, y: float, rows: list[tuple[str, str, str]]) -> None:
    """Draw a ruled table with explicit unit-bearing headers."""
    x = 60
    widths = (180, 140, 140)
    values = [("Sample", "Mass (mg)", "Time (s)"), *rows]
    height = 28
    for index, row in enumerate(values):
        pdf.setFont("Helvetica-Bold" if index == 0 else "Helvetica", 11)
        for column, value in enumerate(row):
            left = x + sum(widths[:column])
            pdf.rect(left, y - (index + 1) * height, widths[column], height)
            pdf.drawString(left + 8, y - index * height - 18, value)


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    figure = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(figure)
    draw.line((110, 40, 110, 350, 830, 350), fill="black", width=5)
    for left, top, color in [(220, 180, "#4477aa"), (430, 110, "#cc6677")]:
        draw.rectangle((left, top, left + 100, 348), fill=color)
    draw.text((210, 365), "CONTROL", fill="black", font_size=28)
    draw.text((430, 365), "TREATED", fill="black", font_size=28)
    draw.text((140, 40), "SYNTHETIC SIGNAL", fill="black", font_size=28)
    figure.save(destination / "original_figure.png")

    digital_path = destination / "digital_twocolumn_figure_table.pdf"
    pdf = canvas.Canvas(str(digital_path))
    pdf.setTitle("Original parser fixture: digital columns, figure and table")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(60, 790, "Synthetic Literature Parser Evaluation")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(60, 750, "1. Two-column reading order")
    pdf.setFont("Helvetica", 10)
    for index in range(10):
        pdf.drawString(
            60, 725 - index * 17, f"LEFT-{index + 1:02d}: The left column is read first."
        )
        pdf.drawString(315, 725 - index * 17, f"RIGHT-{index + 1:02d}: Read after all left lines.")
    pdf.drawImage(ImageReader(figure), 100, 335, width=360, height=168)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(60, 310, "Figure 1. Synthetic bars; heights illustrate layout only.")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(60, 275, "2. Measurements")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(60, 250, "Table 1. Fabricated measurements for parser testing.")
    table(pdf, 235, [("Alpha", "12.5", "30"), ("Beta*", "8.0", "45")])
    pdf.setFont("Helvetica", 10)
    pdf.drawString(60, 130, "* Beta is a synthetic control; values are not experimental results.")
    pdf.drawString(60, 45, "Page 1")
    pdf.save()

    pdf = canvas.Canvas(str(destination / "cross_page_table.pdf"))
    pdf.setTitle("Original parser fixture: a table split over two PDF pages")
    for page, rows in enumerate(
        [[("A", "1.0", "10"), ("B", "2.0", "20")],
         [("C", "3.0", "30"), ("D*", "4.0", "40")]],
        start=1,
    ):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(60, 790, "Cross-page structured table")
        pdf.setFont("Helvetica", 11)
        continuation = " (continued)" if page == 2 else ""
        pdf.drawString(60, 750, f"Table 2. Fabricated time series{continuation}.")
        table(pdf, 720, rows)
        if page == 2:
            pdf.drawString(60, 610, "* D marks the last synthetic row; mg and s are units.")
        pdf.drawString(60, 45, f"Page {page}")
        pdf.showPage()
    pdf.save()

    # Raster-only scan: no PDF text layer. OCR must recover these exact tokens.
    scan_source = destination / "scan_source.pdf"
    pdf = canvas.Canvas(str(scan_source))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(60, 770, "Scanned Synthetic Abstract")
    pdf.setFont("Helvetica", 14)
    for index, line in enumerate(
        ["SCAN-ALPHA: This page contains no searchable text layer.",
         "The fabricated control mass is 12.5 mg.",
         "The fabricated observation time is 30 s.",
         "No biological conclusion is supported by this fixture."]
    ):
        pdf.drawString(60, 715 - 35 * index, line)
    pdf.save()
    source = pdfium.PdfDocument(scan_source)
    bitmap = source[0].render(scale=2).to_pil()
    bitmap.save(destination / "scan.png")
    pdf = canvas.Canvas(str(destination / "scan_ocr.pdf"))
    pdf.setTitle("Original raster-only OCR fixture")
    pdf.drawImage(ImageReader(bitmap), 0, 0, width=595.2756, height=841.8898)
    pdf.save()
    source.close()
    scan_source.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/task38/samples"))
    generate(parser.parse_args().output)
