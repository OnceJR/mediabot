import asyncio
import logging
import os
from typing import Dict

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError, TelegramAPIError

# ==========================================
# 1. CONFIGURACIÓN Y VARIABLES GLOBALES
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8527819825:AAGxLaJtaevQsvubUVaVsd2BgdnHeNDK3_o)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://carlosjrpelegrina_db_user:1DNyN9AFa9bh1tCr@cluster0.haf2f1l.mongodb.net")
PORT = int(os.getenv("PORT", 8080)) # Puerto requerido por Render

# Clientes y diccionarios globales
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.bot_manager  # Base de datos llamada 'bot_manager'
bots_collection = db.bots   # Colección para configuraciones de bots
media_collection = db.media # Colección para registro de anti-duplicados

# Memoria temporal para gestionar las tareas asíncronas de los bots
# Estructura: { bot_id: {"task": asyncio.Task, "bot": Bot} }
active_bots_tasks: Dict[int, Dict] = {}

master_dp = Dispatcher()
child_dp = Dispatcher()

# ==========================================
# 2. LÓGICA DE LOS BOTS HIJOS (ESPEJO & ANTI-DUPLICADOS)
# ==========================================
@child_dp.message(F.photo | F.video | F.document)
async def forward_media(message: Message, bot: Bot):
    """Filtra y reenvía multimedia verificando duplicados y múltiples destinos."""
    
    if message.chat.type not in ["group", "supergroup"]:
        return # Solo operamos en grupos

    # 1. Extraer el identificador único del archivo
    file_unique_id = None
    if message.photo:
        file_unique_id = message.photo[-1].file_unique_id
    elif message.video:
        file_unique_id = message.video.file_unique_id
    elif message.document:
        file_unique_id = message.document.file_unique_id

    if not file_unique_id:
        return

    # 2. Comprobar sistema Anti-Duplicados en MongoDB
    is_duplicate = await media_collection.find_one({
        "bot_id": bot.id, 
        "file_unique_id": file_unique_id
    })
    
    if is_duplicate:
        logger.info(f"[Anti-Spam] Archivo duplicado ignorado en el bot {bot.id}")
        return

    # Registrar el nuevo archivo en la BD
    await media_collection.insert_one({
        "bot_id": bot.id,
        "file_unique_id": file_unique_id
    })

    # 3. Obtener el dueño y los destinos extra
    bot_data = await bots_collection.find_one({"_id": bot.id})
    if not bot_data:
        return
    
    # Destinos = Dueño + Targets configurados (eliminando posibles duplicados con set)
    targets = list(set([bot_data["owner_id"]] + bot_data.get("targets", [])))

    # 4. Reenviar a todos los destinos
    for target_id in targets:
        try:
            # Usamos copy_to para que parezca que el bot lo envía directamente, 
            # o puedes cambiarlo a message.forward(chat_id=target_id)
            await message.copy_to(chat_id=target_id)
            logger.info(f"Media enviada al destino {target_id} vía bot {bot.id}")
        except TelegramAPIError as e:
            logger.error(f"Fallo al enviar media a {target_id} (Bot {bot.id}): {e}")


# ==========================================
# 3. LÓGICA DEL BOT PRINCIPAL (GESTOR)
# ==========================================
@master_dp.message(CommandStart())
async def cmd_start(message: Message):
    text = (
        "👋 ¡Bienvenido al **Bot Gestor Enterprise**!\n\n"
        "Envía un **Token** de @BotFather para iniciar tu propio bot extractor.\n\n"
        "**Comandos disponibles:**\n"
        "• `/mybots` - Lista tus bots y sus IDs\n"
        "• `/add <bot_id> <chat_id>` - Añade un chat/canal destino\n"
        "• `/del <bot_id> <chat_id>` - Elimina un destino"
    )
    await message.answer(text)

@master_dp.message(Command("mybots"))
async def cmd_mybots(message: Message):
    cursor = bots_collection.find({"owner_id": message.from_user.id})
    bots_list = await cursor.to_list(length=50)
    
    if not bots_list:
        await message.answer("❌ Aún no tienes bots en ejecución.")
        return
    
    text = "🤖 **Tus Bots Activos:**\n\n"
    for b in bots_list:
        targets_str = ", ".join(map(str, b.get('targets', []))) or "Ninguno"
        text += f"• **ID:** `{b['_id']}`\n"
        text += f"  Destinos extra: `{targets_str}`\n\n"
        
    await message.answer(text)

