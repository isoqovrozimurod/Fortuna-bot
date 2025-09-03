import os
import json
import uuid
from aiogram import Router, types, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

router = Router()

# Faylga saqlanadigan joy
DATA_FILE = "vakansiyalar.json"


# === FSM holatlari ===
class IshFSM(StatesGroup):
    rasm = State()
    matn = State()
    edit_rasm = State()
    edit_matn = State()


# === JSON saqlash/ochish funksiyalari ===
def load_data():
    """Vakansiyalarni JSON fayldan o‘qish"""
    if not os.path.exists(DATA_FILE):
        save_data([])  # Fayl mavjud bo‘lmasa bo‘sh massiv yaratamiz
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:  # Fayl bo‘sh bo‘lsa
                save_data([])
                return []
            return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # Noto‘g‘ri format bo‘lsa yangidan yaratamiz
        save_data([])
        return []


def save_data(data):
    """Vakansiyalarni JSON faylga saqlash"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# === /job faqat admin uchun ===
@router.message(F.text == "/job")
async def ish_handler(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Sizda bu buyruqdan foydalanish huquqi yo‘q.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Vakansiya qo‘shish", callback_data="add_vakansiya")],
        [InlineKeyboardButton(text="📋 Vakansiyalar ro‘yxati", callback_data="list_vakansiya")]
    ])
    await msg.answer("Ish bo‘limi (faqat admin uchun):", reply_markup=kb)


# === Admin: vakansiya qo‘shish ===
@router.callback_query(F.data == "add_vakansiya")
async def add_vakansiya(clb: types.CallbackQuery, state: FSMContext):
    skip_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data="skip_photo")]
    ])
    await state.set_state(IshFSM.rasm)
    await clb.message.answer(
        "📸 Vakansiya uchun rasm yuboring (yoki o'tkazib yuborish uchun quyidagi tugmani bosing).",
        reply_markup=skip_button
    )


# === Rasm yuborilganda (yangi vakansiya) ===
@router.message(IshFSM.rasm, F.photo)
async def get_rasm(msg: types.Message, state: FSMContext):
    file_id = msg.photo[-1].file_id
    await state.update_data(rasm=file_id)
    await state.set_state(IshFSM.matn)
    await msg.answer("✍️ Vakansiya matnini yuboring:")


# === O'tkazib yuborish tugmasi bosilganda (yangi vakansiya) ===
@router.callback_query(F.data == "skip_photo")
async def skip_photo(clb: types.CallbackQuery, state: FSMContext):
    await state.update_data(rasm=None)
    await state.set_state(IshFSM.matn)
    await clb.message.answer("✍️ Vakansiya matnini yuboring:")


# === ❌ matni yuborilganda (yangi vakansiya) ===
@router.message(IshFSM.rasm, F.text == "❌")
async def skip_rasm(msg: types.Message, state: FSMContext):
    await state.update_data(rasm=None)
    await state.set_state(IshFSM.matn)
    await msg.answer("✍️ Vakansiya matnini yuboring:")


# === Matn yuborilganda (yangi vakansiya) ===
@router.message(IshFSM.matn)
async def get_matn(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    vakansiya = {
        "id": str(uuid.uuid4()),
        "rasm": data.get("rasm"),
        "matn": msg.html_text  # HTML formatda saqlanadi
    }
    db = load_data()
    db.append(vakansiya)
    save_data(db)

    await msg.answer("✅ Vakansiya saqlandi!")
    await state.clear()


# === Admin: vakansiyalar ro‘yxati ===
@router.callback_query(F.data == "list_vakansiya")
async def list_vakansiya(clb: types.CallbackQuery):
    db = load_data()
    if not db:
        return await clb.message.answer("❌ Hozircha vakansiya yo‘q.")

    for v in db:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"edit_{v['id']}")],
            [InlineKeyboardButton(text="🗑 O‘chirish", callback_data=f"del_{v['id']}")]
        ])
        if v["rasm"]:
            await clb.message.answer_photo(v["rasm"], caption=v["matn"], reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await clb.message.answer(v["matn"], reply_markup=kb, parse_mode=ParseMode.HTML)


# === Admin: vakansiya o‘chirish ===
@router.callback_query(F.data.startswith("del_"))
async def delete_vakansiya(clb: types.CallbackQuery):
    vid = clb.data.split("_", 1)[1]
    db = load_data()
    db = [v for v in db if v["id"] != vid]
    save_data(db)
    await clb.message.answer("🗑 Vakansiya o‘chirildi.")


# === Admin: vakansiya tahrirlash ===
@router.callback_query(F.data.startswith("edit_"))
async def edit_vakansiya(clb: types.CallbackQuery, state: FSMContext):
    vid = clb.data.split("_", 1)[1]
    db = load_data()
    vak = next((v for v in db if v["id"] == vid), None)

    if not vak:
        return await clb.message.answer("❌ Vakansiya topilmadi.")

    await state.update_data(edit_id=vid, current_rasm=vak["rasm"], current_matn=vak["matn"])
    await state.set_state(IshFSM.edit_rasm)

    skip_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data="skip_edit_photo")]
    ])

    if vak["rasm"]:
        await clb.message.answer_photo(
            vak["rasm"],
            caption="📸 Yangi rasm yuboring yoki o'tkazib yuborish uchun quyidagi tugmani bosing.",
            reply_markup=skip_button,
            parse_mode=ParseMode.HTML
        )
    else:
        await clb.message.answer(
            "📸 Vakansiyada rasm yo‘q. Yangi rasm yuboring yoki o'tkazib yuborish uchun quyidagi tugmani bosing.",
            reply_markup=skip_button
        )


# === Rasm yuborilganda (tahrirlash) ===
@router.message(IshFSM.edit_rasm, F.photo)
async def edit_get_rasm(msg: types.Message, state: FSMContext):
    file_id = msg.photo[-1].file_id
    await state.update_data(rasm=file_id)
    await state.set_state(IshFSM.edit_matn)
    data = await state.get_data()
    db = load_data()
    vak = next((v for v in db if v["id"] == data["edit_id"]), None)
    skip_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data="skip_edit_text")]
    ])
    await msg.answer(
        f"✍️ Yangi matnni yuboring yoki o'tkazib yuborish uchun quyidagi tugmani bosing:\n\n<b>Oldingi matn:</b>\n\n{vak['matn']}",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_button
    )


# === O'tkazib yuborish tugmasi bosilganda (tahrirlash, rasm) ===
@router.callback_query(F.data == "skip_edit_photo")
async def skip_edit_photo(clb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(rasm=data.get("current_rasm"))
    await state.set_state(IshFSM.edit_matn)
    db = load_data()
    vak = next((v for v in db if v["id"] == data["edit_id"]), None)
    skip_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data="skip_edit_text")]
    ])
    await clb.message.answer(
        f"✍️ Yangi matnni yuboring yoki o'tkazib yuborish uchun quyidagi tugmani bosing:\n\n<b>Oldingi matn:</b>\n\n{vak['matn']}",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_button
    )


# === ❌ matni yuborilganda (tahrirlash, rasm) ===
@router.message(IshFSM.edit_rasm, F.text == "❌")
async def skip_edit_rasm(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(rasm=data.get("current_rasm"))
    await state.set_state(IshFSM.edit_matn)
    db = load_data()
    vak = next((v for v in db if v["id"] == data["edit_id"]), None)
    skip_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data="skip_edit_text")]
    ])
    await msg.answer(
        f"✍️ Yangi matnni yuboring yoki o'tkazib yuborish uchun quyidagi tugmani bosing:\n\n<b>Oldingi matn:</b>\n\n{vak['matn']}",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_button
    )


# === O'tkazib yuborish tugmasi bosilganda (tahrirlash, matn) ===
@router.callback_query(F.data == "skip_edit_text")
async def skip_edit_text(clb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    vid = data["edit_id"]
    db = load_data()
    for v in db:
        if v["id"] == vid:
            v["rasm"] = data.get("rasm")
            v["matn"] = data.get("current_matn")
            break
    save_data(db)
    await clb.message.answer("✅ Vakansiya yangilandi.")
    await state.clear()


# === Matn yuborilganda (tahrirlash) ===
@router.message(IshFSM.edit_matn)
async def save_edit(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    vid = data["edit_id"]
    db = load_data()
    for v in db:
        if v["id"] == vid:
            v["matn"] = msg.html_text
            v["rasm"] = data.get("rasm")
            break
    save_data(db)
    await msg.answer("✅ Vakansiya yangilandi.")
    await state.clear()


# === /vakansiya foydalanuvchilar uchun ===
@router.message(F.text == "/vakansiya")
async def show_vakansiya(msg: types.Message):
    db = load_data()
    if not db:
        return await msg.answer("❌ Hozircha vakansiya yo‘q.")

    for v in db:
        if v["rasm"]:
            await msg.answer_photo(v["rasm"], caption=v["matn"], parse_mode=ParseMode.HTML)
        else:
            await msg.answer(v["matn"], parse_mode=ParseMode.HTML)
