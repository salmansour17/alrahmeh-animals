"""Animal photos: the only module that uses Pillow or touches the photos folder.

Every upload is decoded and re-encoded as WebP. That throws away everything the
original file carried besides the picture itself, including the GPS position a
phone writes into each photo, which here could reveal a foster family's home.
Re-encoding also means the file served to visitors was produced by this code,
never passed through as uploaded.
"""

from __future__ import annotations

import os
import uuid
import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from domains.animals.service import InvalidPhoto, UnsupportedPhotoType

MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_SIDE = 1600
WEBP_QUALITY = 82
VERSION_STEP_NS = 1_000_000
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


class FileSystemPhotoStore:
    """Implements service.PhotoStore: one WebP file per animal, named by id."""

    def __init__(self, folder: Path) -> None:
        self._folder = Path(folder)
        # Created on boot, so a fresh DATA_DIR needs no manual step.
        self._folder.mkdir(parents=True, exist_ok=True)

    def save(self, animal_id: int, photo: bytes) -> None:
        """Replace an animal's photo atomically.

        The new file is written under a temporary name in the same folder and
        then renamed over the old one, which the operating system does in one
        step: a crash leaves either the old photo or the new one, never half a
        file.
        """
        target = self._path(animal_id)
        previous = self.version(animal_id)
        temporary = self._folder / f".{animal_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(photo)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        # The version is the file's modification time. Two saves within one
        # clock tick could share it, so make sure a new photo always moves on.
        # The step is a millisecond because filesystems round file times
        # (Windows to 100 ns), and a 1 ns bump would simply be rounded away.
        if previous is not None and self.version(animal_id) <= previous:
            bumped = previous + VERSION_STEP_NS
            os.utime(target, ns=(bumped, bumped))

    def load(self, animal_id: int) -> bytes | None:
        path = self._path(animal_id)
        return path.read_bytes() if path.is_file() else None

    def version(self, animal_id: int) -> int | None:
        try:
            return self._path(animal_id).stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _path(self, animal_id: int) -> Path:
        # The name comes from an integer id only, never from anything uploaded,
        # so no path traversal or filename trick can reach this.
        if not isinstance(animal_id, int) or isinstance(animal_id, bool) or animal_id < 1:
            raise ValueError("animal_id must be a positive integer")
        return self._folder / f"{animal_id}.webp"
