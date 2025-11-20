import os 
import requests 
import pandas as pd
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import xlsxwriter

# ==========================
#  HELPERS
# ==========================
BASE = "https://api.clashofclans.com/v1"

def get_clan_tag():
    """Читает тег клана из переменной окружения."""
    tag = os.environ.get("CLAN_TAG") 
    if not tag:
         # Использование значения по умолчанию (замените на свой тег, если хотите)
         return '#2LG8PVY8R' 
    return tag

def coc_get(url):
    """
    Выполняет GET-запрос к API Clash of Clans, используя ключ из окружения.
    """
    api_key = os.environ.get("COC_API_KEY") 
    
    if not api_key:
        print("Ошибка безопасности: COC_API_KEY не установлен в окружении.")
        return {}
        
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(BASE + url, headers=headers)
    
    if r.status_code == 200:
        return r.json()
    else:
        # Улучшенная обработка ошибок API
        print(f"API Error for {url}: Status {r.status_code}, Response: {r.text[:100]}...") 
        return {} 


# ==========================
#  DATA PROCESSORS
# ==========================

def get_cw_attacks():
    """Собирает атаки из текущей CW (если она идет)."""
    clan_tag = get_clan_tag() # 🔥 ИЗМЕНЕНО: Читаем тег из функции
    wars = coc_get(f"/clans/{clan_tag.replace('#','%23')}/currentwar") 
    data = {}
    
    # Обработка атак клана
    for member in wars.get("clan", {}).get("members", []):
        name = member.get("tag")
        
        # Получаем список звёзд
        stars = [attack.get("stars", 0) for attack in member.get("attacks", [])]
        
        if name not in data:
            data[name] = []
        data[name].extend(stars)
        
    return data

def get_cwl_attacks():
    """
    Собирает атаки из текущей CWL (если она идет). 
    Возвращает словарь с атаками и данные самой свежей войны.
    """
    clan_tag = get_clan_tag() # 🔥 ИЗМЕНЕНО: Читаем тег из функции
    cwl_group = coc_get(f"/clans/{clan_tag.replace('#','%23')}/currentwar/leaguegroup")
    data = {}
    most_recent_war_data = None 

    # ГЛАВНАЯ ПРОВЕРКА: Если API вернул 404, выходим.
    if not cwl_group or not cwl_group.get("rounds"):
        return data, most_recent_war_data
    
    # Проходим по всем раундам
    for round_data in cwl_group.get("rounds", []):
        for war_tag in round_data.get("warTags", []):
            if war_tag == "#0":
                continue
            
            war = coc_get(f"/clanwarleagues/wars/{war_tag.replace('#','%23')}")
            
            if war and war.get("attacks"):
                most_recent_war_data = war 
                
                # Собираем атаки из этой CWL-войны
                for attack in war["attacks"]:
                    name = attack["attackerTag"]
                    stars = attack.get("stars", 0)
                    if name not in data:
                        data[name] = []
                    data[name].append(stars)
                    
    return data, most_recent_war_data


def build_stats():
    """Строит итоговый DataFrame со всеми статистическими данными."""
    clan_tag = get_clan_tag() # 🔥 ИЗМЕНЕНО: Читаем тег из функции
    clan = coc_get(f"/clans/{clan_tag.replace('#','%23')}")
    
    if not clan.get("memberList"):
        return pd.DataFrame()
        
    # 1. Получаем данные об атаках CW и CWL
    wars = coc_get(f"/clans/{clan_tag.replace('#','%23')}/currentwar") 
    cw = get_cw_attacks()
    cwl_stats, cwl_war_data = get_cwl_attacks() 
    
    rows = []
    target_war = None
    
    # 2. Определение диапазона дат войны
    
    # Приоритет CWL: Если CWL-война найдена и содержит необходимые поля
    if cwl_war_data and cwl_war_data.get("state") and cwl_war_data.get("preparationStartTime"):
        target_war = cwl_war_data
    # Фоллбэк на CW: Если нет CWL, но есть обычная война и она содержит необходимые поля
    elif wars.get("state") in ["inWar", "warEnded", "preparation"] and wars.get("preparationStartTime"):
        target_war = wars
        
    # Значение по умолчанию: текущая дата
    WAR_DATE_RANGE = datetime.now().strftime("%d.%m.%Y") 
    
    if target_war:
        try:
            # Парсим даты начала подготовки и окончания войны
            prep_start_dt = datetime.strptime(target_war.get("preparationStartTime")[:10], '%Y-%m-%d')
            war_end_dt = datetime.strptime(target_war.get("endTime")[:10], '%Y-%m-%d')
            
            start_date_str = prep_start_dt.strftime('%d.%m.%Y') 
            end_date_str = war_end_dt.strftime('%d.%m.%Y')
            
            WAR_DATE_RANGE = f"{start_date_str} - {end_date_str}"
            
        except (TypeError, ValueError):
            print("Warning: Could not parse war dates from API.")
            pass # Оставляем дату по умолчанию

    # 3. Наполнение строк DataFrame
    for member in clan["memberList"]:
        member_tag = member["tag"]
        
        cw_stars = cw.get(member_tag, [])
        cwl_stars = cwl_stats.get(member_tag, [])
        
        # Данные CW
        cw_attack_1 = cw_stars[0] if len(cw_stars) > 0 else 0
        cw_attack_2 = cw_stars[1] if len(cw_stars) > 1 else 0
        
        # Данные CWL
        cwl_attack_1 = cwl_stars[0] if len(cwl_stars) > 0 else 0
        cwl_attack_2 = cwl_stars[1] if len(cwl_stars) > 1 else 0

        total_stars = cw_attack_1 + cw_attack_2 + cwl_attack_1 + cwl_attack_2
        total_attacks = len(cw_stars) + len(cwl_stars)
        
        average_stars = total_stars / total_attacks if total_attacks > 0 else 0
        
        rows.append({
            "Дата": WAR_DATE_RANGE,
            "Игрок": member["name"],
            "TH": member["townHallLevel"],
            "CW Атака 1": cw_attack_1,
            "CW Атака 2": cw_attack_2,
            "CWL Атака 1": cwl_attack_1,
            "CWL Атака 2": cwl_attack_2,
            "Средние звёзды": average_stars,
            "Всего атак": total_attacks,
        })

    df = pd.DataFrame(rows)
    return df


