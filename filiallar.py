import os
from supabase import create_client, Client
from geopy.distance import geodesic
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Location
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from config import SUPABASE_URL, SUPABASE_KEY, load_config

router = Router()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class FilialStates(StatesGroup):
    waiting_for_location = State()

async def get_all_branches():
    """Barcha filiallarni olish"""
    try:
        response = supabase.table("branches").select("*").execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Filiallarni olishda xato: {e}")
        return []

async def add_branch(name: str, address: str, phone: str, latitude: float, longitude: float, working_hours: str = "09:00 - 18:00", description: str = ""):
    """Yangi filial qo'shish (admin uchun)"""
    try:
        response = supabase.table("branches").insert({
            "name": name,
            "address": address,
            "phone": phone,
            "latitude": latitude,
            "longitude": longitude,
            "working_hours": working_hours,
            "description": description
        }).execute()
        return response.data
    except Exception as e:
        print(f"Filial qo'shishda xato: {e}")
        return None

def get_google_maps_url(latitude: float, longitude: float, branch_name: str = "") -> str:
    """Google Maps linkini yaratish"""
    return f"https://maps.google.com/?q={latitude},{longitude}"

def get_distance(user_lat: float, user_lon: float, branch_lat: float, branch_lon: float) -> float:
    """Ikkita nuqta orasidagi masofani km da hisoblash"""
    try:
        return round(geodesic((user_lat, user_lon), (branch_lat, branch_lon)).kilometers, 2)
    except:
        return float('inf')

async def find_nearest_branch(latitude: float, longitude: float) -> dict:
    """Foydalanuvchining joylashuviga qarab eng yaqin filialni topish"""
    branches = await get_all_branches()

    if not branches:
        return None

    nearest = None
    min_distance = float('inf')

    for branch in branches:
        distance = get_distance(
            latitude, longitude,
            float(branch['latitude']), float(branch['longitude'])
        )
        if distance < min_distance:
            min_distance = distance
            nearest = branch
            nearest['distance'] = distance

    return nearest

async def show_branches_menu(message: Message, state: FSMContext):
    """Filiallar menyu"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Filiallar Xaritasi", callback_data="branches_map")],
        [InlineKeyboardButton(text="📍 Yaqin filialni topish", callback_data="find_nearest")],
        [InlineKeyboardButton(text="📋 Barcha filiallar", callback_data="list_branches")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_menu")],
    ])

    if hasattr(message, 'answer'):
        await message.answer("Filiallar bo'limiga xush kelibsiz!", reply_markup=keyboard)
    else:
        await message.edit_text("Filiallar bo'limiga xush kelibsiz!", reply_markup=keyboard)

@router.callback_query(F.data == "branches")
async def show_branches_menu_callback(call, state: FSMContext):
    """Filiallar menyu (callback'dan)"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Filiallar Xaritasi", callback_data="branches_map")],
        [InlineKeyboardButton(text="📍 Yaqin filialni topish", callback_data="find_nearest")],
        [InlineKeyboardButton(text="📋 Barcha filiallar", callback_data="list_branches")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_menu")],
    ])

    await call.message.edit_text("Filiallar bo'limiga xush kelibsiz!", reply_markup=keyboard)
    await call.answer()

@router.message(F.text == "📍 Filiallar")
async def show_branches_menu_message(message: Message, state: FSMContext):
    """Filiallar menyu (xabar'dan)"""
    await show_branches_menu(message, state)

@router.callback_query(F.data == "branches_map")
async def show_branches_map(call, state: FSMContext):
    """Filiallar xaritasini ko'rsat"""
    branches = await get_all_branches()

    if not branches:
        await call.answer("Filiallar ma'lumotlari topilmadi", show_alert=True)
        return

    text = "🗺️ <b>Fortuna Filiallarining Xaritas</b>\n\n"

    keyboard_buttons = []
    for i, branch in enumerate(branches, 1):
        text += f"{i}. <b>{branch['name']}</b>\n"
        text += f"   📍 {branch['address']}\n"
        text += f"   ☎️ {branch['phone']}\n"
        text += f"   🕐 {branch['working_hours']}\n\n"

        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"📍 {branch['name']}",
                url=get_google_maps_url(branch['latitude'], branch['longitude'], branch['name'])
            )
        ])

    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await call.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "find_nearest")
