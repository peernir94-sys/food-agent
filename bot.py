import os
import telebot
from flask import Flask, request
import google.generativeai as genai
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
ALLOWED_USER_ID = os.environ.get('ALLOWED_USER_ID')

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)
genai.configure(api_key=GEMINI_API_KEY)

# הגדרת המערכת החדשה לפי הדרישות שלך
system_instruction = """
אתה סוכן תזונה אישי חכם. המשתמש שואף ל-2,200 קלוריות ביום.
התפקיד שלך:
1. נתח טקסט או תמונות של אוכל.
2. עבור כל ארוחה: ציין ערכים (קלוריות, חלבון, פחמימה, שומן).
3. אל תגיד כמה 'נשאר'. תגיד תמיד כמה נצרך 'עד עכשיו' באותו יום (סה"כ מצטבר).
4. תמיד תציין את שעת הארוחה.
5. שמור על טון ענייני, קצר ומקצועי בעברית.
"""

model = genai.GenerativeModel('models/gemini-1.5-flash', system_instruction=system_instruction)

# זיכרון פשוט (לצורך חישוב יומי - מתאפס כשהשרת עובר ריסטארט ב-Render)
# בהמשך נוכל לחבר למסד נתונים אם תרצה זיכרון לטווח ארוך
user_daily_log = [] 

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

# פונקציה לטיפול בטקסט ובתמונות
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    if str(message.chat.id) != str(ALLOWED_USER_ID).strip():
        bot.reply_to(message, "סליחה, הבוט הזה חסום.")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    
    prompt = "נתח את הארוחה הזו ועדכן את הספירה היומית: "
    if message.text:
        prompt += message.text
        content = [prompt]
    else:
        # טיפול בתמונה
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open("temp_img.jpg", "wb") as new_file:
            new_file.write(downloaded_file)
        
        from PIL import Image
        img = Image.open("temp_img.jpg")
        content = [prompt, img]

    try:
        response = model.generate_content(content)
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, f"שגיאה: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
