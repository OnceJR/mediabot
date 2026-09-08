import asyncio
import logging
import os
from typing import Dict, Any

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError, TelegramAPIError

# ==========================================
# 1. CONFIGURACIÓN GLOBAL Y BASE DE DATOS
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8527819825:AAGxLaJtaevQsvubUVaVsd2BgdnHeNDK3_o")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://carlosjrpelegrina_db_user:1DNyN9AFa9bh1tCr@cluster0.haf2f1l.mongodb.net")
PORT = int(os.getenv("PORT", 8080))

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.bot_manager
bots_collection = db.bots
media_collection = db.media

active_bots_tasks: Dict[int, Dict] = {}

master_dp = Dispatcher()

DEFAULT_SETTINGS = {
    "photos": True,
    "videos": True,
    "docs": True,
    "is_paused": False
}

# ==========================================
# 2. LÓGICA DE LOS BOTS HIJOS (SIN DECORADORES)
# ==========================================
def get_child_menu(settings: Dict[str, Any]) -> InlineKeyboardMarkup:
    btn_photos = "🟢 Fotos" if settings.get("photos", True) else "🔴 Fotos"
    btn_videos = "🟢 Videos" if settings.get("videos", True) else "🔴 Videos"
    btn_docs = "🟢 Docs" if settings.get("docs", True) else "🔴 Docs"
    btn_pause = "⏸ Pausar Bot" if not settings.get("is_paused", False) else "▶️ Reanudar Bot"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=btn_photos, callback_data="toggle_photos"),
            InlineKeyboardButton(text=btn_videos, callback_data="toggle_videos"),
            InlineKeyboardButton(text=btn_docs, callback_data="toggle_docs")
        ],
        [InlineKeyboardButton(text=btn_pause, callback_data="toggle_pause")]
    ])

async def child_start(message: Message, bot: Bot):
    bot_data = await bots_collection.find_one({"_id": bot.id})
    if not bot_data or message.from_user.id != bot_data.get("owner_id"):
        return

    settings = bot_data.get("settings", DEFAULT_SETTINGS)
    text = (
        "⚙️ <b>Panel de Control del Extractor</b>\n\n"
        "Hola jefe. Desde aquí puedes configurar qué tipo de archivos debo extraer "
        "de los grupos. Usa los botones para encender o apagar los filtros."
    )
    await message.answer(text, reply_markup=get_child_menu(settings))

async def child_toggle_settings(callback: CallbackQuery, bot: Bot):
    bot_data = await bots_collection.find_one({"_id": bot.id})
    if not bot_data or callback.from_user.id != bot_data.get("owner_id"):
        await callback.answer("No tienes permisos.", show_alert=True)
        return

    settings = bot_data.get("settings", DEFAULT_SETTINGS)
    action = callback.data.split("_")[1]

    if action == "pause":
        settings["is_paused"] = not settings.get("is_paused", False)
        msg = "Bot pausado" if settings["is_paused"] else "Bot reanudado"
    else:
        settings[action] = not settings.get(action, True)
        msg = f"Filtro actualizado: {action}"

    await bots_collection.update_one({"_id": bot.id}, {"$set": {"settings": settings}})
    await callback.message.edit_reply_markup(reply_markup=get_child_menu(settings))
    await callback.answer(msg)

async def forward_media(message: Message, bot: Bot):
    if message.chat.type not in ["group", "supergroup"]:
        return

    bot_data = await bots_collection.find_one({"_id": bot.id})
    if not bot_data: return

    settings = bot_data.get("settings", DEFAULT_SETTINGS)
    if settings.get("is_paused", False): return

    file_unique_id = None
    if message.photo:
        if not settings.get("photos", True): return
        file_unique_id = message.photo[-1].file_unique_id
    elif message.video:
        if not settings.get("videos", True): return
        file_unique_id = message.video.file_unique_id
    elif message.document:
        if not settings.get("docs", True): return
        file_unique_id = message.document.file_unique_id

    if not file_unique_id: return

    is_duplicate = await media_collection.find_one({"bot_id": bot.id, "file_unique_id": file_unique_id})
    if is_duplicate: return

    await media_collection.insert_one({"bot_id": bot.id, "file_unique_id": file_unique_id})

    targets = list(set([bot_data["owner_id"]] + bot_data.get("targets", [])))
    for target_id in targets:
        try:
            await message.copy_to(chat_id=target_id)
        except TelegramAPIError:
            pass

