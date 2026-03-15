"""
proxy_list.py — список RU/BY прокси для обхода блокировок Fonbet.by и Maxline.by

Форматы поддерживаемых прокси:
  http://ip:port
  http://user:pass@ip:port
  socks5://ip:port
  socks5://user:pass@ip:port

Источники БЕСПЛАТНЫХ прокси (RU/BY):
  https://proxyscrape.com/free-proxy-list  → фильтр Country=RU
  https://hidemy.name/ru/proxy-list/?country=RU
  https://free-proxy-list.net/ → фильтр Country=Russia

Источники ПЛАТНЫХ стабильных прокси (рекомендуется):
  proxys.io          — RU прокси от 150 руб/мес
  proxy6.net         — RU прокси от 99 руб/мес  
  froxy.com          — RU/BY датацентры
"""

# ─── СПИСОК ПРОКСИ ────────────────────────────────────────
# Добавляй сюда свои прокси. Бот будет перебирать их по порядку.
# Если прокси не работает — переходит к следующему.
# Если все не работают — использует прямое соединение.

PROXY_LIST = [
    # Пример формата (замени на реальные):
    # "http://123.45.67.89:3128",
    # "http://login:password@123.45.67.89:3128",
    # "socks5://123.45.67.89:1080",
]

# ─── НАСТРОЙКИ ────────────────────────────────────────────

# Таймаут проверки прокси (секунды)
PROXY_CHECK_TIMEOUT = 8

# URL для проверки работоспособности прокси
PROXY_CHECK_URL = "https://fonbet.by/api/v1/events/getSportEvents/1?locale=ru"

# Если True — при каждом запросе проверяет прокси и ротирует
ROTATE_PROXIES = True

# Использовать прямое соединение если все прокси недоступны
FALLBACK_TO_DIRECT = True
