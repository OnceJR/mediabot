import asyncio
import logging
import os
import html
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
# TU NUEVO TOKEN
TOKEN = '8849830719:AAF9u-rnhezgXzg-iTQ26I71sjOXaFx43t0'

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
    # Obtenemos quién lo envió (Username o Nombre Completo)
    user = message.from_user
    if user.username:
        sender_name = f"@{user.username}"
    else:
        sender_name = user.full_name
        
    # Escapamos caracteres especiales para evitar errores con HTML y armamos la firma
    sender_name = html.escape(sender_name)
    firma = f"\n\n<i>Enviado por: {sender_name}</i>"

    # Extraemos el texto original (si tiene) manteniendo su formato y le sumamos la firma
    original_caption = message.html_text if message.html_text else ""
    new_caption = original_caption + firma

    # Copiamos el archivo al mismo grupo/tema, pero inyectando nuestro nuevo texto
    await message.copy_to(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        caption=new_caption,
        parse_mode="HTML"
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
        asyncio.create_task(process_album(message.chat.id, group_id, message.message_thread_id))

    album_cache[group_id].append(message)

async def process_album(chat_id: int, group_id: str, thread_id: int | None):
    await asyncio.sleep(0.5)

    messages = album_cache.pop(group_id, [])
    if not messages:
        return

    # Obtenemos el autor del primer archivo del álbum
    user = messages[0].from_user
    if user.username:
        sender_name = f"@{user.username}"
    else:
        sender_name = user.full_name
        
    sender_name = html.escape(sender_name)
    firma = f"\n\n<i>Enviado por: {sender_name}</i>"

    media_group = []
    
    for i, msg in enumerate(messages):
        # Mantenemos el formato del texto original
        original_caption = msg.html_text if msg.html_text else ""
        
        # Solo le ponemos la firma a la primera foto/video del álbum
        if i == 0:
            new_caption = original_caption + firma
        else:
            new_caption = original_caption

        if msg.photo:
            media_group.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=new_caption, parse_mode="HTML"))
        elif msg.video:
            media_group.append(InputMediaVideo(media=msg.video.file_id, caption=new_caption, parse_mode="HTML"))
        elif msg.document:
            media_group.append(InputMediaDocument(media=msg.document.file_id, caption=new_caption, parse_mode="HTML"))
        elif msg.audio:
            media_group.append(InputMediaAudio(media=msg.audio.file_id, caption=new_caption, parse_mode="HTML"))

    if media_group:
        try:
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