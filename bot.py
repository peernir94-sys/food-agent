import os
import telebot
from flask import Flask, request
import google.generativeai as genai

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
ALLOWED_USER_ID = os.environ.get('ALLOWED_USER_ID')

# התיקון הקריטי: threaded=False אומר לבוט לטפל בהודעה מיד ולא ברקע
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)
genai.configure(api_key=GEMINI_API_KEY)

system_instruction = """
אתה סוכן AI אישי לתזונה. המטרה שלך היא לעזור למשתמש לעמוד ביעד של 2,200 קלוריות ביום, המחולקות ל-4 ארוחות, תוך שמירה על מסת שריר.
המשתמש יכתוב לך בשפה חופשית מה הוא אכל, מאיזו מסעדה הוא הזמין, או יתייעץ איתך לפני ארוחה.

התפקיד שלך:
1. להעריך את כמות הקלוריות והערכים התזונתיים (חלבון, פחמימה, שומן) מתוך הטקסט החופשי.
2. לתת אומדן של הקלוריות שהוא צרך בארוחה הזו.
3. לייעץ ולתת לו תמונת מצב קצרה לגבי המשך היום כדי שלא יחרוג מהיעד.
דבר בעברית, קצר, ענייני ובגובה העיניים.
"""

model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_instruction)

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

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    print(f"Received message from ID: {message.chat.id}")
    
    # שיפרנו את ההגנה כדי שרווחים בטעות לא יהרסו את הזיהוי
    if str(message.chat.id) != str(ALLOWED_USER_ID).strip():
        bot.reply_to(message, "סליחה, הבוט הזה הוא סוכן אישי ואינו פתוח לציבור. ⛔")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    
    try:
        response = model.generate_content(message.text)
        bot.reply_to(message, response.text)
        print("Successfully replied!")
    except Exception as e:
        print(f"Error with AI: {e}")
        bot.reply_to(message, "משהו השתבש בחיבור למוח שלי... אפשר לנסות שוב?")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
