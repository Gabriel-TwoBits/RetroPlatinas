"""Contact sheet: tiles screenshots (downscaled) into one PNG, to review many frames at once.

Usage:

    python tools/achievement-harness/sheet.py OUT.png SHOT.png [SHOT.png ...]
"""

import argparse

from png import BYTES_PER_PIXEL, read_png, write_png

TILE_WIDTH = 256
TILE_HEIGHT = 120
COLUMNS = 4
SEPARATOR_RGB = b"\xff\xff\xff"


def contact_sheet(paths, out, columns=COLUMNS):
    rows_count = (len(paths) + columns - 1) // columns
    sheet_width = TILE_WIDTH * columns
    sheet_height = TILE_HEIGHT * rows_count
    canvas = bytearray(sheet_width * sheet_height * BYTES_PER_PIXEL)
    for index, path in enumerate(paths):
        width, height, rows = read_png(path)
        origin_x = (index % columns) * TILE_WIDTH
        origin_y = (index // columns) * TILE_HEIGHT
        for tile_y in range(TILE_HEIGHT):
            source = rows[tile_y * height // TILE_HEIGHT]
            for tile_x in range(TILE_WIDTH):
                source_x = tile_x * width // TILE_WIDTH * BYTES_PER_PIXEL
                target = ((origin_y + tile_y) * sheet_width + origin_x + tile_x) * BYTES_PER_PIXEL
                canvas[target : target + BYTES_PER_PIXEL] = source[
                    source_x : source_x + BYTES_PER_PIXEL
                ]
        top_edge = (origin_y * sheet_width + origin_x) * BYTES_PER_PIXEL
        canvas[top_edge : top_edge + TILE_WIDTH * BYTES_PER_PIXEL] = SEPARATOR_RGB * TILE_WIDTH
    return write_png(out, sheet_width, sheet_height, bytes(canvas))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tile screenshots into one PNG.")
    parser.add_argument("out")
    parser.add_argument("shots", nargs="+")
    args = parser.parse_args()
    print(contact_sheet(args.shots, args.out))
