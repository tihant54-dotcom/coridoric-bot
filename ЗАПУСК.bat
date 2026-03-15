@echo off
chcp 65001 >nul
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   FONBET + MAXLINE  —  TG БОТА      ║
echo  ╚══════════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден!
    echo  Скачай: https://python.org
    pause
    exit /b
)

echo  Устанавливаем зависимости...
pip install -r requirements.txt -q

echo.
echo  Не забудь вставить токен в config.py!
echo  Запускаем бота...
echo.
python bot.py
pause
