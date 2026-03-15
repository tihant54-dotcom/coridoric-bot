"""
bot.py — Telegram парсер коридоров Fonbet.by + Maxline.by
Запуск: python bot.py
"""

import asyncio
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
import aiohttp

import config
from parser import fetch_fonbet, fetch_maxline, match_and_build, SPORT_IDS

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
SPORTS = {
    "football":   "⚽ Футбол",
    "basketball": "🏀 Баскетбол",
    "hockey":     "🏒 Хоккей",
    "tennis":     "🎾 Теннис",
    "volleyball": "🏐 Волейбол",
}

AUTO_USERS: dict[int, dict] = {}   # uid → {sport, min_width, interval}

# ─────────────────────────────────────────────────────────
#  ПАРСИНГ
# ─────────────────────────────────────────────────────────

async def scan_sport(sport: str) -> list[dict]:
    """Получает реальные данные и возвращает список событий с коридорами."""
    async with aiohttp.ClientSession() as session:
        fn_task = fetch_fonbet(session, sport)
        ml_task = fetch_maxline(session, sport)
        fn_lines, ml_lines = await asyncio.gather(fn_task, ml_task)
    return match_and_build(fn_lines, ml_lines), len(fn_lines), len(ml_lines)


# ─────────────────────────────────────────────────────────
#  ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ─────────────────────────────────────────────────────────

def fmt_scan_result(sport: str, events: list, fn_cnt: int, ml_cnt: int, min_w: float = 0.0) -> str:
    sport_label = SPORTS.get(sport, sport)
    lines = [f"📡 <b>{sport_label}</b>\n"]
    lines.append(f"<code>Fonbet: {fn_cnt} линий · Maxline: {ml_cnt} линий</code>\n")

    filtered = [ev for ev in events if any(c["width"] >= min_w for c in ev.get("cors", []))]

    if not filtered:
        lines.append("⬜ <i>Коридоров не найдено</i>")
        return "\n".join(lines)

    lines.append(f"✅ Найдено коридоров: <b>{len(filtered)}</b>\n")

    for ev in filtered:
        cors = [c for c in ev.get("cors", []) if c["width"] >= min_w]
        if not cors:
            continue
        best = cors[0]
        roi_s = f"+{best['roi']}%" if best["roi"] > 0 else f"{best['roi']}%"

        lines.append(
            f"🔹 <b>{ev['home']} — {ev['away']}</b>\n"
            f"   {ev['league']}  {ev['time']}"
            + (f"  🔴 LIVE" if ev.get("is_live") else "") + "\n"
            f"   🔴 Fonbet  Тотал <code>{ev['fn_total']:.2f}</code>  "
            f"Б <code>{ev['fn_over']:.2f}</code>  М <code>{ev['fn_under']:.2f}</code>\n"
            f"   🔵 Maxline Тотал <code>{ev['ml_total']:.2f}</code>  "
            f"Б <code>{ev['ml_over']:.2f}</code>  М <code>{ev['ml_under']:.2f}</code>\n"
        )

        lines.append(f"   ▸ <b>Коридор:</b>")
        for cor in cors[:2]:
            roi_str = f"+{cor['roi']}%" if cor["roi"] > 0 else f"{cor['roi']}%"
            o_emoji = "🔴" if cor["oBook"] == "fonbet" else "🔵"
            u_emoji = "🔴" if cor["uBook"] == "fonbet" else "🔵"
            lines.append(
                f"   {o_emoji} <b>{cor['oLabel']}</b> Б{cor['oLine']:.2f} @ {cor['oOdds']:.2f}\n"
                f"   {u_emoji} <b>{cor['uLabel']}</b> М{cor['uLine']:.2f} @ {cor['uOdds']:.2f}\n"
                f"   <code>Ширина: {cor['width']:.2f}  ROI: {roi_str}  "
                f"Ставки: {cor['s1']}/{cor['s2']}</code>"
            )
        lines.append("")

    return "\n".join(lines)


