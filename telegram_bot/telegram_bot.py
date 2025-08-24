import os
import time
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional

import telegram
from telegram import Bot
from sqlalchemy import create_engine, select, and_
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramPriceBot:
    def __init__(self):
        # ✅ SEGURO - Usando variáveis de ambiente
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID') 
        self.database_url = os.getenv('DATABASE_URL')
        
        if not all([self.bot_token, self.chat_id, self.database_url]):
            raise ValueError("Variáveis de ambiente necessárias: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DATABASE_URL")
        
        # Inicializar bot e database
        self.bot = Bot(token=self.bot_token)
        self.engine = create_engine(self.database_url)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        
        # Importar tabelas (assumindo que são as mesmas do seu scraper.py)
        from sqlalchemy import MetaData, Table
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.engine)
        self.products = self.metadata.tables['products']
        self.prices = self.metadata.tables['prices']
    
    async def send_message(self, message: str):
        """Envia mensagem via Telegram"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            logger.info("Mensagem enviada com sucesso")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
    
    def get_recent_price_drops(self, hours: int = 1) -> List[Dict]:
        """Busca produtos que tiveram queda de preço nas últimas horas"""
        try:
            # Subquery para pegar o preço anterior de cada produto
            subquery = select([
                self.prices.c.product_id,
                self.prices.c.price.label('current_price'),
                self.prices.c.price_changed_at
            ]).where(
                self.prices.c.price_changed_at >= datetime.now() - timedelta(hours=hours)
            ).alias('recent_prices')
            
            # Query principal para buscar produtos com mudança de preço
            query = select([
                self.products.c.name,
                self.products.c.website,
                self.products.c.category,
                self.products.c.product_link,
                subquery.c.current_price,
                subquery.c.price_changed_at
            ]).select_from(
                self.products.join(subquery, self.products.c.id == subquery.c.product_id)
            ).order_by(subquery.c.price_changed_at.desc())
            
            results = []
            with self.engine.connect() as conn:
                rows = conn.execute(query).fetchall()
                
                for row in rows:
                    # Para cada produto, buscar o preço anterior para calcular a diferença
                    prev_price_query = select([self.prices.c.price]).where(
                        and_(
                            self.prices.c.product_id == self.get_product_id(row.name, row.website),
                            self.prices.c.price_changed_at < row.price_changed_at
                        )
                    ).order_by(self.prices.c.price_changed_at.desc()).limit(1)
                    
                    prev_price_result = conn.execute(prev_price_query).scalar()
                    
                    if prev_price_result:
                        prev_price = float(prev_price_result)
                        current_price = float(row.current_price)
                        
                        # Só notifica se houve REDUÇÃO de preço
                        if current_price < prev_price:
                            price_diff = prev_price - current_price
                            percentage = (price_diff / prev_price) * 100
                            
                            results.append({
                                'name': row.name,
                                'website': row.website,
                                'category': row.category,
                                'product_link': row.product_link,
                                'previous_price': prev_price,
                                'current_price': current_price,
                                'price_diff': price_diff,
                                'percentage': percentage,
                                'changed_at': row.price_changed_at
                            })
            
            return results
            
        except Exception as e:
            logger.error(f"Erro ao buscar quedas de preço: {e}")
            return []
    
    def get_product_id(self, name: str, website: str) -> Optional[int]:
        """Helper para buscar ID do produto"""
        try:
            with self.engine.connect() as conn:
                query = select([self.products.c.id]).where(
                    and_(
                        self.products.c.name == name,
                        self.products.c.website == website
                    )
                )
                return conn.execute(query).scalar()
        except:
            return None
    
    def format_price_drop_message(self, drops: List[Dict]) -> str:
        """Formata mensagem com as quedas de preço"""
        if not drops:
            return None
        
        message = "🚨 <b>ALERTAS DE QUEDA DE PREÇO!</b> 🚨\n\n"
        
        for drop in drops:
            emoji = "📱" if "smartphone" in drop['category'].lower() else "💻"
            
            message += f"{emoji} <b>{drop['name'].title()}</b>\n"
            message += f"🏪 {drop['website'].title()}\n"
            message += f"💰 De <s>R$ {drop['previous_price']:.2f}</s> para <b>R$ {drop['current_price']:.2f}</b>\n"
            message += f"📉 Economia: <b>R$ {drop['price_diff']:.2f} ({drop['percentage']:.1f}%)</b>\n"
            
            if drop['product_link']:
                message += f"🔗 <a href='{drop['product_link']}'>Ver produto</a>\n"
            
            message += f"⏰ {drop['changed_at'].strftime('%d/%m/%Y às %H:%M')}\n\n"
        
        return message
    
    async def check_and_notify(self):
        """Verifica quedas de preço e envia notificações"""
        logger.info("Verificando quedas de preço...")
        
        drops = self.get_recent_price_drops(hours=1)
        
        if drops:
            message = self.format_price_drop_message(drops)
            if message:
                await self.send_message(message)
                logger.info(f"Notificação enviada para {len(drops)} produtos")
        else:
            logger.info("Nenhuma queda de preço detectada")
    
    async def send_daily_summary(self):
        """Envia resumo diário das melhores ofertas"""
        logger.info("Enviando resumo diário...")
        
        drops = self.get_recent_price_drops(hours=24)
        
        if drops:
            # Ordena por maior percentual de desconto
            drops.sort(key=lambda x: x['percentage'], reverse=True)
            top_drops = drops[:5]  # Top 5 ofertas
            
            message = "📊 <b>RESUMO DIÁRIO - TOP 5 OFERTAS</b> 📊\n\n"
            
            for i, drop in enumerate(top_drops, 1):
                message += f"{i}. <b>{drop['name'][:50]}...</b>\n"
                message += f"   💰 R$ {drop['current_price']:.2f} ({drop['percentage']:.1f}% OFF)\n"
                message += f"   🏪 {drop['website'].title()}\n\n"
            
            await self.send_message(message)
        else:
            await self.send_message("📊 <b>RESUMO DIÁRIO</b>\n\nNenhuma queda significativa de preço hoje.")
    
    async def run_monitoring(self):
        """Loop principal de monitoramento"""
        logger.info("Bot iniciado! Monitorando preços...")
        
        last_daily_summary = datetime.now().date()
        
        while True:
            try:
                # Verifica quedas de preço a cada 30 minutos
                await self.check_and_notify()
                
                # Envia resumo diário às 20h
                now = datetime.now()
                if (now.hour == 20 and now.minute < 30 and 
                    now.date() > last_daily_summary):
                    await self.send_daily_summary()
                    last_daily_summary = now.date()
                
                # Aguarda 30 minutos
                await asyncio.sleep(1800)  # 30 minutos
                
            except Exception as e:
                logger.error(f"Erro no monitoramento: {e}")
                await asyncio.sleep(300)  # 5 minutos em caso de erro

# Função para obter seu chat ID
async def get_my_chat_id():
    """Helper para descobrir seu chat ID - ✅ SEGURO"""
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("❌ Configure a variável TELEGRAM_BOT_TOKEN primeiro!")
        return
        
    bot = Bot(token=bot_token)
    
    print("Envie qualquer mensagem para o bot e execute este comando...")
    updates = await bot.get_updates()
    
    if updates:
        for update in updates[-5:]:  # Últimas 5 mensagens
            if update.message:
                print(f"Chat ID: {update.message.chat.id}")
                print(f"Nome: {update.message.from_user.first_name}")
                print("---")

if __name__ == "__main__":
    # Para descobrir seu chat ID:
    # asyncio.run(get_my_chat_id())
    
    # Para rodar o bot:
    bot = TelegramPriceBot()
    asyncio.run(bot.run_monitoring())