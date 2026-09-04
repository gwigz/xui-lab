"""Compare deterministic RGBA PNG captures with platform baselines."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .errors import AssertionFailure

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ImageComparison:
    """Measured difference between two captures."""

    width: int
    height: int
    changed_pixels: int
    max_channel_delta: int

    @property
    def changed_fraction(self) -> float:
        return self.changed_pixels / (self.width * self.height)


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (
        abs(estimate - left),
        abs(estimate - above),
        abs(estimate - upper_left),
    )
    return (left, above, upper_left)[distances.index(min(distances))]


def _rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise AssertionFailure(f"image baseline is not a PNG: {path}")

    cursor = len(PNG_SIGNATURE)
    width = height = 0
    compressed = bytearray()
    while cursor < len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        chunk_type = data[cursor + 4 : cursor + 8]
        chunk = data[cursor + 8 : cursor + 8 + length]
        cursor += length + 12
        if chunk_type == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk)
            )
            if (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise AssertionFailure(
                    f"image baseline must be an 8-bit non-interlaced RGBA PNG: {path}"
                )
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise AssertionFailure(f"image baseline has no dimensions: {path}")
    decoded = zlib.decompress(compressed)
    stride = width * 4
    expected_size = height * (stride + 1)
    if len(decoded) != expected_size:
        raise AssertionFailure(f"image baseline has invalid pixel data: {path}")

    pixels = bytearray()
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = decoded[offset]
        row = bytearray(decoded[offset + 1 : offset + 1 + stride])
        offset += stride + 1
        for index, value in enumerate(row):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + above) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (value + _paeth(left, above, upper_left)) & 0xFF
            elif filter_type != 0:
                raise AssertionFailure(
                    f"image baseline uses unknown PNG filter {filter_type}: {path}"
                )
        pixels.extend(row)
        previous = row
    return width, height, bytes(pixels)


def compare_png(
    actual: Path,
    baseline: Path,
    *,
    channel_tolerance: int = 8,
    changed_fraction_tolerance: float = 0.01,
) -> ImageComparison:
    """Compare two captures and fail when their pixel difference exceeds the limit."""
    if not 0 <= channel_tolerance <= 255:
        raise ValueError("channel_tolerance must be between 0 and 255")
    if not 0 <= changed_fraction_tolerance <= 1:
        raise ValueError("changed_fraction_tolerance must be between 0 and 1")

    actual_width, actual_height, actual_pixels = _rgba(actual)
    baseline_width, baseline_height, baseline_pixels = _rgba(baseline)
    if (actual_width, actual_height) != (baseline_width, baseline_height):
        raise AssertionFailure(
            "capture dimensions differ from the platform baseline: "
            f"{actual_width}x{actual_height} != {baseline_width}x{baseline_height}"
        )

    changed_pixels = 0
    maximum = 0
    for offset in range(0, len(actual_pixels), 4):
        delta = max(
            abs(actual_pixels[offset + channel] - baseline_pixels[offset + channel])
            for channel in range(4)
        )
        maximum = max(maximum, delta)
        changed_pixels += delta > channel_tolerance

    comparison = ImageComparison(
        width=actual_width,
        height=actual_height,
        changed_pixels=changed_pixels,
        max_channel_delta=maximum,
    )
    if comparison.changed_fraction > changed_fraction_tolerance:
        raise AssertionFailure(
            "capture differs from the platform baseline: "
            f"{comparison.changed_pixels} pixels changed "
            f"({comparison.changed_fraction:.3%}, limit "
            f"{changed_fraction_tolerance:.3%}); maximum channel delta "
            f"{comparison.max_channel_delta}"
        )
    return comparison