# ¡EL SECRETO ESTÁ AQUÍ! Fábrica de Dispatchers vírgenes
def get_new_child_dp() -> Dispatcher:
    dp = Dispatcher()
    # Registramos las funciones manualmente a este Dispatcher único
    dp.message.register(child_start, CommandStart(), F.chat.type == "private")
    dp.callback_query.register(child_toggle_settings, F.data.startswith("toggle_"))
    dp.message.register(forward_media, F.photo | F.video | F.document)
    return dp


# ==========================================
# 3. INTERFAZ Y LÓGICA DEL MASTER BOT
# ==========================================
def get_master_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Ver Mis Bots", callback_data="master_mybots")],
        [InlineKeyboardButton(text="📖 Guía de Uso", callback_data="master_help")]
    ])

@master_dp.message(CommandStart())
async def master_start(message: Message):
    text = (
        "👋 <b>¡Bienvenido al Gestor de Bots Extractores!</b>\n\n"
        "Soy tu asistente personal. Puedo alojar en mis servidores tus propios bots "
        "para extraer fotos, videos y documentos de cualquier grupo automáticamente.\n\n"
        "🔑 <i>Para crear un nuevo bot, simplemente reenvíame un <b>Token</b> obtenido en @BotFather.</i>"
    )
    await message.answer(text, reply_markup=get_master_main_menu())

@master_dp.callback_query(F.data == "master_help")
async def master_help_callback(callback: CallbackQuery):
    text = (
        "📖 <b>GUÍA DE USO RÁPIDO</b>\n\n"
        "<b>1. Crear un Bot:</b>\n"
        "Ve a @BotFather, usa <code>/newbot</code> y envíame el Token que te genere.\n\n"
        "<b>2. Configurar Privacidad (Importante):</b>\n"
        "En @BotFather, usa <code>/setprivacy</code> -> Selecciona tu bot -> Ponlo en <b>Disable</b>.\n\n"
        "<b>3. Añadir Destinos:</b>\n"
        "Por defecto, los archivos te llegarán a ti por privado. Para enviarlos a un canal, usa el comando:\n"
        "<code>/add ID_BOT ID_CANAL</code>\n"
        "<i>Ej: /add 123456789 -1009876543</i>\n\n"
        "<b>4. Configurar tu Bot (Filtros):</b>\n"
        "Inicia un chat privado directamente con tu <b>Bot Hijo</b> y envíale <code>/start</code> para ver su menú de filtros."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Volver", callback_data="master_back")]
    ]))
    await callback.answer()

@master_dp.callback_query(F.data == "master_back")
async def master_back_callback(callback: CallbackQuery):
    await master_start(callback.message)
    await callback.message.delete()

@master_dp.callback_query(F.data == "master_mybots")
async def master_mybots_callback(callback: CallbackQuery):
    cursor = bots_collection.find({"owner_id": callback.from_user.id})
    bots_list = await cursor.to_list(length=20)
    
    if not bots_list:
        await callback.message.edit_text(
            "❌ No tienes bots activos.\nEnvíame un Token para empezar.", 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Volver", callback_data="master_back")]])
        )
        return
    
    text = "🤖 <b>TUS BOTS ACTIVOS</b>\n\n"
    for b in bots_list:
        targets_str = ", ".join(map(str, b.get('targets', []))) or "Ninguno"
        text += f"🔹 <b>ID:</b> <code>{b['_id']}</code>\n"
        text += f"📢 <b>Destinos extra:</b> <code>{targets_str}</code>\n"
        text += "<i>(Para cambiar filtros, ve al chat de este bot)</i>\n\n"
        
    text += "⚙️ <i>Para añadir un destino usa:</i>\n<code>/add ID_BOT ID_DESTINO</code>"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Volver al menú", callback_data="master_back")]
    ]))
    await callback.answer()

