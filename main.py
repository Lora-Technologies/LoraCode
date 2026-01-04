import os
import discord
from discord.ext import commands
import openai
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# API anahtarlarını al
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

# OpenAI API anahtarını ayarla
openai.api_key = OPENAI_API_KEY

# Bot'u oluştur
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} olarak giriş yapıldı')
    print(f'Bot hazır!')

@bot.event
async def on_message(message):
    # Bot'un kendi mesajlarını yoksay
    if message.author == bot.user:
        return
    
    # Sadece belirtilen kanalda çalış
    if message.channel.id != CHANNEL_ID:
        return
    
    # Yazıyor göstergesi
    async with message.channel.typing():
        try:
            # OpenAI API'ye istek gönder
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": message.content}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            # Yanıtı al
            reply = response.choices[0].message.content
            
            # Mesaj uzunluğu Discord limitini aşarsa böl
            if len(reply) > 2000:
                chunks = [reply[i:i+2000] for i in range(0, len(reply), 2000)]
                for chunk in chunks:
                    await message.reply(chunk)
            else:
                await message.reply(reply)
                
        except openai.error.RateLimitError:
            await message.reply("⚠️ API rate limit'e ulaşıldı. Lütfen biraz sonra tekrar deneyin.")
        except openai.error.APIError as e:
            await message.reply(f"❌ OpenAI API hatası: {str(e)}")
        except Exception as e:
            await message.reply(f"❌ Bir hata oluştu: {str(e)}")

# Bot'u çalıştır
bot.run(DISCORD_TOKEN)
