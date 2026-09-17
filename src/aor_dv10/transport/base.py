
from __future__ import annotations

import abc


class TransportError(RuntimeError):
    pass


class TransportTimeout(TransportError):
    pass


class Transport(abc.ABC):

    @abc.abstractmethod
    def open(self) -> None:
        pass

    @abc.abstractmethod
    def close(self) -> None:
        pass

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        ...

    @abc.abstractmethod
    def write_line(self, data: bytes) -> None:
        pass

    @abc.abstractmethod
    def read_line(self, timeout: float) -> bytes | None:
        pass

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
