import os
import telebot
import sqlite3
from flask import Flask, request
import google.generativeai as genai
from datetime import datetime
from telebot import types

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
    c.execute('''CREATE TABLE IF NOT EXISTS meals 
                 (user_id TEXT, date TEXT, time TEXT, description TEXT, calories REAL, protein REAL, carbs REAL, fat REAL)''')
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

init_db()

# --- הגדרת המערכת החדשה (בלי 2200 קלוריות) ---
system_instruction = """
אתה עוזר תזונה מקצועי. התפקיד שלך הוא לנתח ארוחות בצורה יבשה ומדויקת.
1. עבור כל ארוחה (טקסט או תמונה): ציין קלוריות, חלבון, פחמימה ושומן.
2. אל תציב יעדים (כמו 2200) ואל תתן עצות תזונתיות אלא אם נתבקשת.
3. בסיכום היומי: הצג את סך כל הערכים שנצרכו היום בצורה ברורה.
4. חשוב: בסוף כל ניתוח ארוחה, כתוב את הנתונים בשורה אחת בפורמט הבא בדיוק כדי שאוכל לשמור אותם: 
DATA: calories=X, protein=X, carbs=X, fat=X
"""

model = genai.GenerativeModel('models/gemini-2.5-flash', system_instruction=system_instruction)

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(types.KeyboardButton('🍎 סכם לי את היום'))
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

    if message.text == '🍎 סכם לי את היום':
        s = get_daily_summary(str(message.chat.id))
        if s[0]:
            msg = f"📊 סיכום ליום {datetime.now().strftime('%d/%m')}:\n\n"
            msg += f"🔥 קלוריות: {s[0]:.1f}\n💪 חלבון: {s[1]:.1f}ג'\n🍞 פחמימות: {s[2]:.1f}ג'\n🥑 שומן: {s[3]:.1f}ג'"
            bot.reply_to(message, msg, reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "עוד לא רשמת כלום היום.", reply_markup=get_main_keyboard())
        return

    # ניתוח ארוחה רגיל
    prompt = "נתח את הארוחה הזו: " + (message.text if message.text else "")
    content = [prompt]
    if message.photo:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open("temp.jpg", "wb") as f: f.write(downloaded_file)
        from PIL import Image
        content.append(Image.open("temp.jpg"))

    try:
        response = model.generate_content(content).text
        bot.reply_to(message, response, reply_markup=get_main_keyboard())
        
        # חילוץ נתונים לשמירה במסד הנתונים
        if "DATA:" in response:
            try:
                parts = response.split("DATA:")[1].strip().split(",")
                data = {p.split("=")[0].strip(): float(p.split("=")[1]) for p in parts}
                save_meal(str(message.chat.id), data)
            except: pass
    except Exception as e:
        bot.reply_to(message, f"שגיאה: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
