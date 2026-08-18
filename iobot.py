import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, 
    InputMediaPhoto, 
    InputMediaVideo, 
    InputMediaDocument, 
    InputMediaAudio
)
from aiogram.filters import Filter

# ================= CONFIGURACIÓN =================
TOKEN = '8689803553:AAEsQ6Pvwxnil8g8feUxnRuMBEL5D0r9U1Q'

# Lista de IDs de los usuarios designados
AUTHORIZED_IDS = [
    8748956307, 8764734838, 6630522163, 8831263313, 8556221763, 
    5142196200, 7452819858, 8803304819, 8266066936, 8985586526
]

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Búfer temporal para agrupar los mensajes que forman parte de un álbum
album_cache = {}

# ================= FILTROS =================
class IsAuthorized(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in AUTHORIZED_IDS


# ================= HANDLERS DEL BOT =================

# 1. HANDLER PARA MEDIOS INDIVIDUALES
@dp.message(
    IsAuthorized(), 
    F.media_group_id.is_(None), 
    F.content_type.in_({'photo', 'video', 'document', 'audio', 'voice', 'animation'})
)
async def handle_single_media(message: Message):
    # SOLUCIÓN AQUÍ: Añadimos message_thread_id para que respete los Temas del grupo
    await message.copy_to(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id
    )
    try:
        await message.delete()
    except Exception as e:
        logging.error(f"Error borrando mensaje individual: {e}")

# 2. HANDLER PARA ÁLBUMES
@dp.message(
    IsAuthorized(), 
    F.media_group_id
)
async def handle_album(message: Message):
    group_id = message.media_group_id

    if group_id not in album_cache:
        album_cache[group_id] = []
        # Pasamos también el ID del tema (message_thread_id) a la función
        asyncio.create_task(process_album(message.chat.id, group_id, message.message_thread_id))

    album_cache[group_id].append(message)

# SOLUCIÓN AQUÍ: Recibimos el thread_id
async def process_album(chat_id: int, group_id: str, thread_id: int | None):
    await asyncio.sleep(0.5)

    messages = album_cache.pop(group_id, [])
    if not messages:
        return

    media_group = []
    
    for msg in messages:
        caption = msg.caption if msg.caption else None
        caption_entities = msg.caption_entities

        if msg.photo:
            media_group.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption, caption_entities=caption_entities))
        elif msg.video:
            media_group.append(InputMediaVideo(media=msg.video.file_id, caption=caption, caption_entities=caption_entities))
        elif msg.document:
            media_group.append(InputMediaDocument(media=msg.document.file_id, caption=caption, caption_entities=caption_entities))
        elif msg.audio:
            media_group.append(InputMediaAudio(media=msg.audio.file_id, caption=caption, caption_entities=caption_entities))

    if media_group:
        try:
            # SOLUCIÓN AQUÍ: Usamos el thread_id al enviar el álbum
            await bot.send_media_group(
                chat_id=chat_id, 
                media=media_group,
                message_thread_id=thread_id
            )
        except Exception as e:
            logging.error(f"Error enviando el álbum: {e}")

    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            logging.error(f"No se pudo borrar el mensaje del álbum: {e}")


# ================= SERVIDOR WEB (UPTIMEROBOT & RENDER) =================
async def handle(request):
    return web.Response(text="Bot is running! UptimeRobot ping successful.", status=200)

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Servidor web iniciado en el puerto {port}")


# ================= EJECUCIÓN PRINCIPAL =================
async def main():
    asyncio.create_task(web_server())
    print("🤖 Bot Iniciado y escuchando mensajes...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())