@master_dp.message(Command("add"))
async def cmd_add_target(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Uso correcto: `/add <bot_id> <chat_id>`\nEjemplo: `/add 123456789 -100123456789`")
        return
    
    try:
        bot_id, target_id = int(args[1]), int(args[2])
    except ValueError:
        await message.answer("❌ Los IDs deben ser números.")
        return
        
    # Verificar propiedad del bot
    bot_data = await bots_collection.find_one({"_id": bot_id, "owner_id": message.from_user.id})
    if not bot_data:
        await message.answer("❌ No eres el dueño de ese bot o no existe.")
        return
        
    await bots_collection.update_one({"_id": bot_id}, {"$addToSet": {"targets": target_id}})
    await message.answer(f"✅ Destino `{target_id}` añadido al bot `{bot_id}` exitosamente.")

@master_dp.message(Command("del"))
async def cmd_del_target(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Uso correcto: `/del <bot_id> <chat_id>`")
        return
    
    try:
        bot_id, target_id = int(args[1]), int(args[2])
    except ValueError:
        return
        
    await bots_collection.update_one({"_id": bot_id, "owner_id": message.from_user.id}, {"$pull": {"targets": target_id}})
    await message.answer(f"🗑 Destino `{target_id}` eliminado.")

@master_dp.message(F.text)
async def receive_token(message: Message):
    token = message.text.strip()
    if len(token.split(':')) != 2:
        return
        
    msg_status = await message.answer("🔄 Verificando e iniciando el bot en los servidores...")
    new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    
    try:
        bot_info = await new_bot.get_me()
        bot_id = bot_info.id
        
        # Verificar si ya está corriendo en memoria
        if bot_id in active_bots_tasks:
            await msg_status.edit_text("⚠️ Este bot ya está en ejecución.")
            await new_bot.session.close()
            return
            
        # Guardar/Actualizar en MongoDB
        await bots_collection.update_one(
            {"_id": bot_id},
            {"$set": {"token": token, "owner_id": message.from_user.id}},
            upsert=True
        )
        
        # Iniciar tarea asíncrona
        task = asyncio.create_task(child_dp.start_polling(new_bot, handle_signals=False))
        active_bots_tasks[bot_id] = {"task": task, "bot": new_bot}
        
        await msg_status.edit_text(
            f"✅ **Bot @{bot_info.username} en línea.**\n"
            f"Tu ID de bot es: `{bot_id}`.\n\n"
            "Usa `/mybots` para gestionarlo o `/add` para añadir canales/grupos de destino."
        )
        
    except TelegramUnauthorizedError:
        await msg_status.edit_text("❌ Token inválido o revocado.")
        await new_bot.session.close()
    except Exception as e:
        logger.error(f"Error fatal con el token: {e}")
        await new_bot.session.close()


# ==========================================
# 4. SERVIDOR WEB (RENDER & UPTIMEROBOT)
# ==========================================
async def ping_handler(request):
    """Endpoint simple para que UptimeRobot sepa que el sistema está vivo."""
    return web.Response(text="Bot Manager is alive and running!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Servidor web escuchando en el puerto {PORT}")


# ==========================================
# 5. ENTRY POINT Y RECARGA DESDE BD
# ==========================================
async def restore_bots():
    """Al iniciar, lee la BD y enciende todos los bots registrados previamente."""
    logger.info("Restaurando bots desde MongoDB...")
    cursor = bots_collection.find({})
    async for bot_data in cursor:
        bot_id = bot_data["_id"]
        token = bot_data["token"]
        
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        try:
            await new_bot.get_me() # Verificamos que el token siga vivo
            task = asyncio.create_task(child_dp.start_polling(new_bot, handle_signals=False))
            active_bots_tasks[bot_id] = {"task": task, "bot": new_bot}
            logger.info(f"Bot {bot_id} restaurado correctamente.")
        except TelegramUnauthorizedError:
            logger.warning(f"El token del bot {bot_id} fue revocado. Ignorando.")
            await new_bot.session.close()

async def main():
    # 1. Iniciamos el servidor web para Render/UptimeRobot
    await start_web_server()
    
    # 2. Restauramos bots existentes de la BD
    await restore_bots()
    
    # 3. Iniciamos el Master Bot
    master_bot = Bot(token=MASTER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    logger.info("Iniciando el Master Bot...")
    
    try:
        await master_dp.start_polling(master_bot)
    finally:
        logger.info("Apagando sistema de forma segura (Graceful Shutdown)...")
        # Cerrar conexiones de los hijos
        for bot_id, data in active_bots_tasks.items():
            data["task"].cancel()
            await data["bot"].session.close()
            
        await master_bot.session.close()
        db_client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Script detenido.")
        