def fmt_event_detail(ev: dict) -> str:
    cors = ev.get("cors", [])
    lines = [
        f"<b>{ev['home']} — {ev['away']}</b>",
        f"{ev['league']}  {ev['time']}" + ("  🔴 LIVE" if ev.get("is_live") else ""),
        "",
        "📊 <b>Линии тоталов:</b>",
        f"🔴 Fonbet   Тотал <code>{ev['fn_total']:.2f}</code>  Б <code>{ev['fn_over']:.2f}</code>  М <code>{ev['fn_under']:.2f}</code>",
        f"🔵 Maxline  Тотал <code>{ev['ml_total']:.2f}</code>  Б <code>{ev['ml_over']:.2f}</code>  М <code>{ev['ml_under']:.2f}</code>",
        "",
    ]

    if cors:
        lines.append(f"🟩 <b>Коридоров: {len(cors)}</b>")
        for cor in cors:
            roi_s = f"+{cor['roi']}%" if cor["roi"] > 0 else f"{cor['roi']}%"
            o_e = "🔴" if cor["oBook"] == "fonbet" else "🔵"
            u_e = "🔴" if cor["uBook"] == "fonbet" else "🔵"
            lines += [
                "",
                f"  {o_e} <b>{cor['oLabel']}</b>  Б {cor['oLine']:.2f} @ {cor['oOdds']:.2f}",
                f"  {u_e} <b>{cor['uLabel']}</b>  М {cor['uLine']:.2f} @ {cor['uOdds']:.2f}",
                f"  <code>Ш: {cor['width']:.2f}  ROI: {roi_s}  {cor['s1']}/{cor['s2']} на 100 BYN</code>",
            ]
        lines += [
            "",
            f"✦ Ставишь <b>Б {cors[0]['oLine']:.2f}</b> на {cors[0]['oLabel']} "
            f"и <b>М {cors[0]['uLine']:.2f}</b> на {cors[0]['uLabel']}.",
            f"Если итог в коридоре "
            f"<b>{min(cors[0]['oLine'], cors[0]['uLine']):.2f}–"
            f"{max(cors[0]['oLine'], cors[0]['uLine']):.2f}</b> — оба купона выигрывают.",
        ]
    else:
        lines.append("⬜ <i>Коридоров нет</i>")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚽ Футбол",    callback_data="scan:football"),
            InlineKeyboardButton("🏀 Баскетбол", callback_data="scan:basketball"),
        ],
        [
            InlineKeyboardButton("🏒 Хоккей",    callback_data="scan:hockey"),
            InlineKeyboardButton("🎾 Теннис",    callback_data="scan:tennis"),
            InlineKeyboardButton("🏐 Волейбол",  callback_data="scan:volleyball"),
        ],
        [
            InlineKeyboardButton("🔍 Всё сразу", callback_data="scan:all"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки",         callback_data="settings"),
            InlineKeyboardButton("📡 Авто-уведомления",  callback_data="auto_menu"),
        ],
    ])


def kb_settings(user_data: dict) -> InlineKeyboardMarkup:
    cur = user_data.get("min_width", 0.0)
    rows = []
    for w in [0.0, 0.25, 0.5, 1.0, 1.5, 2.0]:
        check = "✅" if cur == w else "☑️"
        rows.append([InlineKeyboardButton(
            f"{check} Ширина ≥ {w}",
            callback_data=f"set_width:{w}"
        )])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def kb_auto(user_data: dict) -> InlineKeyboardMarkup:
    uid_auto = user_data.get("auto_active", False)
    interval = user_data.get("interval", 300)
    sp = user_data.get("auto_sport", "football")

    rows = [
        [InlineKeyboardButton(
            f"{'🟢' if uid_auto else '🔴'} Авто-уведомления {'ВКЛ' if uid_auto else 'ВЫКЛ'}",
            callback_data="auto_toggle"
        )],
    ]
    # Выбор спорта
    sport_row = []
    for sid, slabel in SPORTS.items():
        check = "✅ " if sid == sp else ""
        sport_row.append(InlineKeyboardButton(f"{check}{slabel}", callback_data=f"auto_sport:{sid}"))
        if len(sport_row) == 2:
            rows.append(sport_row)
            sport_row = []
    if sport_row:
        rows.append(sport_row)

    # Интервал
    rows.append([
        InlineKeyboardButton(f"{'✅ ' if interval==300  else ''}5 мин",  callback_data="auto_int:300"),
        InlineKeyboardButton(f"{'✅ ' if interval==600  else ''}10 мин", callback_data="auto_int:600"),
        InlineKeyboardButton(f"{'✅ ' if interval==1800 else ''}30 мин", callback_data="auto_int:1800"),
    ])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Обновить",  callback_data="refresh_last"),
        InlineKeyboardButton("🏠 Меню",      callback_data="main"),
    ]])


