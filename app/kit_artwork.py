"""Portable artwork and logo assets for sample kits."""
from functools import lru_cache

KIT_ARTWORK = {'artwork': '.artwork.png', 'logo': '.logo.png'}
MAX_IMAGE_BYTES = 2 * 1024**2


def decode_png(stream):
    from PIL import Image
    try:
        with Image.open(stream, formats=['PNG']) as image:
            if max(image.size) > 2048:
                raise ValueError('Kit artwork exceeds 2048 pixels.')
            return image.convert('RGBA')
    except Image.DecompressionBombError as error:
        raise ValueError('Kit artwork exceeds 2048 pixels.') from error


@lru_cache(maxsize=32)
def _thumbnail(path, modified, size):
    with path.open('rb') as stream:
        image = decode_png(stream)
    bounds = image.getchannel('A').getbbox()
    if bounds is None:
        return None
    image = image.crop(bounds)
    scale = min(1, size[0] / image.width, size[1] / image.height)
    from PIL import Image
    return image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.LANCZOS)


def thumbnail(path, size):
    try:
        if path.is_symlink() or not path.is_file():
            return None
        info = path.stat()
        if info.st_size <= MAX_IMAGE_BYTES:
            return _thumbnail(path, info.st_mtime_ns, size)
    except (OSError, ValueError):
        pass
    return None


@lru_cache(maxsize=32)
def expansion_artwork(folder,modified):
    """Use the first imported copy of the expansion's shared cover."""
    for kit in sorted(folder.iterdir()):
        if kit.is_symlink() or not (kit/'Set.json').is_file():
            continue
        if any((kit/leaf).is_file() for leaf in KIT_ARTWORK.values()):
            return kit
    return None
