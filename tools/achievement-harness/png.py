"""Minimal 8-bit RGB PNG writer and reader (standard library only) for screenshots and sheets."""

import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
BIT_DEPTH = 8
COLOR_TYPE_RGB = 2
BYTES_PER_PIXEL = 3
FILTER_NONE = b"\x00"
CHUNK_LENGTH_BYTES = 4
CHUNK_TAG_BYTES = 4
CHUNK_CRC_BYTES = 4
HEADER_FORMAT = ">IIBBBBB"
UINT32_FORMAT = ">I"
NO_COMPRESSION_METHOD = 0
NO_FILTER_METHOD = 0
NO_INTERLACE = 0


def _chunk(tag, payload):
    body = tag + payload
    return (
        struct.pack(UINT32_FORMAT, len(payload))
        + body
        + struct.pack(UINT32_FORMAT, zlib.crc32(body))
    )


def write_png(path, width, height, rgb):
    """Writes packed RGB24 pixels (`width * height * 3` bytes) as an unfiltered PNG."""
    row_bytes = width * BYTES_PER_PIXEL
    raw = b"".join(FILTER_NONE + rgb[y * row_bytes : (y + 1) * row_bytes] for y in range(height))
    header = struct.pack(
        HEADER_FORMAT,
        width,
        height,
        BIT_DEPTH,
        COLOR_TYPE_RGB,
        NO_COMPRESSION_METHOD,
        NO_FILTER_METHOD,
        NO_INTERLACE,
    )
    data = SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw))
    data += _chunk(b"IEND", b"")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def read_png(path):
    """Reads a PNG written by `write_png`: returns (width, height, [row of RGB24 bytes, ...])."""
    data = Path(path).read_bytes()
    if not data.startswith(SIGNATURE):
        raise ValueError(f"{path} is not a PNG")
    offset = len(SIGNATURE)
    idat = b""
    width = height = 0
    while offset < len(data):
        (length,) = struct.unpack(UINT32_FORMAT, data[offset : offset + CHUNK_LENGTH_BYTES])
        tag_start = offset + CHUNK_LENGTH_BYTES
        body_start = tag_start + CHUNK_TAG_BYTES
        tag = data[tag_start:body_start]
        body = data[body_start : body_start + length]
        if tag == b"IHDR":
            width, height, depth, color_type, *_ = struct.unpack(HEADER_FORMAT, body)
            if (depth, color_type) != (BIT_DEPTH, COLOR_TYPE_RGB):
                raise ValueError(f"{path}: only 8-bit RGB PNGs are supported")
        elif tag == b"IDAT":
            idat += body
        else:
            pass  # Ancillary chunks and IEND carry nothing the reader needs.
        offset = body_start + length + CHUNK_CRC_BYTES
    raw = zlib.decompress(idat)
    stride = width * BYTES_PER_PIXEL + len(FILTER_NONE)
    rows = []
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        if row[: len(FILTER_NONE)] != FILTER_NONE:
            raise ValueError(f"{path}: only unfiltered PNGs, as write_png writes, are supported")
        rows.append(row[len(FILTER_NONE) :])
    return width, height, rows
