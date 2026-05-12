import os
import telebot
import sqlite3
from flask import Flask, request
import google.generativeai as genai
from datetime import datetime
from telebot import types
from PIL import Image

# הגדרות בסיסיות
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
ALLOWED_USER_ID = os.environ.get('ALLOWED_USER_ID')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)
genai.configure(api_key=GEMINI_API_KEY)

# --- ניהול מסד נתונים (SQLite) ---
def init_db():
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    # טבלת ארוחות
    c.execute('''CREATE TABLE IF NOT EXISTS meals 
                 (user_id TEXT, date TEXT, time TEXT, description TEXT, calories REAL, protein REAL, carbs REAL, fat REAL)''')
    # טבלת היסטוריית שיחה לצורך הזיכרון של ה-AI
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history 
                 (user_id TEXT, role TEXT, message_text TEXT)''')
    conn.commit()
    conn.close()

def save_meal(user_id, meal_data):
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    now = datetime.now()
    c.execute("INSERT INTO meals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (user_id, now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), 
               meal_data.get('description', ''), meal_data.get('calories', 0),
               meal_data.get('protein', 0), meal_data.get('carbs', 0), meal_data.get('fat', 0)))
    conn.commit()
    conn.close()

def get_daily_summary(user_id):
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT SUM(calories), SUM(protein), SUM(carbs), SUM(fat) FROM meals WHERE user_id=? AND date=?", (user_id, today))
    summary = c.fetchone()
    conn.close()
    return summary

def delete_last_meal(user_id):
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    # שליפת המנה האחרונה כדי שנוכל להגיד למשתמש מה נמחק
    c.execute("SELECT description FROM meals WHERE user_id=? ORDER BY rowid DESC LIMIT 1", (user_id,))
    res = c.fetchone()
    if res:
        c.execute("DELETE FROM meals WHERE rowid = (SELECT MAX(rowid) FROM meals WHERE user_id=?)", (user_id,))
        conn.commit()
    conn.close()
    return res[0] if res else None

def save_chat_message(user_id, role, text):
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    c.execute("INSERT INTO chat_history VALUES (?, ?, ?)", (user_id, role, text))
    conn.commit()
    conn.close()

def get_chat_context(user_id, limit=10):
    conn = sqlite3.connect('nutrition.db')
    c = conn.cursor()
    # שליפת 10 ההודעות האחרונות וסידורן מהישן לחדש
    c.execute("""SELECT role, message_text FROM (
                    SELECT role, message_text, rowid FROM chat_history 
                    WHERE user_id=? ORDER BY rowid DESC LIMIT ?
                 ) ORDER BY rowid ASC""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    
    # הפיכה למבנה ש-Gemini מבין
    history = []
    for role, text in rows:
        history.append({'role': role, 'parts': [text]})
    return history

init_db()

# --- הגדרת המערכת השיחתית החדשה ---
system_instruction = """
אתה עוזר תזונה אישי חכם ומנהל שיחה זורמת עם המשתמש. התפקיד שלך הוא לנתח ארוחות בצורה מקצועית.
1. עבור כל ארוחה (טקסט או תמונה): ציין קלוריות, חלבון, פחמימה ושומן.
2. מכיוון שאתה זוכר את ההיסטוריה, אם המשתמש מוסיף פרטים או מתקן אותך ("שכחתי להגיד שהיה גם רוטב"), התייחס לזה בשיחה.
3. חוק חשוב: בסוף כל הודעה שבה חישבת ערכים של ארוחה חדשה (או רכיב חדש שהתווסף), חובה להוסיף שורה בפורמט הבא בדיוק כדי שהמערכת תשמור אותה:
DATA: calories=X, protein=X, carbs=X, fat=X
4. אם המשתמש רק מדבר איתך, שואל שאלה כללית או מתקן משהו בלי להוסיף ערכים חדשים - אל תוסיף את שורת ה-DATA.
5. אל תציב מעצמך יעדים קלוריים (כמו 2200 קלוריות) אלא אם המשתמש ביקש זאת במפורש.
"""

model = genai.GenerativeModel('models/gemini-2.5-flash', system_instruction=system_instruction)

# יצירת המקלדת עם שני קיצורי הדרך
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_summary = types.KeyboardButton('🍎 סכם לי את היום')
    btn_delete = types.KeyboardButton('❌ מחק ארוחה אחרונה')
    markup.add(btn_summary, btn_delete)
    return markup

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/' + TELEGRAM_TOKEN)
    return "Webhook setup complete!", 200

@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    if str(message.chat.id) != str(ALLOWED_USER_ID).strip():
        return

    # 1. טיפול בכפתור סכום יום
    if message.text == '🍎 סכם לי את היום':
        s = get_daily_summary(str(message.chat.id))
        if s[0]:
            msg = f"📊 סיכום ליום {datetime.now().strftime('%d/%m')}:\n\n"
            msg += f"🔥 קלוריות: {s[0]:.1f}\n💪 חלבון: {s[1]:.1f}ג'\n🍞 פחמימות: {s[2]:.1f}ג'\n🥑 שומן: {s[3]:.1f}ג'"
            bot.reply_to(message, msg, reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "עוד לא רשמת כלום היום.", reply_markup=get_main_keyboard())
        return

    # 2. טיפול בכפתור מחק ארוחה אחרונה
    if message.text == '❌ מחק ארוחה אחרונה':
        deleted_meal_desc = delete_last_meal(str(message.chat.id))
        if deleted_meal_desc:
            bot.reply_to(message, f"🗑️ המנה האחרונה נמחקה בהצלחה בהצלחה!\n(נמחקה: {deleted_meal_desc})", reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "לא נמצאה ארוחה למחיקה.", reply_markup=get_main_keyboard())
        return

    # 3. ניהול שיחה חכמה עם זיכרון
    bot.send_chat_action(message.chat.id, 'typing')
    
    # טעינת היסטוריית השיחה ממסד הנתונים
    history_context = get_chat_context(str(message.chat.id))
    chat_session = model.start_chat(history=history_context)
    
    user_text = message.text if message.text else "[שלח תמונה]"
    prompt = message.text if message.text else "נתח את התמונה הזו:"
    content = [prompt]
    
    if message.photo:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open("temp.jpg", "wb") as f: f.write(downloaded_file)
        content.append(Image.open("temp.jpg"))

    try:
        # שליחת ההודעה בתוך סשן הצ'אט שזוכר הכל
        response = chat_session.send_message(content).text
        bot.reply_to(message, response, reply_markup=get_main_keyboard())
        
        # שמירת ההודעות בהיסטוריית הצ'אט (לפעם הבאה)
        save_chat_message(str(message.chat.id), 'user', user_text)
        save_chat_message(str(message.chat.id), 'model', response)
        
        # חילוץ נתונים לשמירה בטבלת הארוחות במידה ויש ארוחה חדשה
        if "DATA:" in response:
            try:
                parts = response.split("DATA:")[1].strip().split(",")
                data = {p.split("=")[0].strip(): float(p.split("=")[1]) for p in parts}
                # ננסה להשתמש בטקסט של המשתמש כתיאור המנה
                data['description'] = message.text if message.text else "מנה מתמונה"
                save_meal(str(message.chat.id), data)
            except: pass
            
    except Exception as e:
        bot.reply_to(message, f"שגיאה: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
