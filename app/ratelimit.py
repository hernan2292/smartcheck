"""Rate limiting con ventana deslizante, en memoria.

Sin Redis a proposito: la app corre en un solo proceso uvicorn, asi que un dict
con un lock alcanza y no suma infraestructura. Si algun dia se escala a varios
procesos, cada uno tendria su propio contador y el limite efectivo se
multiplicaria por la cantidad de workers — ahi si hace falta un store compartido.

El limite que importa es el de POST /api/audits*: cada audit arranca un Slither,
que en esta maquina (458MB, 1 vCPU) es lo unico capaz de tumbarla.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindow:
    """Permite `limit` eventos por `window` segundos para cada clave."""

    def __init__(self, limit: int, window: int, name: str = ""):
        self.limit = limit
        self.window = window
        self.name = name
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def hit(self, key: str) -> float | None:
        """Registra un intento.

        Devuelve None si esta permitido, o los segundos que faltan para que se
        libere el cupo (para el header Retry-After).
        """
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            self._prune(now)
            timestamps = self._hits[key]
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                # El cupo se libera cuando el evento mas viejo sale de la ventana
                return max(1.0, round(self.window - (now - timestamps[0]), 1))
            timestamps.append(now)
            return None

    def _prune(self, now: float) -> None:
        """Saca las claves sin eventos vigentes. Sin esto el dict crece sin techo."""
        if now - self._last_prune < self.window:
            return
        self._last_prune = now
        cutoff = now - self.window
        stale = [k for k, ts in self._hits.items() if not ts or ts[-1] < cutoff]
        for key in stale:
            del self._hits[key]

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"limit": self.limit, "window_seconds": self.window, "tracked_keys": len(self._hits)}
