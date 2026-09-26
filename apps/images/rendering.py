"""Pillow drawing for badges, game icons and avatars: placeholders, locked badges, identicons."""

import hashlib
import io

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

# RA's conventional sizes: 64×64 badges, 96×96 game icons.
BADGE_SIZE_PX = 64
GAME_ICON_SIZE_PX = 96

# Design tokens from tailwind.config.js, named in the trailing comments.
PLACEHOLDER_FILL_COLOR = "#1e2531"  # `surface2`
PLACEHOLDER_FRAME_COLOR = "#3b4657"  # `line2`
IDENTICON_BACKGROUND_COLOR = "#171c25"  # `surface`
IDENTICON_COLORS = (
    "#34dcc4",  # `brand`
    "#b09cff",  # `brand2`
    "#f2b84b",  # `gold`
    "#5cc48c",  # `state-beaten`
    "#e0552f",  # `state-hardcore`
    "#7e93b1",  # `state-softcore`
    "#d8922f",  # `state-progress`
)

PLACEHOLDER_FRAME_PX = 2
# Below 1 flattens the grey, like RA's locked badges.
LOCKED_CONTRAST_FACTOR = 0.8

# A 5×5 grid of 20px cells with a 14px margin on each side fills the 128px avatar.
AVATAR_SIZE_PX = 128
IDENTICON_GRID_CELLS = 5
IDENTICON_CELL_PX = 20
IDENTICON_MARGIN_PX = 14
# The first three columns are drawn from the hash; the last two mirror them.
IDENTICON_DRAWN_COLUMNS = 3


def encode_png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def placeholder_image(size):
    """A neutral framed tile, served while no art has been uploaded."""
    image = Image.new("RGBA", (size, size), PLACEHOLDER_FILL_COLOR)
    ImageDraw.Draw(image).rectangle(
        (0, 0, size - 1, size - 1), outline=PLACEHOLDER_FRAME_COLOR, width=PLACEHOLDER_FRAME_PX
    )
    return image


def uploaded_image(field_file, size):
    """The uploaded image as a `size`×`size` RGBA square, centre-cropped when not square."""
    with field_file.open("rb"), Image.open(field_file) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    return ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)


def locked_image(image):
    """The grayscale, lower-contrast variant shown while an achievement is locked."""
    grey = ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(LOCKED_CONTRAST_FACTOR)
    return Image.merge("RGBA", (grey, grey, grey, image.getchannel("A")))


def _identicon_cell_box(row, column):
    left = IDENTICON_MARGIN_PX + column * IDENTICON_CELL_PX
    top = IDENTICON_MARGIN_PX + row * IDENTICON_CELL_PX
    return (left, top, left + IDENTICON_CELL_PX - 1, top + IDENTICON_CELL_PX - 1)


def identicon_png(username):
    """A symmetric 5×5 identicon, the same for a username on every call."""
    digest = hashlib.md5(username.encode(), usedforsecurity=False).digest()
    color = IDENTICON_COLORS[digest[-1] % len(IDENTICON_COLORS)]
    filled = [
        (row, column)
        for row in range(IDENTICON_GRID_CELLS)
        for column in range(IDENTICON_DRAWN_COLUMNS)
        if digest[row * IDENTICON_DRAWN_COLUMNS + column] & 1
    ]
    image = Image.new("RGB", (AVATAR_SIZE_PX, AVATAR_SIZE_PX), IDENTICON_BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    for row, column in filled:
        mirrored_column = IDENTICON_GRID_CELLS - 1 - column
        draw.rectangle(_identicon_cell_box(row, column), fill=color)
        draw.rectangle(_identicon_cell_box(row, mirrored_column), fill=color)
    return encode_png(image)
