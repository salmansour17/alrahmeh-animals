"""Animal photos: the only module that uses Pillow.

Every upload is decoded and re-encoded as WebP. That throws away everything the
original file carried besides the picture itself, including the GPS position a
phone writes into each photo, which here could reveal a foster family's home.
Re-encoding also means the image served to visitors was produced by this code,
never passed through as uploaded. Storing the result is not this module's job:
it goes to the database through repository.SqlPhotoStore.
"""

from __future__ import annotations

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from animals.service import InvalidPhoto, UnsupportedPhotoType

# A phone photo is commonly 3-8 MB. The file size is not what protects memory
# (MAX_DECODED_PIXELS below does that), and every upload is shrunk and
# re-encoded, so the stored copy stays small whatever arrives.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_SIDE = 1600
WEBP_QUALITY = 82
# A small file can still decode into an enormous image (a "decompression
# bomb"). Anything above this many pixels is refused before it is decoded:
# 25 megapixels is more than any phone photo of an animal needs.
MAX_DECODED_PIXELS = 25_000_000
# Pillow reads this limit before decoding any image. Its own default is about
# 89 million pixels, which would let a much bigger bomb through.
Image.MAX_IMAGE_PIXELS = MAX_DECODED_PIXELS

# The upload's declared type, and the format Pillow must find when it decodes.
ACCEPTED_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def prepare_photo(data: bytes, content_type: str) -> bytes:
    """Check an upload and return it as a clean, size-capped WebP."""
    expected_format = ACCEPTED_TYPES.get(content_type)
    if expected_format is None:
        raise UnsupportedPhotoType(content_type)

    with warnings.catch_warnings():
        # Pillow only warns between the limit and twice the limit; treat the
        # warning as the refusal it should be.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(data)) as probe:
                probe.verify()  # structural check; the image is unusable after it
            with Image.open(BytesIO(data)) as image:
                if image.format != expected_format:
                    raise InvalidPhoto(f"the file is not a {content_type} image")
                # Apply the camera's rotation before the metadata holding it is
                # discarded, so photos are not left on their side.
                image = ImageOps.exif_transpose(image)
                image = image.convert("RGBA" if _has_transparency(image) else "RGB")
                image.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE))
                out = BytesIO()
                # exif=b"" makes sure no metadata is written, whatever the
                # opened image still carries in memory.
                image.save(out, format="WEBP", quality=WEBP_QUALITY, exif=b"")
        except InvalidPhoto:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise InvalidPhoto("the image is too large to process") from None
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise InvalidPhoto("the file is not a readable image") from None
    return out.getvalue()


def _has_transparency(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA") or "transparency" in image.info
