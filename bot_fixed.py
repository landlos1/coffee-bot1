import sqlite3
from datetime import datetime, timedelta
import json
import time
import urllib.request
import qrcode
from io import BytesIO
import threading
import os
import sys

# ============= НАСТРОЙКИ =============
# Токен бота теперь берется из переменных окружения для безопасности
# Установите переменную окружения: export BOT_TOKEN="ваш_токен"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    print("❌ Ошибка: Не задан токен бота. Установите переменную окружения BOT_TOKEN")
    print("   Пример: export BOT_TOKEN='ваш_токен'")
    sys.exit(1)

ADMIN_IDS = [711547379]  # ID АДМИНИСТРАТОРОВ
last_update_id = 0
# =====================================

# Меню кофейни
MENU = {
    "☕ Кофе": {
        "Эспрессо": {"маленький": 120, "большой": 150},
        "Американо": {"маленький": 130, "большой": 160},
        "Капучино": {"маленький": 150, "большой": 180},
        "Латте": {"маленький": 160, "большой": 190}
    },
    "🍵 Чай": {
        "Зеленый чай": {"маленький": 100, "большой": 130},
        "Черный чай": {"маленький": 100, "большой": 130}
    },
    "🍰 Десерты": {
        "Круассан": {"стандарт": 120},
        "Маффин": {"стандарт": 110},
        "Чизкейк": {"стандарт": 180}
    }
}

user_carts = {}

# Состояния пользователей для обработки ввода
user_states = {}

def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

def send_photo(chat_id, photo_bio, caption, keyboard=None):
    try:
        import requests
        files = {'photo': ('qr.png', photo_bio, 'image/png')}
        data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown'}
        if keyboard:
            data['reply_markup'] = json.dumps({"inline_keyboard": keyboard})
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto', files=files, data=data, timeout=10)
    except Exception:
        send_message(chat_id, caption, keyboard)

