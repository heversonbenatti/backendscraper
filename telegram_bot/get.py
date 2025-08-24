import asyncio
import os
from telegram import Bot

async def get_chat_id():
    # ✅ SEGURO - Usando variável de ambiente
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        print("❌ Configure a variável de ambiente TELEGRAM_BOT_TOKEN primeiro!")
        return
    
    bot = Bot(token=bot_token)
    updates = await bot.get_updates()
    
    for update in updates:
        if update.message:
            print(f"Seu Chat ID é: {update.message.chat.id}")
            break

if __name__ == "__main__":
    asyncio.run(get_chat_id())