# ==========================
#  TELEGRAM HANDLERS
# ==========================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clan_tag_encoded = get_clan_tag().replace('#', '%23') # 🔥 ИЗМЕНЕНО
    file_path = "stats.xlsx"
    
    df = build_stats()

    if df.empty:
        await update.message.reply_text(
            "⚠️ Не удалось получить данные о клане или нет участников."
        )
        return

    # Проверяем статус войны для информационного сообщения
    war_status_data = coc_get(f"/clans/{clan_tag_encoded}/currentwar")
    current_state = war_status_data.get("state")
    
    if current_state == "preparation":
        await update.message.reply_text("⚠️ **Внимание!** Сейчас идет **День Подготовки**. Статистика будет обновлена нулями.", parse_mode='Markdown')
    elif current_state == "notInWar":
         await update.message.reply_text("⛔️ **Внимание!** **Не идет** активная Война Кланов. Статистика в файле не изменится.", parse_mode='Markdown')
         
    
    # 2. ФОРМАТИРОВАНИЕ И ОТПРАВКА
    writer = pd.ExcelWriter(file_path, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Статистика', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Статистика']
    
    date_col_index = df.columns.get_loc("Дата")
    
    merge_ranges = []
    if not df.empty: 
        start_row = 1
        
        for date_value, group in df.groupby("Дата"):
            end_row = start_row + len(group) - 1
            merge_ranges.append((start_row, date_col_index, end_row, date_col_index))
            start_row = end_row + 1

        # Формат для вертикального текста
        vertical_merge_format = workbook.add_format({
            'align': 'center',       
            'valign': 'vcenter',     
            'rotation': 90,          
            'font_size': 14          
        })
        
        # Применяем объединение и вертикальный формат
        for row_start, col_start, row_end, col_end in merge_ranges:
            date_text = df.iloc[row_start - 1, col_start]
            if row_start != row_end: 
                worksheet.merge_range(row_start, col_start, row_end, col_end, date_text, vertical_merge_format)
            else:
                 worksheet.write(row_start, col_start, date_text, vertical_merge_format)
                 
    # 4. Автоматическое расширение столбцов
    for i, col in enumerate(df.columns):
        if col == "Дата":
             worksheet.set_column(i, i, 4) 
        else:
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len) 
                 
    writer.close()
    
    await update.message.reply_document(open(file_path, "rb"))

# ---

def get_top_players(n=5):
    """
    Создает DataFrame, сортирует его по 'Средние звёзды' и возвращает N лучших.
    """
    df = build_stats()

    if df.empty:
        return "Не удалось получить данные о клане или нет участников."

    total_attacks = df['Всего атак'].sum()
    
    df_sorted = df.sort_values(
        by=['Средние звёзды', 'TH', 'Всего атак'], 
        ascending=[False, False, False]
    )
    
    df_active = df_sorted[df_sorted['Всего атак'] > 0]
    top_n = df_active.head(n)
    
    if total_attacks == 0:
        return "В последней войне ещё не было совершено ни одной атаки."

    if top_n.empty and total_attacks > 0:
        return f"Всего совершено {total_attacks} атак. Не удалось определить топ-{n} игроков."
        
    output = f"🏆 **ТОП-{len(top_n)} Игроков** ⚔️ (Всего атак: {total_attacks})\n\n"
    
    for index, row in top_n.iterrows():
        stars_formatted = f"{row['Средние звёзды']:.1f}"
        
        output += (
            f"👤 **{row['Игрок']}** (ТХ {row['TH']}):\n"
            f"   ⭐ {stars_formatted} средних звёзд за {row['Всего атак']} атак.\n"
        )
        
    return output

