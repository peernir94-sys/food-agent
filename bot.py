import os
import telebot
from flask import Flask, request
import google.generativeai as genai

# משיכת מפתחות הגישה מתוך משתני סביבה (כדי שיהיה מאובטח בענן)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL') # זו תהיה הכתובת שנקבל מ-Render

# אתחול הבוט של טלגרם ואפליקציית הפלאסק
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# אתחול מודל ה-AI
genai.configure(api_key=GEMINI_API_KEY)

# כאן אנחנו מגדירים את ה"מוח" וההקשר של הסוכן
system_instruction = """
אתה סוכן AI אישי לתזונה. המטרה שלך היא לעזור למשתמש לעמוד ביעד של 2,200 קלוריות ביום, המחולקות ל-4 ארוחות, תוך שמירה על מסת שריר.
המשתמש יכתוב לך בשפה חופשית מה הוא אכל, מאיזו מסעדה הוא הזמין, או יתייעץ איתך לפני ארוחה.

התפקיד שלך:
1. להעריך את כמות הקלוריות והערכים התזונתיים (חלבון, פחמימה, שומן) מתוך הטקסט החופשי.
2. לתת אומדן של הקלוריות שהוא צרך בארוחה הזו.
3. לייעץ ולתת לו תמונת מצב קצרה לגבי המשך היום כדי שלא יחרוג מהיעד.
דבר בעברית, קצר, ענייני ובגובה העיניים.
"""

# יצירת מודל ה-AI עם ההנחיות שלנו
model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_instruction)

# נתיב קבלת ההודעות מטלגרם (ה-Webhook)
@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

# נתיב הגדרת ה-Webhook (נריץ אותו פעם אחת אחרי שהשרת באוויר)
@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/' + TELEGRAM_TOKEN)
    return "Webhook setup complete!", 200

# טיפול בכל הודעת טקסט שנכנסת
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_text = message.text
    
    # מראה למשתמש בטלגרם שהבוט "מקליד..." כדי שנדע שהוא חושב
    bot.send_chat_action(message.chat.id, 'typing')
    
    try:
        # שליחת הטקסט של המשתמש לסוכן ה-AI וקבלת תשובה
        response = model.generate_content(user_text)
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, "משהו השתבש בחיבור למוח שלי... אפשר לנסות שוב?")

if __name__ == "__main__":
    # הפעלת השרת על הפורט שהענן מספק
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
