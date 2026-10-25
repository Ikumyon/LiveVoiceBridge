from threading import Condition, Event


class AudioBudget:
    """Reserve worst-case PCM before synthesis, then retain only the actual size."""

    def __init__(self, limit: int, cancelled: Event) -> None:
        self._condition = Condition()
        self._limit = limit
        self._held = 0
        self._cancelled = cancelled

    def set_limit(self, limit: int) -> None:
        with self._condition:
            self._limit = limit
            self._condition.notify_all()

    def reserve(self) -> int:
        with self._condition:
            while not self._cancelled.is_set():
                capacity = min(self._limit // 2, 16 * 1024 * 1024)
                if self._held + capacity <= self._limit:
                    self._held += capacity
                    return capacity
                self._condition.wait(0.05)
        return 0

    def release(self, count: int) -> None:
        with self._condition:
            if not 0 <= count <= self._held:
                raise ValueError("音声容量の解放数が不正です。")
            self._held -= count
            self._condition.notify_all()

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()