async def top_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = 5
    if context.args and context.args[0].isdigit():
        n = int(context.args[0])
    
    message = get_top_players(n)
    
    try:
        war_date_range = build_stats()['Дата'].iloc[0]
        message = f"📅 Война: {war_date_range}\n\n" + message
    except:
         pass
         
    await update.message.reply_text(message, parse_mode='Markdown')

# ---

def get_clan_war_stats():
    """Считает общие звезды, разрушение и статус войны."""
    clan_tag_encoded = get_clan_tag().replace('#', '%23') # 🔥 ИЗМЕНЕНО
    wars = coc_get(f"/clans/{clan_tag_encoded}/currentwar") 
    
    if wars.get("state") not in ["inWar", "warEnded", "preparation"]:
        return "В данный момент активная Война Кланов не идет."

    clan_data = wars.get("clan", {})
    opponent_data = wars.get("opponent", {})
    
    if not clan_data or not opponent_data:
        return "Не удалось получить полные данные о текущей войне."

    clan_stars = clan_data.get("stars", 0)
    clan_destruction = clan_data.get("destructionPercentage", 0)
    
    opponent_stars = opponent_data.get("stars", 0)
    opponent_destruction = opponent_data.get("destructionPercentage", 0)
    
    result_emoji = "⚔️"
    result_text = "Война в процессе (День Атаки)"
    
    if wars.get("state") == "preparation":
        result_emoji = "🛡️"
        result_text = "День Подготовки"
    elif wars.get("state") == "warEnded":
        if clan_stars > opponent_stars:
            result_emoji = "🏆"
            result_text = f"Победа! {clan_stars} : {opponent_stars}"
        elif clan_stars < opponent_stars:
            result_emoji = "❌"
            result_text = f"Поражение {clan_stars} : {opponent_stars}"
        else:
            if clan_destruction > opponent_destruction:
                result_emoji = "🏆"
                result_text = f"Победа! (По проценту разрушения)"
            elif clan_destruction < opponent_destruction:
                 result_emoji = "❌"
                 result_text = f"Поражение (По проценту разрушения)"
            else:
                result_emoji = "🤝"
                result_text = "Ничья"
        result_text += f" ({clan_stars} ⭐ / {opponent_stars} ⭐)"


    output = f"📊 **Общая статистика клана в Войне** {result_emoji}\n\n"
    
    try:
        war_date_range = build_stats()['Дата'].iloc[0]
        output += f"📅 **Война:** {war_date_range}\n"
    except:
         pass
         
    output += f"**{result_text}**\n\n"
    
    output += f"**{clan_data['name']}** (VS) **{opponent_data['name']}**\n"
    output += f"⭐ Звёзды: **{clan_stars}** : **{opponent_stars}**\n"
    output += f"🔨 Разрушение: **{clan_destruction:.2f}%** : **{opponent_destruction:.2f}%**\n"
    
    return output

async def clan_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = get_clan_war_stats()
    await update.message.reply_text(message, parse_mode='Markdown')

# ==========================
#  PRODUCTION / DEVELOPMENT RUNNER
# ==========================

def run_production():
    """
    Запускает бота с использованием Webhook'ов (Render) или Polling (локально).
    """
    # Используем os.environ для чтения токена
    token = os.environ.get("TELEGRAM_BOT_TOKEN") 
    
    if not token:
        # Если токен не установлен, выводим ошибку и не запускаемся
        print("Ошибка: TELEGRAM_BOT_TOKEN не установлен. Проверьте переменные окружения.")
        return

    # Получаем порт и внешний URL (для Render)
    port = int(os.environ.get("PORT", 8080))
    WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL") 
    
    if not WEBHOOK_URL:
        # Режим Polling (локальный запуск)
        print("WEBHOOK_URL не найден. Запускаем в режиме Polling (локально).")
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("top", top_stats))
        app.add_handler(CommandHandler("clanstats", clan_stats))
        app.run_polling()
        return

    # Режим Webhook (Render)
    print(f"Запуск в Production (Webhook) на: {WEBHOOK_URL}")

    app = ApplicationBuilder().token(token).build()
    
    # Добавляем все обработчики
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top_stats))
    app.add_handler(CommandHandler("clanstats", clan_stats))
    
    # Устанавливаем Webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token, 
        webhook_url=f"{WEBHOOK_URL}/{token}"
    )

if __name__ == "__main__":
    run_production()