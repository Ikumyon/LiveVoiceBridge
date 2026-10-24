from collections import OrderedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Signal
from PySide6.QtGui import QImageReader, QPixmap

from livevoicebridge.desktop.comments.rendering import clip_to_circle


class AvatarCache(QObject):
    changed = Signal(object)

    def __init__(self, mib: int, parent=None) -> None:
        super().__init__(parent)
        self._limit = mib * 1024 * 1024
        self._bytes = 0
        self._images: OrderedDict[str, tuple[QPixmap, int]] = OrderedDict()

    def contains(self, key: str) -> bool:
        return key in self._images

    def get(self, key: str) -> QPixmap | None:
        value = self._images.get(key)
        if value is None:
            return None
        self._images.move_to_end(key)
        return value[0]

    def set_limit(self, mib: int) -> None:
        self._limit = mib * 1024 * 1024
        changed = self._evict()
        if changed:
            self.changed.emit(changed)

    def _evict(self) -> tuple[str, ...]:
        changed = []
        while self._bytes > self._limit and self._images:
            key, (_, cost) = self._images.popitem(last=False)
            self._bytes -= cost
            changed.append(key)
        return tuple(changed)

    def receive(self, key: str, content: bytes, ratio: float) -> None:
        if not content or len(content) > 512 * 1024:
            return
        source = QBuffer()
        source.setData(QByteArray(content))
        source.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(source)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 4 * 1024 * 1024:
            source.close()
            return
        pixels = max(36, min(144, round(36 * ratio)))
        reader.setScaledSize(QSize(pixels, pixels))
        image = reader.read()
        source.close()
        if image.isNull():
            return
        pixmap = clip_to_circle(QPixmap.fromImage(image), pixels)
        pixmap.setDevicePixelRatio(ratio)
        cost = pixmap.width() * pixmap.height() * max(pixmap.depth() // 8, 1)
        previous = self._images.pop(key, None)
        if previous is not None:
            self._bytes -= previous[1]
        self._images[key] = (pixmap, cost)
        self._bytes += cost
        self.changed.emit((*self._evict(), key))
