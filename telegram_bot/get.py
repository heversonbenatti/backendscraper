import asyncio
from telegram import Bot

async def get_chat_id():
    bot = Bot(token="8363912617:AAGe1NzPkNjvQ_zo4dnUT7Ycr9y98bL-0qA")
    updates = await bot.get_updates()
    
    for update in updates:
        if update.message:
            print(f"Seu Chat ID é: {update.message.chat.id}")
            break

asyncio.run(get_chat_id())