@master_dp.message(Command("add"))
async def cmd_add_target(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Uso: <code>/add ID_BOT ID_DESTINO</code>")
        return
    try:
        bot_id, target_id = int(args[1]), int(args[2])
        bot_data = await bots_collection.find_one({"_id": bot_id, "owner_id": message.from_user.id})
        if not bot_data:
            await message.answer("❌ Bot no encontrado o no eres el dueño.")
            return
        await bots_collection.update_one({"_id": bot_id}, {"$addToSet": {"targets": target_id}})
        await message.answer(f"✅ Destino <code>{target_id}</code> añadido con éxito.")
    except ValueError:
        await message.answer("❌ Los IDs deben ser números.")

@master_dp.message(Command("del"))
async def cmd_del_target(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Uso: <code>/del ID_BOT ID_DESTINO</code>")
        return
    try:
        bot_id, target_id = int(args[1]), int(args[2])
        await bots_collection.update_one({"_id": bot_id, "owner_id": message.from_user.id}, {"$pull": {"targets": target_id}})
        await message.answer(f"🗑 Destino <code>{target_id}</code> eliminado.")
    except ValueError:
        pass

@master_dp.message(F.text)
async def receive_token(message: Message):
    token = message.text.strip()
    if len(token.split(':')) != 2: return
        
    msg_status = await message.answer("🔄 <i>Conectando a los servidores de Telegram...</i>")
    new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    try:
        bot_info = await new_bot.get_me()
        bot_id = bot_info.id
        
        if bot_id in active_bots_tasks:
            await msg_status.edit_text("⚠️ Este bot ya está corriendo.")
            await new_bot.session.close()
            return
            
        await bots_collection.update_one(
            {"_id": bot_id},
            {"$set": {"token": token, "owner_id": message.from_user.id}, "$setOnInsert": {"settings": DEFAULT_SETTINGS}},
            upsert=True
        )
        
        # INYECTAMOS EL NUEVO DISPATCHER VIRGEN
        child_dp = get_new_child_dp()
        task = asyncio.create_task(child_dp.start_polling(new_bot, handle_signals=False))
        active_bots_tasks[bot_id] = {"task": task, "bot": new_bot}
        
        text = (
            f"✅ <b>¡Bot @{bot_info.username} en línea!</b>\n\n"
            f"<b>ID:</b> <code>{bot_id}</code>\n\n"
            "👉 <b>Siguiente paso:</b> Inicia un chat con él y envíale <code>/start</code> para ver tu panel de control."
        )
        await msg_status.edit_text(text)
        
    except TelegramUnauthorizedError:
        await msg_status.edit_text("❌ Token inválido o revocado. Revísalo en @BotFather.")
        await new_bot.session.close()
    except Exception as e:
        logger.error(f"Error: {e}")
        await new_bot.session.close()


# ==========================================
# 4. SERVIDOR WEB Y ARRANQUE
# ==========================================
async def ping_handler(request):
    return web.Response(text="Bot Manager Pro is alive!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

async def restore_bots():
    cursor = bots_collection.find({})
    async for bot_data in cursor:
        bot_id, token = bot_data["_id"], bot_data["token"]
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            await new_bot.get_me()
            
            # INYECTAMOS EL NUEVO DISPATCHER AL RESTAURAR
            child_dp = get_new_child_dp()
            task = asyncio.create_task(child_dp.start_polling(new_bot, handle_signals=False))
            active_bots_tasks[bot_id] = {"task": task, "bot": new_bot}
        except Exception:
            await new_bot.session.close()

async def main():
    await start_web_server()
    await restore_bots()
    
    master_bot = Bot(token=MASTER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await master_dp.start_polling(master_bot)
    finally:
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
