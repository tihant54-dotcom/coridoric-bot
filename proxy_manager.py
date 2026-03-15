"""
proxy_manager.py — менеджер прокси с авто-проверкой и ротацией
"""

import asyncio
import logging
import time
import random
from typing import Optional
import aiohttp

from proxy_list import PROXY_LIST, PROXY_CHECK_TIMEOUT, PROXY_CHECK_URL, ROTATE_PROXIES, FALLBACK_TO_DIRECT

log = logging.getLogger(__name__)


class ProxyManager:
    """
    Управляет списком прокси:
    - Проверяет работоспособность при старте
    - Ротирует при ошибках
    - Автоматически исключает нерабочие
    - Fallback на прямое соединение
    """

    def __init__(self):
        self._all: list[str] = list(PROXY_LIST)
        self._working: list[str] = []
        self._dead: set[str] = set()
        self._dead_until: dict[str, float] = {}   # прокси → время бана
        self._current_idx: int = 0
        self._checked: bool = False
        self._lock = asyncio.Lock()

    async def check_all(self) -> int:
        """Проверяет все прокси, возвращает кол-во рабочих."""
        if not self._all:
            log.info("[Proxy] Список прокси пуст — используем прямое соединение")
            self._checked = True
            return 0

        log.info(f"[Proxy] Проверяем {len(self._all)} прокси...")
        tasks = [self._check_one(p) for p in self._all]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        self._working = [
            p for p, ok in zip(self._all, results) if ok is True
        ]
        self._checked = True
        log.info(f"[Proxy] Рабочих: {len(self._working)}/{len(self._all)}")
        return len(self._working)

    async def _check_one(self, proxy: str) -> bool:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    PROXY_CHECK_URL,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=PROXY_CHECK_TIMEOUT),
                    ssl=False,
                ) as r:
                    ok = r.status in (200, 403, 429)   # 403/429 тоже значит прокси работает
                    if ok:
                        log.info(f"[Proxy] ✅ {proxy[:40]}")
                    else:
                        log.warning(f"[Proxy] ❌ {proxy[:40]} status={r.status}")
                    return ok
        except Exception as e:
            log.warning(f"[Proxy] ❌ {proxy[:40]} — {type(e).__name__}")
            return False

    def get_proxy(self) -> Optional[str]:
        """Возвращает следующий рабочий прокси или None."""
        now = time.time()

        # Размораживаем истёкшие баны
        revive = [p for p, t in self._dead_until.items() if t < now]
        for p in revive:
            del self._dead_until[p]
            self._dead.discard(p)
            if p in self._all and p not in self._working:
                self._working.append(p)
                log.info(f"[Proxy] Размораживаем {p[:40]}")

        active = [p for p in self._working if p not in self._dead]
        if not active:
            if FALLBACK_TO_DIRECT:
                return None   # None = прямое соединение
            raise RuntimeError("Нет доступных прокси")

        if ROTATE_PROXIES:
            self._current_idx = (self._current_idx + 1) % len(active)
            return active[self._current_idx]
        else:
            return active[0]

    def mark_dead(self, proxy: str, ban_seconds: int = 120):
        """Помечает прокси как нерабочий на ban_seconds секунд."""
        if proxy:
            self._dead.add(proxy)
            self._dead_until[proxy] = time.time() + ban_seconds
            log.warning(f"[Proxy] Бан {proxy[:40]} на {ban_seconds}с")

    def status(self) -> dict:
        now = time.time()
        active = [p for p in self._working if p not in self._dead]
        return {
            "total":   len(self._all),
            "working": len(self._working),
            "active":  len(active),
            "dead":    len(self._dead),
        }


# Глобальный экземпляр
proxy_mgr = ProxyManager()


async def init_proxies():
    """Вызвать при старте бота."""
    return await proxy_mgr.check_all()


def get_session_kwargs() -> dict:
    """Возвращает kwargs для aiohttp.ClientSession с прокси."""
    proxy = proxy_mgr.get_proxy()
    if proxy:
        return {"proxy": proxy}
    return {}


async def fetch_with_proxy(url: str, headers: dict, timeout: int = 12) -> dict:
    """
    Делает GET-запрос с автоматической ротацией прокси.
    При ошибке прокси — пробует следующий.
    """
    attempts = max(1, len(proxy_mgr._working) + 1)

    for attempt in range(attempts):
        proxy = proxy_mgr.get_proxy()
        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=timeout), "ssl": False}
                if proxy:
                    kwargs["proxy"] = proxy

                async with session.get(url, **kwargs) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    elif r.status == 429:
                        # Rate limit — пробуем другой прокси
                        if proxy:
                            proxy_mgr.mark_dead(proxy, ban_seconds=60)
                        continue
                    elif r.status in (403, 451):
                        # Заблокирован с этого IP — меняем прокси
                        if proxy:
                            proxy_mgr.mark_dead(proxy, ban_seconds=300)
                        continue
                    else:
                        return {}

        except aiohttp.ClientProxyConnectionError:
            if proxy:
                proxy_mgr.mark_dead(proxy, ban_seconds=180)
        except asyncio.TimeoutError:
            if proxy:
                proxy_mgr.mark_dead(proxy, ban_seconds=60)
        except Exception as e:
            log.warning(f"[fetch] {url[-40:]} через {str(proxy or 'direct')[:30]}: {e}")
            if proxy:
                proxy_mgr.mark_dead(proxy, ban_seconds=60)

    return {}
