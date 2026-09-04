from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from xui_lab.errors import AssertionFailure
from xui_lab.image_comparison import PNG_SIGNATURE, compare_png


def png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload))
        )

    rows = b"".join(
        b"\0" + pixels[offset : offset + width * 4]
        for offset in range(0, len(pixels), width * 4)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class ImageComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, name: str, width: int, height: int, pixels: bytes) -> Path:
        path = self.directory / name
        path.write_bytes(png(width, height, pixels))
        return path

    def test_equal_images_have_no_changed_pixels(self) -> None:
        pixels = bytes((10, 20, 30, 255, 40, 50, 60, 255))
        actual = self.write("actual.png", 2, 1, pixels)
        baseline = self.write("baseline.png", 2, 1, pixels)

        result = compare_png(actual, baseline)

        self.assertEqual(0, result.changed_pixels)
        self.assertEqual(0.0, result.changed_fraction)

    def test_small_channel_differences_use_the_tolerance(self) -> None:
        actual = self.write("actual.png", 1, 1, bytes((18, 20, 30, 255)))
        baseline = self.write("baseline.png", 1, 1, bytes((10, 20, 30, 255)))

        result = compare_png(actual, baseline, channel_tolerance=8)

        self.assertEqual(0, result.changed_pixels)
        self.assertEqual(8, result.max_channel_delta)

    def test_large_difference_fails_with_measured_result(self) -> None:
        actual = self.write("actual.png", 1, 1, bytes((255, 20, 30, 255)))
        baseline = self.write("baseline.png", 1, 1, bytes((10, 20, 30, 255)))

        with self.assertRaisesRegex(AssertionFailure, "1 pixels changed"):
            compare_png(actual, baseline)

    def test_dimension_difference_fails(self) -> None:
        actual = self.write("actual.png", 1, 1, bytes((10, 20, 30, 255)))
        baseline = self.write(
            "baseline.png", 2, 1, bytes((10, 20, 30, 255, 10, 20, 30, 255))
        )

        with self.assertRaisesRegex(AssertionFailure, "dimensions differ"):
            compare_png(actual, baseline)
