from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


INK = "#16212f"
BLUE = "#2563eb"
ORANGE = "#ea580c"
GRID = "#d7dde5"
MUTED = "#64748b"
BG = "#ffffff"


def _canvas(title: str, *, width: int = 1000, height: int = 620):
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((45, 24), title, fill=INK, font=font)
    return image, draw, font


def bar_chart(
    path: Path,
    *,
    title: str,
    labels: Sequence[str],
    values: Sequence[float],
    y_label: str,
    colors: Sequence[str] | None = None,
) -> None:
    if len(labels) != len(values) or not labels:
        raise ValueError("bar chart labels and values must be non-empty and aligned")
    image, draw, font = _canvas(title)
    left, top, right, bottom = 90, 75, 960, 525
    maximum = max(float(value) for value in values) or 1.0
    for step in range(6):
        y = bottom - (bottom - top) * step / 5
        value = maximum * step / 5
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((10, y - 6), f"{value:,.2f}", fill=MUTED, font=font)
    count = len(values)
    slot = (right - left) / count
    palette = list(colors or (BLUE, ORANGE))
    for index, (label, raw) in enumerate(zip(labels, values)):
        value = float(raw)
        x0 = left + index * slot + slot * 0.18
        x1 = left + (index + 1) * slot - slot * 0.18
        y0 = bottom - (bottom - top) * value / maximum
        draw.rectangle((x0, y0, x1, bottom), fill=palette[index % len(palette)])
        draw.text((x0, max(top, y0 - 18)), f"{value:,.2f}", fill=INK, font=font)
        draw.text((x0, bottom + 12), label[:24], fill=INK, font=font)
    draw.text((10, top - 25), y_label, fill=MUTED, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def histogram(
    path: Path,
    *,
    title: str,
    values: Sequence[float],
    x_label: str,
    bins: int = 16,
) -> None:
    materialized = [float(value) for value in values]
    if not materialized:
        raise ValueError("histogram requires values")
    low, high = min(materialized), max(materialized)
    if math.isclose(low, high):
        high = low + 1.0
    counts = [0] * bins
    for value in materialized:
        index = min(bins - 1, int((value - low) / (high - low) * bins))
        counts[index] += 1
    image, draw, font = _canvas(title)
    left, top, right, bottom = 90, 75, 960, 525
    maximum = max(counts) or 1
    for step in range(6):
        y = bottom - (bottom - top) * step / 5
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((35, y - 6), f"{maximum * step / 5:.0f}", fill=MUTED, font=font)
    slot = (right - left) / bins
    for index, count in enumerate(counts):
        x0 = left + index * slot + 1
        x1 = left + (index + 1) * slot - 1
        y0 = bottom - (bottom - top) * count / maximum
        draw.rectangle((x0, y0, x1, bottom), fill=BLUE)
    draw.text((left, bottom + 12), f"{low:,.1f}", fill=INK, font=font)
    draw.text((right - 70, bottom + 12), f"{high:,.1f}", fill=INK, font=font)
    draw.text(((left + right) / 2 - 60, bottom + 35), x_label, fill=MUTED, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def confusion_matrix_chart(
    path: Path,
    *,
    title: str,
    matrix: Sequence[Sequence[int]],
    negative_label: str = "NON_INTERRUPTION",
    positive_label: str = "INTERRUPTION",
) -> None:
    if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
        raise ValueError("confusion matrix must be 2x2 in [[TN, FP], [FN, TP]] order")
    image, draw, font = _canvas(title, width=760, height=650)
    labels = (negative_label, positive_label)
    values = [[int(value) for value in row] for row in matrix]
    maximum = max(value for row in values for value in row) or 1
    left, top, size = 190, 115, 185
    for truth in range(2):
        for prediction in range(2):
            value = values[truth][prediction]
            intensity = int(245 - 155 * value / maximum)
            fill = (intensity, min(245, intensity + 20), 250)
            x0, y0 = left + prediction * size, top + truth * size
            draw.rectangle((x0, y0, x0 + size, y0 + size), fill=fill, outline=GRID, width=2)
            draw.text((x0 + 78, y0 + 78), str(value), fill=INK, font=font)
    for index, label in enumerate(labels):
        draw.text((left + index * size + 25, top - 28), f"Pred {label}"[:24], fill=INK, font=font)
        draw.text((25, top + index * size + 80), f"True {label}"[:24], fill=INK, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
