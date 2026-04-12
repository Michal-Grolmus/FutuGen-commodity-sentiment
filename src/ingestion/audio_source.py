from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.models import AudioChunk


class AudioSource(ABC):
    @abstractmethod
    def chunks(self) -> AsyncIterator[AudioChunk]:
        """Yield audio chunks from the source."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