# ─────────────────────────────────────────────────────────
#  HANDLERS
# ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 <b>Парсер коридоров</b>\n\n"
        "🔴 <b>Fonbet.by</b>  +  🔵 <b>Maxline.by</b>\n\n"
        "Ищу расхождения тоталов между двумя букмекерами.\n"
        "Когда тотал у одного бука выше чем у другого — "
        "это коридор: ставишь Б у одного и М у другого, "
        "и если итог попадает между — оба купона выигрывают.\n\n"
        "Выбери вид спорта:"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/scan — сканировать текущий спорт\n"
        "/football /basketball /hockey /tennis /volleyball\n"
        "/auto — включить авто-уведомления\n"
        "/help — справка\n\n"
        "<b>Коридор:</b>\n"
        "Fonbet Тотал 220.5 → ставишь Больше 220.5\n"
        "Maxline Тотал 223.0 → ставишь Меньше 223.0\n"
        "Ширина коридора = 223.0 − 220.5 = 2.5\n"
        "Если итог 221–222 — оба купона выигрывают ✅"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def _do_scan(update, ctx, sport, is_callback=False):
    """Универсальная функция сканирования."""
    edit = is_callback
    msg_func = update.message.reply_text if not edit else update.callback_query.edit_message_text

    await msg_func("⏳ Загружаю котировки...", parse_mode=ParseMode.HTML)

    try:
        events, fn_cnt, ml_cnt = await scan_sport(sport)
        min_w = ctx.user_data.get("min_width", 0.0)
        text = fmt_scan_result(sport, events, fn_cnt, ml_cnt, min_w)
        ctx.user_data["last_sport"] = sport
        ctx.user_data["last_events"] = events
        ctx.user_data["last_fn_cnt"] = fn_cnt
        ctx.user_data["last_ml_cnt"] = ml_cnt

    except Exception as e:
        text = f"❌ Ошибка парсинга: <code>{e}</code>"

    try:
        await msg_func(text, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    except Exception:
        # Если сообщение слишком длинное — обрезаем
        await msg_func(text[:4000] + "...", parse_mode=ParseMode.HTML, reply_markup=kb_back())


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sport = ctx.user_data.get("last_sport", "football")
    await _do_scan(update, ctx, sport)


async def cmd_sport(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sport = update.message.text.lstrip("/")
    if sport in SPORTS:
        await _do_scan(update, ctx, sport)


async def cmd_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if uid in AUTO_USERS:
        AUTO_USERS.pop(uid, None)
        ctx.user_data["auto_active"] = False
        await update.message.reply_text("🔕 Авто-уведомления выключены.", parse_mode=ParseMode.HTML)
    else:
        sport = ctx.user_data.get("auto_sport", "football")
        interval = ctx.user_data.get("interval", 300)
        AUTO_USERS[uid] = {"sport": sport, "interval": interval}
        ctx.user_data["auto_active"] = True
        await update.message.reply_text(
            f"🔔 Авто-уведомления включены!\n"
            f"Спорт: {SPORTS[sport]}\n"
            f"Каждые {interval//60} минут.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main()
        )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "main":
        await q.edit_message_text(
            "🏠 <b>Главное меню</b>\nВыбери вид спорта:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main()
        )

    elif d.startswith("scan:"):
        sport = d.split(":")[1]
        if sport == "all":
            await q.edit_message_text("⏳ Сканирую все спорты...", parse_mode=ParseMode.HTML)
            min_w = ctx.user_data.get("min_width", 0.0)
            all_text = []
            for sp in SPORTS:
                try:
                    events, fn_cnt, ml_cnt = await scan_sport(sp)
                    with_cors = [e for e in events if any(c["width"] >= min_w for c in e.get("cors", []))]
                    if with_cors:
                        best = max(
                            [c for e in with_cors for c in e["cors"] if c["width"] >= min_w],
                            key=lambda x: x["width"]
                        )
                        all_text.append(
                            f"{SPORTS[sp]}: {len(with_cors)} матчей с коридорами, "
                            f"лучший Ш <b>{best['width']:.2f}</b>"
                        )
                    else:
                        all_text.append(f"{SPORTS[sp]}: ⬜ нет коридоров")
                except Exception as e:
                    all_text.append(f"{SPORTS[sp]}: ❌ {str(e)[:50]}")

            text = "📊 <b>Сводка по всем спортам:</b>\n\n" + "\n".join(all_text)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_back())
        else:
            await _do_scan(update, ctx, sport, is_callback=True)

    elif d == "refresh_last":
        sport = ctx.user_data.get("last_sport", "football")
        await _do_scan(update, ctx, sport, is_callback=True)

    elif d == "settings":
        await q.edit_message_text(
            "⚙️ <b>Настройки</b>\nМинимальная ширина коридора:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_settings(ctx.user_data)
        )

    elif d.startswith("set_width:"):
        w = float(d.split(":")[1])
        ctx.user_data["min_width"] = w
        await q.edit_message_text(
            f"✅ Минимальная ширина: <b>{w}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_settings(ctx.user_data)
        )

    elif d == "auto_menu":
        await q.edit_message_text(
            "📡 <b>Авто-уведомления</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_auto(ctx.user_data)
        )

    elif d == "auto_toggle":
        uid = update.effective_chat.id
        if uid in AUTO_USERS:
            AUTO_USERS.pop(uid)
            ctx.user_data["auto_active"] = False
        else:
            sport = ctx.user_data.get("auto_sport", "football")
            interval = ctx.user_data.get("interval", 300)
            AUTO_USERS[uid] = {"sport": sport, "interval": interval}
            ctx.user_data["auto_active"] = True
        await q.edit_message_text(
            "📡 <b>Авто-уведомления</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_auto(ctx.user_data)
        )

    elif d.startswith("auto_sport:"):
        sp = d.split(":")[1]
        ctx.user_data["auto_sport"] = sp
        uid = update.effective_chat.id
        if uid in AUTO_USERS:
            AUTO_USERS[uid]["sport"] = sp
        await q.edit_message_text(
            "📡 <b>Авто-уведомления</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_auto(ctx.user_data)
        )

    elif d.startswith("auto_int:"):
        interval = int(d.split(":")[1])
        ctx.user_data["interval"] = interval
        uid = update.effective_chat.id
        if uid in AUTO_USERS:
            AUTO_USERS[uid]["interval"] = interval
        await q.edit_message_text(
            "📡 <b>Авто-уведомления</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_auto(ctx.user_data)
        )


# ─────────────────────────────────────────────────────────
#  АВТО-УВЕДОМЛЕНИЯ (Job)
# ─────────────────────────────────────────────────────────

_last_sent: dict[int, float] = {}

async def auto_notify_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Запускается каждую минуту, рассылает по расписанию."""
    if not AUTO_USERS:
        return

    now = time.time()
    for uid, settings in list(AUTO_USERS.items()):
        interval = settings.get("interval", 300)
        last = _last_sent.get(uid, 0)
        if now - last < interval:
            continue

        sport = settings.get("sport", "football")
        try:
            events, fn_cnt, ml_cnt = await scan_sport(sport)
            cors_events = [e for e in events if e.get("cors")]
            if not cors_events:
                continue

            min_w = 0.0
            text = (
                f"🔔 <b>Новые коридоры!</b>  {SPORTS[sport]}\n\n"
            ) + fmt_scan_result(sport, events, fn_cnt, ml_cnt, min_w)

            await ctx.bot.send_message(
                chat_id=uid,
                text=text[:4000],
                parse_mode=ParseMode.HTML,
                reply_markup=kb_main()
            )
            _last_sent[uid] = now

        except Exception as e:
            log.warning(f"Auto notify error for {uid}: {e}")
            AUTO_USERS.pop(uid, None)


# ─────────────────────────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("scan",       cmd_scan))
    app.add_handler(CommandHandler("auto",       cmd_auto))
    app.add_handler(CommandHandler("football",   cmd_sport))
    app.add_handler(CommandHandler("basketball", cmd_sport))
    app.add_handler(CommandHandler("hockey",     cmd_sport))
    app.add_handler(CommandHandler("tennis",     cmd_sport))
    app.add_handler(CommandHandler("volleyball", cmd_sport))
    app.add_handler(CallbackQueryHandler(on_callback))

    # Проверяем каждую минуту
    app.job_queue.run_repeating(auto_notify_job, interval=60, first=10)

    log.info("Бот запущен ✅")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