async def request_location(call, state: FSMContext):
    """Foydalanuvchidan joylashuvini so'rash"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")]
    ])

    await call.message.edit_text(
        "📍 Joylashuvingizni yuboring, biz sizga eng yaqin filialni topib beramiz.",
        reply_markup=keyboard
    )
    await call.answer()
    await state.set_state(FilialStates.waiting_for_location)

@router.message(FilialStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    """Foydalanuvchining joylashuvini qayta ishlash"""
    user_latitude = message.location.latitude
    user_longitude = message.location.longitude

    nearest = await find_nearest_branch(user_latitude, user_longitude)

    if nearest:
        maps_url = get_google_maps_url(nearest['latitude'], nearest['longitude'])

        text = f"🎯 <b>Eng Yaqin Filiyal</b>\n\n"
        text += f"<b>{nearest['name']}</b>\n"
        text += f"📍 Manzil: {nearest['address']}\n"
        text += f"☎️ Telefon: {nearest['phone']}\n"
        text += f"🕐 Ish vaqti: {nearest['working_hours']}\n"
        text += f"📏 Sizdan masofasi: <b>{nearest['distance']} km</b>\n"

        if nearest.get('description'):
            text += f"\n📝 {nearest['description']}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗺️ Google Xaritada ko'rish", url=maps_url)],
            [InlineKeyboardButton(text="☎️ Qo'ng'iroq qilish", url=f"tel:{nearest['phone']}")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")]
        ])

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer("❌ Filiallar ma'lumotlari topilmadi")

    await state.clear()

@router.callback_query(F.data == "list_branches")
async def show_all_branches(call, state: FSMContext):
    """Barcha filiallarni ro'yxat ko'rish"""
    branches = await get_all_branches()

    if not branches:
        await call.answer("Filiallar ma'lumotlari topilmadi", show_alert=True)
        return

    text = "📋 <b>Barcha Filiallar</b>\n\n"

    for i, branch in enumerate(branches, 1):
        text += f"<b>{i}. {branch['name']}</b>\n"
        text += f"   📍 {branch['address']}\n"
        text += f"   ☎️ {branch['phone']}\n"
        text += f"   🕐 {branch['working_hours']}\n"
        if branch.get('description'):
            text += f"   📝 {branch['description']}\n"
        text += "\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")]
    ])

    await call.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "branches_back")
async def branches_back(call, state: FSMContext):
    """Filiallar menyu orqaga qaytish"""
    await show_branches_menu(call.message, state)
    await call.answer()

@router.message(Command("filiallar"))
async def cmd_filiallar(message: Message, state: FSMContext):
    """Filiallar ko'rish komandasi"""
    await show_branches_menu(message, state)

@router.message(Command("init_branches"))
async def init_branches(message: Message, bot: Bot):
    """Admin uchun misoliy filiallarni o'rnatish"""
    config = load_config()
    if message.from_user.id != config.my_id:
        await message.answer("❌ Siz admin emassiz")
        return

    branches_data = [
        {
            "name": "Gallaorol Filiali",
            "address": "G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy",
            "phone": "+998551510040",
            "latitude": 41.5229,
            "longitude": 69.2812,
            "working_hours": "09:00 - 18:00",
            "description": "Asosiy filial"
        },
        {
            "name": "Markaз Filiali",
            "address": "Tashkent shahri, Chilonzor tumani, Buyuk Ipak yo'li",
            "phone": "+998992510040",
            "latitude": 41.2995,
            "longitude": 69.2401,
            "working_hours": "09:00 - 18:00",
            "description": "Markaз filiali"
        },
        {
            "name": "Samarqand Filiali",
            "address": "Samarqand shahri, Registon ko'chasi 12",
            "phone": "+998953754540",
            "latitude": 39.6548,
            "longitude": 66.9597,
            "working_hours": "09:00 - 18:00",
            "description": "Samarqand filiali"
        }
    ]

    added = 0
    for branch in branches_data:
        result = await add_branch(
            branch["name"],
            branch["address"],
            branch["phone"],
            branch["latitude"],
            branch["longitude"],
            branch["working_hours"],
            branch["description"]
        )
        if result:
            added += 1

    await message.answer(f"✅ {added} ta filial qo'shildi")
