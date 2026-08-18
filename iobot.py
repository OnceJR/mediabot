import asyncio
import logging
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
# Filtro personalizado para verificar si el usuario está autorizado
class IsAuthorized(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in AUTHORIZED_IDS


# ================= HANDLERS DEL BOT =================

# 1. HANDLER PARA MEDIOS INDIVIDUALES (Sin media_group_id)
@dp.message(
    IsAuthorized(), 
    F.media_group_id.is_(None), 
    F.content_type.in_({'photo', 'video', 'document', 'audio', 'voice', 'animation'})
)
async def handle_single_media(message: Message):
    # Copia y envía el mensaje exactamente igual al mismo chat
    await message.copy_to(chat_id=message.chat.id)
    # Borra el original
    try:
        await message.delete()
    except Exception as e:
        logging.error(f"Error borrando mensaje individual: {e}")


# 2. HANDLER PARA ÁLBUMES (Con media_group_id)
@dp.message(
    IsAuthorized(), 
    F.media_group_id
)
async def handle_album(message: Message):
    group_id = message.media_group_id

    # Si es el primer elemento del álbum, creamos la lista y lanzamos una tarea en segundo plano
    if group_id not in album_cache:
        album_cache[group_id] = []
        asyncio.create_task(process_album(message.chat.id, group_id))

    # Añadimos el mensaje actual al búfer del álbum
    album_cache[group_id].append(message)


async def process_album(chat_id: int, group_id: str):
    # Esperamos medio segundo para dar tiempo a que lleguen todas las partes del álbum
    await asyncio.sleep(0.5)

    # Extraemos y limpiamos el álbum del caché
    messages = album_cache.pop(group_id, [])
    if not messages:
        return

    media_group = []
    
    # Reconstruimos el álbum para el bot
    for msg in messages:
        caption = msg.caption if msg.caption else None
        caption_entities = msg.caption_entities

        if msg.photo:
            # Tomamos la foto con mayor resolución (la última de la lista)
            media_group.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption, caption_entities=caption_entities))
        elif msg.video:
            media_group.append(InputMediaVideo(media=msg.video.file_id, caption=caption, caption_entities=caption_entities))
        elif msg.document:
            media_group.append(InputMediaDocument(media=msg.document.file_id, caption=caption, caption_entities=caption_entities))
        elif msg.audio:
            media_group.append(InputMediaAudio(media=msg.audio.file_id, caption=caption, caption_entities=caption_entities))

    # Enviamos el álbum completo
    if media_group:
        try:
            await bot.send_media_group(chat_id=chat_id, media=media_group)
        except Exception as e:
            logging.error(f"Error enviando el álbum: {e}")

    # Borramos los mensajes originales del usuario (iteramos sobre todos los mensajes del álbum)
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            logging.error(f"No se pudo borrar el mensaje del álbum: {e}")


# ================= SERVIDOR WEB FALSO PARA RENDER =================
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render asigna dinámicamente un puerto a través de la variable de entorno PORT.
    # Si no existe, usamos 10000 por defecto.
    import os
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Servidor web iniciado en el puerto {port}")


# ================= EJECUCIÓN PRINCIPAL =================
async def main():
    # Iniciamos el servidor web falso en segundo plano
    asyncio.create_task(web_server())
    
    print("🤖 Bot Iniciado y escuchando mensajes...")
    # Comenzamos a escuchar mensajes del bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Configuramos el log para ver errores en la consola
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())