def send_message(chat_id, text, keyboard=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if keyboard:
            data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")

def get_updates(offset=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        if offset:
            url += f"?offset={offset}&timeout=25"
        else:
            url += "?timeout=25"
        req = urllib.request.Request(url)
        response = urllib.request.urlopen(req, timeout=30)
        data = json.loads(response.read().decode())
        return data.get("result", [])
    except Exception as e:
        print(f"Ошибка получения обновлений: {e}")
        return []

def init_db():
    conn = sqlite3.connect('coffee_bonus.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        birthday TEXT,
        balance INTEGER DEFAULT 0,
        total_bonus_earned INTEGER DEFAULT 0,
        total_spent INTEGER DEFAULT 0,
        registration_date TIMESTAMP,
        last_activity TIMESTAMP,
        last_bonus_date TIMESTAMP,
        level TEXT DEFAULT 'Новичок',
        is_subscribed INTEGER DEFAULT 1
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        date TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        bonus_amount INTEGER,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        expires_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        items TEXT,
        total_amount INTEGER,
        bonus_used INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        order_date TIMESTAMP,
        qr_code TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS expiring_bonuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        earned_date TIMESTAMP,
        expires_at TIMESTAMP,
        is_notified INTEGER DEFAULT 0
    )''')
    
    c.execute('SELECT COUNT(*) FROM promo_codes')
    if c.fetchone()[0] == 0:
        promos = [("COFFEE100", 100, 100), ("WELCOME50", 50, 200), ("BONUS200", 200, 50)]
        for code, bonus, max_uses in promos:
            expires = datetime.now() + timedelta(days=30)
            c.execute('INSERT INTO promo_codes (code, bonus_amount, max_uses, expires_at) VALUES (?,?,?,?)', 
                      (code, bonus, max_uses, expires))
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def register_user(user_id, username, full_name):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('''INSERT OR IGNORE INTO users 
                     (user_id, username, full_name, registration_date, last_activity, balance) 
                     VALUES (?,?,?,?,?,0)''',
                  (user_id, username, full_name, datetime.now(), datetime.now()))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_user_by_id(user_id):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance, level, phone, birthday FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result
    except Exception:
        return None

def get_user_by_phone(phone):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance, level FROM users WHERE phone = ?', (phone,))
        result = c.fetchone()
        conn.close()
        return result
    except Exception:
        return None

def get_user_by_name(name):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance, level FROM users WHERE full_name LIKE ?', (f'%{name}%',))
        result = c.fetchall()
        conn.close()
        return result
    except Exception:
        return []

def get_all_users():
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance, level FROM users WHERE is_subscribed = 1')
        result = c.fetchall()
        conn.close()
        return result
    except Exception:
        return []

def get_balance(user_id):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception:
        return 0

def get_user_level(user_id):
    """
    Определяет уровень пользователя на основе ОБЩЕЙ СУММЫ ПОКУПОК (total_spent),
    а не текущего баланса. Это более логично - уровень не падает при трате бонусов.
    """
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT total_spent FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        if result and result[0]:
            total_spent = result[0]
            if total_spent < 5000:  # До 5000 руб - Новичок
                return "Новичок"
            elif total_spent < 15000:  # До 15000 руб - Знаток
                return "Знаток"
            else:  # От 15000 руб - Гурман
                return "Гурман"
        return "Новичок"
    except Exception:
        return "Новичок"

def get_total_earned(user_id):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT total_bonus_earned FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception:
        return 0

def get_expiring_bonuses(user_id):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT SUM(amount) FROM expiring_bonuses WHERE user_id = ? AND expires_at > datetime("now")', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result and result[0] else 0
    except Exception:
        return 0

def add_bonus_by_purchase(user_id, purchase_amount):
    """Начисляет бонусы за покупку (кешбэк)"""
    try:
        level = get_user_level(user_id)
        
        cashback_percent = {
            "Новичок": 5,
            "Знаток": 7,
            "Гурман": 10
        }.get(level, 5)
        
        bonus_amount = int(purchase_amount * cashback_percent / 100)
        
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + ?, total_bonus_earned = total_bonus_earned + ?, total_spent = total_spent + ?, last_activity = ?, last_bonus_date = ? WHERE user_id = ?',
                  (bonus_amount, bonus_amount, purchase_amount, datetime.now(), datetime.now(), user_id))
        
        expires_at = datetime.now() + timedelta(days=30)
        c.execute('INSERT INTO expiring_bonuses (user_id, amount, earned_date, expires_at) VALUES (?,?,?,?)',
                  (user_id, bonus_amount, datetime.now(), expires_at))
        
        c.execute('INSERT INTO transactions (user_id, amount, type, description, date) VALUES (?,?,?,?,?)',
                  (user_id, bonus_amount, "earn", f"Покупка на {purchase_amount} руб. ({cashback_percent}% кешбэк)", datetime.now()))
        
        conn.commit()
        conn.close()
        
        update_user_level(user_id)
        
        return bonus_amount, cashback_percent
    except Exception as e:
        print(f"Ошибка начисления бонусов: {e}")
        return 0, 0

def add_bonus_direct(user_id, amount, description):
    """Прямое начисление бонусов (для промокодов, подарков и т.д.)"""
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + ?, total_bonus_earned = total_bonus_earned + ?, last_activity = ? WHERE user_id = ?',
                  (amount, amount, datetime.now(), user_id))
        
        expires_at = datetime.now() + timedelta(days=30)
        c.execute('INSERT INTO expiring_bonuses (user_id, amount, earned_date, expires_at) VALUES (?,?,?,?)',
                  (user_id, amount, datetime.now(), expires_at))
        
        c.execute('INSERT INTO transactions (user_id, amount, type, description, date) VALUES (?,?,?,?,?)',
                  (user_id, amount, "earn", description, datetime.now()))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка прямого начисления бонусов: {e}")
        return False

def spend_bonus(user_id, amount, description):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance - ?, last_activity = ? WHERE user_id = ?', 
                  (amount, datetime.now(), user_id))
        c.execute('INSERT INTO transactions (user_id, amount, type, description, date) VALUES (?,?,?,?,?)',
                  (user_id, amount, "spend", description, datetime.now()))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def refund_bonus(user_id, amount, description):
    """Возвращает бонусы на счет (при отмене заказа)"""
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + ?, last_activity = ? WHERE user_id = ?', 
                  (amount, datetime.now(), user_id))
        c.execute('INSERT INTO transactions (user_id, amount, type, description, date) VALUES (?,?,?,?,?)',
                  (user_id, amount, "refund", description, datetime.now()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка возврата бонусов: {e}")
        return False

def get_transactions(user_id):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT amount, type, description, date FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT 10', (user_id,))
        result = c.fetchall()
        conn.close()
        return result
    except Exception:
        return []

def add_order(user_id, user_name, items, total_amount, bonus_used=0):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        
        order_qr = f"ORDER_{int(time.time())}_{user_id}"
        
        c.execute('INSERT INTO orders (user_id, user_name, items, total_amount, bonus_used, status, order_date, qr_code) VALUES (?,?,?,?,?,?,?,?)',
                  (user_id, user_name, json.dumps(items), total_amount, bonus_used, "pending", datetime.now(), order_qr))
        order_id = c.lastrowid
        
        order_qr = f"ORDER_{order_id}_{user_id}"
        c.execute('UPDATE orders SET qr_code = ? WHERE id = ?', (order_qr, order_id))
        
        conn.commit()
        conn.close()
        return order_id, order_qr
    except Exception:
        return None, None

def get_order_by_qr(qr_code):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT id, user_id, user_name, items, total_amount, bonus_used, status FROM orders WHERE qr_code = ?', (qr_code,))
        result = c.fetchone()
        conn.close()
        return result
    except Exception:
        return None

def update_order_status(order_id, status):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def get_pending_orders():
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT id, user_id, user_name, total_amount, order_date FROM orders WHERE status = "pending" ORDER BY order_date DESC')
        result = c.fetchall()
        conn.close()
        return result
    except Exception:
        return []

def parse_datetime(date_string):
    """Гибкий парсер даты с поддержкой разных форматов"""
    if not date_string:
        return None
    formats = [
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d'
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    return None

def apply_promo_code(user_id, code):
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT bonus_amount, max_uses, used_count, expires_at FROM promo_codes WHERE code = ?', (code,))
        promo = c.fetchone()
        if not promo:
            return False, "Промокод не найден"
        bonus_amount, max_uses, used_count, expires_at = promo
        
        # Используем гибкий парсер даты
        expires = parse_datetime(expires_at)
        if expires and datetime.now() > expires:
            return False, "Срок действия истек"
        
        if used_count >= max_uses:
            return False, "Промокод использован максимальное число раз"
        
        c.execute('SELECT id FROM transactions WHERE user_id = ? AND description LIKE ?', (user_id, f'%{code}%'))
        if c.fetchone():
            return False, "Вы уже использовали этот промокод"
        
        # Используем прямое начисление вместо add_bonus_by_purchase
        add_bonus_direct(user_id, bonus_amount, f"Активация промокода {code}")
        
        c.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?', (code,))
        conn.commit()
        conn.close()
        return True, f"Получено {bonus_amount} бонусов!"
    except Exception as e:
        return False, f"Ошибка: {e}"

def get_stats():
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        c.execute('SELECT SUM(balance) FROM users')
        total_bonus = c.fetchone()[0] or 0
        c.execute('SELECT SUM(total_bonus_earned) FROM users')
        total_earned = c.fetchone()[0] or 0
        c.execute('SELECT COUNT(*) FROM orders WHERE status = "pending"')
        pending_orders = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM users WHERE level = "Новичок"')
        novices = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM users WHERE level = "Знаток"')
        experts = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM users WHERE level = "Гурман"')
        gourmets = c.fetchone()[0]
        conn.close()
        return {
            'total_users': total_users,
            'total_bonus': total_bonus,
            'total_earned': total_earned,
            'pending_orders': pending_orders,
            'novices': novices,
            'experts': experts,
            'gourmets': gourmets
        }
    except Exception:
        return None

def send_broadcast(message):
    users = get_all_users()
    success = 0
    for user_id, name, balance, level in users:
        try:
            send_message(user_id, f"📢 *Уведомление от кофейни*\n\n{message}")
            success += 1
            time.sleep(0.05)
        except Exception:
            pass
    return success

def check_birthdays():
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        today = datetime.now().strftime('%m-%d')
        c.execute('SELECT user_id, full_name FROM users WHERE birthday LIKE ? AND is_subscribed = 1', (f'%-{today}',))
        users = c.fetchall()
        for user_id, name in users:
            add_bonus_direct(user_id, 100, "Подарок на День Рождения")
            send_message(user_id, f"🎂 *С Днем Рождения, {name}!* 🎂\n\nВам начислено 100 бонусов!")
        conn.close()
    except Exception:
        pass

def get_level_icon(level):
    icons = {"Новичок": "☕", "Знаток": "🌟", "Гурман": "👑"}
    return icons.get(level, "☕")

def get_cashback_percent(level):
    percents = {"Новичок": 5, "Знаток": 7, "Гурман": 10}
    return percents.get(level, 5)

def get_level_benefits(level):
    benefits = {
        "Новичок": "5% кешбэк",
        "Знаток": "7% кешбэк + приоритет",
        "Гурман": "10% кешбэк + подарок в ДР"
    }
    return benefits.get(level, "5% кешбэк")

def update_user_level(user_id):
    """Обновляет уровень пользователя на основе total_spent"""
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT total_spent FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if result and result[0]:
            total_spent = result[0]
            if total_spent < 5000:
                level = "Новичок"
            elif total_spent < 15000:
                level = "Знаток"
            else:
                level = "Гурман"
            c.execute('UPDATE users SET level = ? WHERE user_id = ?', (level, user_id))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка обновления уровня: {e}")

def show_admin_menu(chat_id):
    keyboard = [
        [{"text": "📷 Сканировать QR", "callback_data": "admin_scan_qr"}],
        [{"text": "🔍 Поиск по ID", "callback_data": "admin_search_id"}],
        [{"text": "📞 Поиск по телефону", "callback_data": "admin_search_phone"}],
        [{"text": "👤 Поиск по имени", "callback_data": "admin_search_name"}],
        [{"text": "💰 Начислить бонусы", "callback_data": "admin_add_bonus"}],
        [{"text": "📋 Список заказов", "callback_data": "admin_orders"}],
        [{"text": "📊 Статистика", "callback_data": "admin_stats"}],
        [{"text": "📢 Рассылка", "callback_data": "admin_broadcast"}]
    ]
    send_message(chat_id, "👑 *Панель администратора*\n\nВыберите действие:", keyboard)

def handle_message(chat_id, text, user_id, username, full_name, photo=None):
    register_user(user_id, username, full_name)
    is_admin = user_id in ADMIN_IDS
    
    # Обработка фото для распознавания QR
    if photo:
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        
        send_message(chat_id, "🔍 Распознаю QR-код...")
        
        try:
            import requests
            from PIL import Image
            from pyzbar.pyzbar import decode
            
            file_id = photo[-1]['file_id']
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            req = urllib.request.Request(url)
            response = urllib.request.urlopen(req)
            file_info = json.loads(response.read().decode())
            file_path = file_info['result']['file_path']
            
            photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            img_response = requests.get(photo_url)
            img = Image.open(BytesIO(img_response.content))
            
            decoded_objects = decode(img)
            
            if decoded_objects:
                for obj in decoded_objects:
                    qr_data = obj.data.decode('utf-8')
                    print(f"Распознан QR: {qr_data}")
                    
                    if qr_data.startswith("COFFEE_BONUS:"):
                        client_id = qr_data.replace("COFFEE_BONUS:", "")
                        if client_id.isdigit():
                            client = get_user_by_id(int(client_id))
                            if client:
                                cid, name, balance, level, phone, birthday = client
                                msg = f"""✅ *QR-код клиента распознан!*

👤 *Клиент найден*

🆔 ID: {cid}
👤 Имя: {name}
💰 Баланс: {balance} бонусов
👑 Уровень: {level} ({get_cashback_percent(level)}% кешбэк)
📞 Телефон: {phone or 'не указан'}
🎂 ДР: {birthday or 'не указан'}"""
                                
                                keyboard = [[
                                    {"text": "💰 Начислить бонусы", "callback_data": f"add_bonus_{cid}"}
                                ]]
                                send_message(chat_id, msg, keyboard)
                            else:
                                send_message(chat_id, f"❌ Клиент с ID {client_id} не найден")
                    
                    elif qr_data.startswith("ORDER_"):
                        order = get_order_by_qr(qr_data)
                        if order:
                            order_id, uid, name, items_json, total, bonus_used, status = order
                            items = json.loads(items_json)
                            
                            if status == "pending":
                                msg = f"""✅ *QR-код заказа распознан!*

📦 *Заказ #{order_id}*

👤 *Клиент:* {name}
🆔 ID: {uid}
💰 *Сумма:* {total}₽
🎫 *Бонусов использовано:* {bonus_used}
💵 *К оплате:* {total - bonus_used}₽

🛒 *Состав заказа:*
"""
                                for it in items:
                                    msg += f"• {it['item']} — {it['price']}₽\n"
                                
                                keyboard = [[
                                    {"text": "✅ Подтвердить заказ", "callback_data": f"confirm_order_{order_id}"},
                                    {"text": "❌ Отменить заказ", "callback_data": f"cancel_order_{order_id}"}
                                ]]
                                send_message(chat_id, msg, keyboard)
                            else:
                                send_message(chat_id, f"📦 *Заказ #{order_id}*\n\nСтатус: {status}")
                        else:
                            send_message(chat_id, "❌ Заказ не найден")
                    else:
                        send_message(chat_id, "❌ Неизвестный QR-код")
            else:
                send_message(chat_id, "❌ QR-код не обнаружен на фото")
                
        except Exception as e:
            print(f"Ошибка распознавания: {e}")
            send_message(chat_id, f"❌ Ошибка распознавания")
        return
    
    # Админ меню
    if text == "/admin":
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        show_admin_menu(chat_id)
    
    # Поиск по QR (текстовый)
    elif text.startswith("/scanqr"):
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /scanqr [данные]")
            return
        qr_data = parts[1]
        if qr_data.startswith("COFFEE_BONUS:"):
            client_id = qr_data.replace("COFFEE_BONUS:", "")
            if client_id.isdigit():
                client = get_user_by_id(int(client_id))
                if client:
                    cid, name, balance, level, phone, birthday = client
                    msg = f"""👤 *Клиент найден*

🆔 ID: {cid}
👤 Имя: {name}
💰 Баланс: {balance}
👑 Уровень: {level}
📞 Телефон: {phone or 'не указан'}
🎂 ДР: {birthday or 'не указан'}"""
                    keyboard = [[
                        {"text": "💰 Начислить бонусы", "callback_data": f"add_bonus_{cid}"}
                    ]]
                    send_message(chat_id, msg, keyboard)
                else:
                    send_message(chat_id, "❌ Клиент не найден")
        elif qr_data.startswith("ORDER_"):
            order = get_order_by_qr(qr_data)
            if order:
                order_id, uid, name, items_json, total, bonus_used, status = order
                items = json.loads(items_json)
                msg = f"📦 *Заказ #{order_id}*\n👤 {name}\n💰 {total}₽\n📅 Статус: {status}"
                send_message(chat_id, msg)
            else:
                send_message(chat_id, "❌ Заказ не найден")
        else:
            send_message(chat_id, "❌ Неверный QR-код")
    
    # Поиск по телефону
    elif text.startswith("/find"):
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /find [телефон]")
            return
        phone = parts[1]
        client = get_user_by_phone(phone)
        if client:
            cid, name, balance, level = client
            # ИСПРАВЛЕНО: добавлен отступ
            msg = f"👤 *Клиент*\n🆔 ID: {cid}\n👤 Имя: {name}\n💰 Баланс: {balance}\n👑 Уровень: {level}"
            keyboard = [[{"text": "💰 Начислить бонусы", "callback_data": f"add_bonus_{cid}"}]]
            send_message(chat_id, msg, keyboard)
        else:
            send_message(chat_id, "❌ Клиент не найден")
    
    # Поиск по имени
    elif text.startswith("/findname"):
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /findname [имя]")
            return
        name = " ".join(parts[1:])
        clients = get_user_by_name(name)
        if clients:
            msg = f"👥 *Найдено {len(clients)} клиентов:*\n\n"
            for cid, full_name, balance, level in clients[:10]:
                msg += f"🆔 {cid} — {full_name}\n   💰 {balance} бонусов, {level}\n"
            send_message(chat_id, msg)
        else:
            send_message(chat_id, "❌ Клиенты не найдены")
    
    # Установка телефона
    elif text.startswith("/setphone"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /setphone [номер]")
            return
        phone = parts[1]
        try:
            conn = sqlite3.connect('coffee_bonus.db')
            c = conn.cursor()
            c.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
            conn.commit()
            conn.close()
            send_message(chat_id, f"✅ Телефон {phone} сохранен!")
        except Exception:
            send_message(chat_id, "❌ Ошибка")
    
    # Установка дня рождения
    elif text.startswith("/setbirthday"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /setbirthday [ДД.ММ]")
            return
        birthday = parts[1]
        try:
            conn = sqlite3.connect('coffee_bonus.db')
            c = conn.cursor()
            c.execute('UPDATE users SET birthday = ? WHERE user_id = ?', (birthday, user_id))
            conn.commit()
            conn.close()
            send_message(chat_id, f"✅ ДР {birthday} сохранен! В этот день получите подарок!")
        except Exception:
            send_message(chat_id, "❌ Ошибка")
    
    # Статистика
    elif text == "/stats":
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        stats = get_stats()
        if stats:
            msg = f"""📊 *Статистика*

👥 Клиентов: {stats['total_users']}
💰 Бонусов: {stats['total_bonus']}
📈 Начислено: {stats['total_earned']}
📦 Ожидает заказов: {stats['pending_orders']}

Уровни:
☕ Новички: {stats['novices']}
🌟 Знатоки: {stats['experts']}
👑 Гурманы: {stats['gourmets']}"""
            send_message(chat_id, msg)
    
    # Список заказов
    elif text == "/orders":
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        orders = get_pending_orders()
        if not orders:
            send_message(chat_id, "📭 Нет активных заказов")
        else:
            msg = "📋 *Ожидающие заказы:*\n\n"
            for order_id, uid, name, total, date in orders:
                date_obj = parse_datetime(date)
                date_str = date_obj.strftime('%d.%m.%Y %H:%M') if date_obj else str(date)
                msg += f"📦 *Заказ #{order_id}*\n"
                msg += f"👤 {name} (ID: {uid})\n"
                msg += f"💰 {total}₽\n"
                msg += f"🕐 {date_str}\n\n"
            send_message(chat_id, msg)
    
    # Рассылка
    elif text.startswith("/broadcast"):
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /broadcast [сообщение]")
            return
        message = " ".join(parts[1:])
        send_message(chat_id, "📨 Начинаю рассылку...")
        sent = send_broadcast(message)
        send_message(chat_id, f"✅ Доставлено: {sent}")
    
    # Список пользователей
    elif text == "/users":
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        users = get_all_users()
        if not users:
            send_message(chat_id, "📭 Нет пользователей")
        else:
            msg = "👥 *Пользователи:*\n\n"
            for uid, name, balance, level in users[:20]:
                msg += f"🆔 {uid} — {name}\n   💰 {balance}, {level}\n"
            send_message(chat_id, msg)
    
    # Заказ
    elif text == "/order":
        user_carts[user_id] = []
        msg = "☕ *Меню*\n\nВыберите категорию:"
        keyboard = [[{"text": cat, "callback_data": f"cat_{cat}"}] for cat in MENU.keys()]
        send_message(chat_id, msg, keyboard)
    
    # /start
    elif text == "/start":
        balance = get_balance(user_id)
        level = get_user_level(user_id)
        total_earned = get_total_earned(user_id)
        expiring = get_expiring_bonuses(user_id)
        icon = get_level_icon(level)
        
        qr_data = f"COFFEE_BONUS:{user_id}"
        qr_bio = generate_qr_code(qr_data)
        
        msg = f"""☕ *Добро пожаловать в кофейню!* ☕

Привет, *{full_name}*!

{icon} *Уровень:* {level}
💰 *Баланс:* {balance} бонусов
📈 *Всего начислено:* {total_earned}
⏰ *Сгорает через 30 дней:* {expiring}

🎁 *Кешбэк:* {get_cashback_percent(level)}%
{get_level_benefits(level)}

📱 *Ваш QR-код:*
Покажите кассиру для получения бонусов!"""
        
        keyboard = [
            [{"text": "💰 Баланс", "callback_data": "balance"}],
            [{"text": "📜 История", "callback_data": "history"}],
            [{"text": "🎫 Промокоды", "callback_data": "promos"}],
            [{"text": "📊 Уровень", "callback_data": "level"}],
            [{"text": "☕ Сделать заказ", "callback_data": "order"}]
        ]
        send_photo(chat_id, qr_bio, msg, keyboard)
    
    # /qr
    elif text == "/qr":
        qr_bio = generate_qr_code(f"COFFEE_BONUS:{user_id}")
        send_photo(chat_id, qr_bio, "🎫 *Ваш персональный QR-код*\nПокажите его кассиру при покупке!")
    
    # /bonus
    elif text == "/bonus":
        balance = get_balance(user_id)
        level = get_user_level(user_id)
        send_message(chat_id, f"💰 *Ваш баланс:* {balance} бонусов\n👑 *Уровень:* {level}")
    
    # /id
    elif text == "/id":
        send_message(chat_id, f"🆔 *Ваш ID:* `{user_id}`")
    
    # /level
    elif text == "/level":
        balance = get_balance(user_id)
        level = get_user_level(user_id)
        msg = f"📊 *Уровень:* {level}\n💎 Бонусов: {balance}\n"
        if level == "Новичок":
            msg += f"📈 До уровня Знаток: потратьте еще {5000 - get_user_total_spent(user_id)} руб."
        elif level == "Знаток":
            msg += f"📈 До уровня Гурман: потратьте еще {15000 - get_user_total_spent(user_id)} руб."
        send_message(chat_id, msg)
    
    # /spend
    elif text.startswith("/spend"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "📝 Использование: /spend [сумма]\nПример: /spend 50")
            return
        try:
            amount = int(parts[1])
            current = get_balance(user_id)
            if amount <= 0:
                send_message(chat_id, "❌ Сумма должна быть положительной")
            elif amount > current:
                send_message(chat_id, f"❌ Недостаточно! Доступно: {current} бонусов")
            else:
                spend_bonus(user_id, amount, f"Списание {amount} бонусов")
                send_message(chat_id, f"✅ Списано {amount} бонусов\n💰 Остаток: {get_balance(user_id)}")
        except Exception:
            send_message(chat_id, "❌ Введите число")
    
    # /promo
    elif text.startswith("/promo"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "🎫 *Промокоды:* COFFEE100, WELCOME50, BONUS200\nИспользование: /promo КОД")
            return
        ok, msg = apply_promo_code(user_id, parts[1].upper())
        send_message(chat_id, msg)
    
    # /promos
    elif text == "/promos":
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT code, bonus_amount FROM promo_codes LIMIT 5')
        promos = c.fetchall()
        conn.close()
        if not promos:
            send_message(chat_id, "🎫 Нет активных промокодов")
        else:
            msg = "🎫 *Доступные промокоды:*\n\n"
            for code, bonus in promos:
                msg += f"`{code}` — {bonus} бонусов\n"
            msg += "\nИспользуйте: `/promo КОД`"
            send_message(chat_id, msg)
    
    # /history
    elif text == "/history":
        trans = get_transactions(user_id)
        if not trans:
            send_message(chat_id, "📭 У вас пока нет операций")
        else:
            msg = "📜 *Последние операции:*\n\n"
            for amount, typ, desc, date in trans:
                emoji = "➕" if typ == "earn" else "➖"
                msg += f"{emoji} *{amount}* — {desc}\n"
            send_message(chat_id, msg)
    
    # /earn (админ)
    elif text.startswith("/earn"):
        if not is_admin:
            send_message(chat_id, "⛔ У вас нет прав")
            return
        parts = text.split()
        if len(parts) < 3:
            send_message(chat_id, "📝 *Начисление бонусов*\n\nФормат: `/earn [id] [сумма_покупки]`\n\nПример: `/earn 123456789 500`\n\nБонусы начисляются в зависимости от уровня клиента:\n☕ Новичок: 5%\n🌟 Знаток: 7%\n👑 Гурман: 10%")
            return
        try:
            target = int(parts[1])
            purchase_amount = int(parts[2])
            
            user_info = get_user_by_id(target)
            user_name = user_info[1] if user_info else str(target)
            level = get_user_level(target)
            
            bonus_amount, cashback_percent = add_bonus_by_purchase(target, purchase_amount)
            
            if bonus_amount > 0:
                msg = f"✅ *Бонусы начислены!*\n\n"
                msg += f"👤 Клиент: {user_name}\n"
                msg += f"🆔 ID: {target}\n"
                msg += f"👑 Уровень: {level}\n"
                msg += f"💰 Сумма покупки: {purchase_amount} руб.\n"
                msg += f"🎁 Начислено: {bonus_amount} бонусов ({cashback_percent}%)\n"
                msg += f"💎 Новый баланс: {get_balance(target)} бонусов"
                
                send_message(chat_id, msg)
                
                client_msg = f"🎉 *За покупку на {purchase_amount} руб.*\n\n"
                client_msg += f"Вам начислено *{bonus_amount} бонусов* ({cashback_percent}% кешбэк)!\n"
                client_msg += f"💰 Ваш баланс: {get_balance(target)} бонусов\n\n"
                client_msg += f"✨ У вас уровень: {level}\n"
                
                send_message(target, client_msg)
            else:
                send_message(chat_id, "❌ Ошибка начисления бонусов")
                
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
    
    # /help
    elif text == "/help":
        msg = """📚 *Команды бота*

👤 *Для клиентов:*
/start — главное меню с QR-кодом
/bonus — проверить баланс
/qr — получить QR-код
/spend [сумма] — потратить бонусы
/promo [код] — активировать промокод
/promos — список промокодов
/order — сделать заказ
/setphone [номер] — сохранить телефон
/setbirthday [ДД.ММ] — сохранить ДР
/level — информация об уровнях
/history — история операций
/id — узнать свой ID
/help — эта справка

👑 *Для администратора:*
/admin — панель администратора
/scanqr [данные] — поиск по QR
/find [телефон] — поиск по телефону
/findname [имя] — поиск по имени
/earn [id] [сумма] — начислить бонусы
/orders — список заказов
/stats — статистика
/users — список пользователей
/broadcast [текст] — массовая рассылка

🎫 *Промокоды:* COFFEE100, WELCOME50, BONUS200"""
        send_message(chat_id, msg)
    
    else:
        send_message(chat_id, "❓ Неизвестная команда. Используйте /help")

def get_user_total_spent(user_id):
    """Вспомогательная функция для получения общей суммы покупок"""
    try:
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT total_spent FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result and result[0] else 0
    except Exception:
        return 0

def handle_callback(chat_id, data, user_id):
    is_admin = user_id in ADMIN_IDS
    
    if data.startswith("add_bonus_"):
        if not is_admin:
            return
        target_id = int(data.replace("add_bonus_", ""))
        send_message(chat_id, f"💰 Введите сумму покупки для клиента {target_id}:\n\nФормат: `/earn {target_id} [сумма]`")
    
    elif data == "admin_scan_qr":
        send_message(chat_id, "📷 *Сканирование QR-кода*\n\nОтправьте фото QR-кода клиента или заказа, и я найду его в системе.\n\n📱 *Инструкция:*\n1. Нажмите на скрепку 📎\n2. Выберите \"Камера\"\n3. Сфотографируйте QR-код\n4. Отправьте фото")
    
    elif data == "admin_search_id":
        send_message(chat_id, "🔍 Введите ID клиента:\n\nФормат: `/find [id]`")
    
    elif data == "admin_search_phone":
        send_message(chat_id, "📞 Введите номер телефона:\n\nФормат: `/find [телефон]`")
    
    elif data == "admin_search_name":
        send_message(chat_id, "👤 Введите имя клиента:\n\nФормат: `/findname [имя]`")
    
    elif data == "admin_add_bonus":
        send_message(chat_id, "💰 Введите ID и сумму покупки:\n\nФормат: `/earn [id] [сумма]`\n\nПример: `/earn 123456789 500`")
    
    elif data == "admin_orders":
        orders = get_pending_orders()
        if not orders:
            send_message(chat_id, "📭 Нет активных заказов")
        else:
            for order_id, uid, name, total, date in orders:
                date_obj = parse_datetime(date)
                date_str = date_obj.strftime('%d.%m.%Y %H:%M') if date_obj else str(date)
                msg = f"📦 *Заказ #{order_id}*\n\n"
                msg += f"👤 {name}\n"
                msg += f"🆔 ID: {uid}\n"
                msg += f"💰 Сумма: {total}₽\n"
                msg += f"🕐 {date_str}\n\n"
                keyboard = [[
                    {"text": "✅ Подтвердить", "callback_data": f"confirm_order_{order_id}"},
                    {"text": "❌ Отменить", "callback_data": f"cancel_order_{order_id}"}
                ]]
                send_message(chat_id, msg, keyboard)
    
    elif data == "admin_stats":
        stats = get_stats()
        if stats:
            msg = f"""📊 *Статистика*

👥 Клиентов: {stats['total_users']}
💰 Бонусов: {stats['total_bonus']}
📈 Начислено: {stats['total_earned']}
📦 Ожидает заказов: {stats['pending_orders']}

Уровни:
☕ Новички: {stats['novices']}
🌟 Знатоки: {stats['experts']}
👑 Гурманы: {stats['gourmets']}"""
            send_message(chat_id, msg)
    
    elif data == "admin_broadcast":
        send_message(chat_id, "📢 Введите сообщение для рассылки:\n\nФормат: `/broadcast [текст]`")
    
    elif data.startswith("confirm_order_"):
        if not is_admin:
            return
        order_id = int(data.replace("confirm_order_", ""))
        try:
            conn = sqlite3.connect('coffee_bonus.db')
            c = conn.cursor()
            c.execute('SELECT user_id, user_name, items, total_amount, bonus_used FROM orders WHERE id = ?', (order_id,))
            result = c.fetchone()
            if result:
                user_id_customer, user_name, items_json, total_amount, bonus_used = result
                items = json.loads(items_json)
                
                update_order_status(order_id, "confirmed")
                send_message(chat_id, f"✅ Заказ #{order_id} подтвержден!")
                
                final_amount = total_amount - bonus_used
                
                client_msg = f"✅ *Ваш заказ #{order_id} подтвержден!*\n\n"
                client_msg += f"🛒 *Состав заказа:*\n"
                for it in items:
                    client_msg += f"• {it['item']} — {it['price']}₽\n"
                client_msg += f"\n💰 *Сумма:* {total_amount}₽\n"
                client_msg += f"🎫 *Использовано бонусов:* {bonus_used}\n"
                client_msg += f"💵 *К оплате:* {final_amount}₽\n\n"
                client_msg += f"☕ Заказ готовится. Ждем вас в кофейне!"
                
                send_message(user_id_customer, client_msg)
            conn.close()
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
    
    elif data.startswith("cancel_order_"):
        if not is_admin:
            return
        order_id = int(data.replace("cancel_order_", ""))
        try:
            conn = sqlite3.connect('coffee_bonus.db')
            c = conn.cursor()
            c.execute('SELECT user_id, user_name, bonus_used FROM orders WHERE id = ?', (order_id,))
            result = c.fetchone()
            if result:
                user_id_customer, user_name, bonus_used = result
                
                # Возвращаем бонусы клиенту
                if bonus_used > 0:
                    refund_bonus(user_id_customer, bonus_used, f"Возврат бонусов за отмененный заказ #{order_id}")
                
                update_order_status(order_id, "cancelled")
                send_message(chat_id, f"❌ Заказ #{order_id} отменен!")
                
                refund_msg = ""
                if bonus_used > 0:
                    refund_msg = f"\n\n💰 {bonus_used} бонусов возвращено на ваш счет."
                
                send_message(user_id_customer, f"❌ *Ваш заказ #{order_id} отменен*{refund_msg}\n\nЕсли у вас есть вопросы, обратитесь к администратору.")
            conn.close()
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
    
    elif data == "balance":
        balance = get_balance(user_id)
        level = get_user_level(user_id)
        send_message(chat_id, f"💰 *Баланс:* {balance} бонусов\n👑 *Уровень:* {level}")
    
    elif data == "history":
        trans = get_transactions(user_id)
        if not trans:
            send_message(chat_id, "📭 Нет операций")
        else:
            msg = "📜 *История операций:*\n\n"
            for amount, typ, desc, date in trans:
                emoji = "➕" if typ == "earn" else "➖"
                msg += f"{emoji} *{amount}* — {desc}\n"
            send_message(chat_id, msg)
    
    elif data == "promos":
        conn = sqlite3.connect('coffee_bonus.db')
        c = conn.cursor()
        c.execute('SELECT code, bonus_amount FROM promo_codes LIMIT 5')
        promos = c.fetchall()
        conn.close()
        if not promos:
            send_message(chat_id, "🎫 Нет активных промокодов")
        else:
            msg = "🎫 *Промокоды:*\n"
            for code, bonus in promos:
                msg += f"`{code}` — {bonus} бонусов\n"
            send_message(chat_id, msg)
    
    elif data == "level":
        balance = get_balance(user_id)
        level = get_user_level(user_id)
        msg = f"📊 *Уровень:* {level}\n💎 *Бонусов:* {balance}\n"
        total_spent = get_user_total_spent(user_id)
        if level == "Новичок":
            msg += f"📈 До Знатока: потратьте еще {5000 - total_spent} руб."
        elif level == "Знаток":
            msg += f"📈 До Гурмана: потратьте еще {15000 - total_spent} руб."
        send_message(chat_id, msg)
    
    elif data == "order":
        user_carts[user_id] = []
        msg = "☕ *Меню кофейни*\n\nВыберите категорию:"
        keyboard = [[{"text": cat, "callback_data": f"cat_{cat}"}] for cat in MENU.keys()]
        send_message(chat_id, msg, keyboard)
    
    elif data.startswith("cat_"):
        category = data.replace("cat_", "")
        msg = f"📋 *{category}*\n\nВыберите позицию:"
        keyboard = [[{"text": item, "callback_data": f"item_{category}_{item}"}] for item in MENU[category].keys()]
        keyboard.append([{"text": "🔙 Назад", "callback_data": "back_menu"}])
        send_message(chat_id, msg, keyboard)
    
    elif data.startswith("item_"):
        parts = data.split("_")
        category = parts[1]
        item = parts[2]
        msg = f"☕ *{item}*\n\nВыберите размер:"
        keyboard = []
        for size, price in MENU[category][item].items():
            keyboard.append([{"text": f"{size} — {price}₽", "callback_data": f"size_{category}_{item}_{size}_{price}"}])
        keyboard.append([{"text": "🔙 Назад", "callback_data": f"back_{category}"}])
        send_message(chat_id, msg, keyboard)
    
    elif data.startswith("size_"):
        parts = data.split("_")
        category = parts[1]
        item = parts[2]
        size = parts[3]
        price = int(parts[4])
        
        if user_id not in user_carts:
            user_carts[user_id] = []
        user_carts[user_id].append({"item": f"{item} ({size})", "price": price})
        total = sum(x["price"] for x in user_carts[user_id])
        
        msg = f"✅ *Добавлено в корзину:* {item} ({size}) — {price}₽\n\n"
        msg += f"🛒 *Ваша корзина:*\n"
        for i, it in enumerate(user_carts[user_id], 1):
            msg += f"{i}. {it['item']} — {it['price']}₽\n"
        msg += f"\n💰 *Итого:* {total}₽"
        
        keyboard = [
            [{"text": "➕ Добавить еще", "callback_data": "add_more"}],
            [{"text": "✅ Оформить заказ", "callback_data": "checkout"}],
            [{"text": "🗑 Очистить корзину", "callback_data": "clear_cart"}]
        ]
        send_message(chat_id, msg, keyboard)
    
    elif data == "add_more":
        msg = "☕ *Выберите категорию:*"
        keyboard = [[{"text": cat, "callback_data": f"cat_{cat}"}] for cat in MENU.keys()]
        keyboard.append([{"text": "✅ Оформить", "callback_data": "checkout"}])
        send_message(chat_id, msg, keyboard)
    
    elif data == "clear_cart":
        user_carts[user_id] = []
        send_message(chat_id, "🗑 Корзина очищена!")
    
    elif data == "checkout":
        if user_id not in user_carts or not user_carts[user_id]:
            send_message(chat_id, "🛒 Ваша корзина пуста!")
            return
        total = sum(x["price"] for x in user_carts[user_id])
        balance = get_balance(user_id)
        max_bonus = min(balance, int(total * 0.5))
        
        msg = f"💰 *Оформление заказа*\n\n"
        msg += f"💰 Сумма заказа: {total}₽\n"
        msg += f"🎫 Ваш баланс: {balance} бонусов\n"
        msg += f"💎 Можно использовать: {max_bonus} бонусов (макс. 50%)\n\n"
        msg += f"Использовать бонусы?"
        
        keyboard = [
            [{"text": f"✅ Да, использовать {max_bonus} бонусов", "callback_data": f"use_{max_bonus}"}],
            [{"text": "❌ Нет, оплатить полностью", "callback_data": "use_0"}]
        ]
        send_message(chat_id, msg, keyboard)
    
    elif data.startswith("use_"):
        bonus_used = int(data.replace("use_", ""))
        total = sum(x["price"] for x in user_carts[user_id])
        
        if bonus_used > 0:
            spend_bonus(user_id, bonus_used, f"Оплата заказа {bonus_used} бонусами")
        
        final = total - bonus_used
        
        user_info = get_user_by_id(user_id)
        user_name = user_info[1] if user_info else str(user_id)
        
        order_id, order_qr = add_order(user_id, user_name, user_carts[user_id], total, bonus_used)
        
        if final > 0:
            add_bonus_by_purchase(user_id, final)
        
        order_qr_bio = generate_qr_code(order_qr)
        
        msg = f"✅ *Заказ #{order_id} оформлен!*\n\n"
        msg += f"🛒 *Состав заказа:*\n"
        for it in user_carts[user_id]:
            msg += f"• {it['item']} — {it['price']}₽\n"
        msg += f"\n💰 *Сумма:* {total}₽\n"
        msg += f"🎫 *Использовано бонусов:* {bonus_used}\n"
        msg += f"💵 *К оплате:* {final}₽\n\n"
        msg += f"📱 *QR-код заказа:*\nПокажите этот QR-код администратору при получении заказа."
        
        send_photo(chat_id, order_qr_bio, msg)
        
        for admin_id in ADMIN_IDS:
            admin_msg = f"🆕 *НОВЫЙ ЗАКАЗ #{order_id}*\n\n"
            admin_msg += f"👤 *Клиент:* {user_name}\n"
            admin_msg += f"🆔 ID: {user_id}\n"
            admin_msg += f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            admin_msg += f"🛒 *Состав:*\n"
            for it in user_carts[user_id]:
                admin_msg += f"• {it['item']} — {it['price']}₽\n"
            admin_msg += f"\n💰 *Сумма:* {total}₽\n"
            admin_msg += f"🎫 *Бонусов:* {bonus_used}\n"
            admin_msg += f"💵 *К оплате:* {final}₽\n\n"
            admin_msg += f"📱 *QR заказа:* `{order_qr}`"
            
            keyboard = [[
                {"text": "✅ Подтвердить", "callback_data": f"confirm_order_{order_id}"},
                {"text": "❌ Отменить", "callback_data": f"cancel_order_{order_id}"}
            ]]
            send_message(admin_id, admin_msg, keyboard)
        
        user_carts[user_id] = []
    
    elif data == "back_menu":
        # ИСПРАВЛЕНО: добавлен отступ
        msg = "☕ *Меню кофейни*\n\nВыберите категорию:"
        keyboard = [[{"text": cat, "callback_data": f"cat_{cat}"}] for cat in MENU.keys()]
        send_message(chat_id, msg, keyboard)
    
    elif data.startswith("back_"):
        category = data.replace("back_", "")
        msg = f"📋 *{category}*\n\nВыберите позицию:"
        keyboard = [[{"text": item, "callback_data": f"item_{category}_{item}"}] for item in MENU[category].keys()]
        keyboard.append([{"text": "🔙 Назад", "callback_data": "back_menu"}])
        send_message(chat_id, msg, keyboard)

def main():
    global last_update_id
    print("=" * 50)
    print("☕ БОНУСНЫЙ БОТ ДЛЯ КОФЕЙНИ")
    print("=" * 50)
    init_db()
    print("✅ Бот запущен! Отправьте /start в Telegram")
    print("=" * 50)
    
    def background():
        while True:
            try:
                check_birthdays()
                time.sleep(3600)
            except Exception:
                time.sleep(60)
    
    thread = threading.Thread(target=background, daemon=True)
    thread.start()
    
    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for update in updates:
                if "message" in update:
                    msg = update["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")
                    user = msg["from"]
                    user_id = user["id"]
                    username = user.get("username", "")
                    full_name = user.get("first_name", "")
                    photo = msg.get("photo")
                    
                    if text:
                        print(f"📩 {full_name}: {text}")
                        handle_message(chat_id, text, user_id, username, full_name)
                    elif photo:
                        print(f"📸 {full_name}: отправил фото")
                        handle_message(chat_id, "", user_id, username, full_name, photo)
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    chat_id = cb["message"]["chat"]["id"]
                    data = cb["data"]
                    user_id = cb["from"]["id"]
                    try:
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                        data_cb = json.dumps({"callback_query_id": cb["id"]}).encode()
                        req = urllib.request.Request(url, data=data_cb, headers={'Content-Type': 'application/json'})
                        urllib.request.urlopen(req)
                    except Exception:
                        pass
                    handle_callback(chat_id, data, user_id)
                last_update_id = update["update_id"]
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
