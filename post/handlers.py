from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = Router()

CHANNEL_ID = "@isoqovrozimurod_blog"

class PostEditState(StatesGroup):
    waiting_for_caption = State()

def get_post_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Kanalga joylash", callback_data="publish_post")],
        [InlineKeyboardButton(text="✍️ Matnni tahrirlash", callback_data="edit_post")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="reject_post")]
    ])

@router.callback_query(F.data == "publish_post")
async def publish_post_handler(callback: CallbackQuery, bot: Bot):
    # Post rasm bilan bo'lsa
    if callback.message.photo:
        photo_id = callback.message.photo[-1].file_id
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=photo_id,
            caption=callback.message.caption,
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=callback.message.text,
            parse_mode="HTML"
        )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Post muvaffaqiyatli kanalga yuklandi!")

@router.callback_query(F.data == "reject_post")
async def reject_post_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Post bekor qilindi.")

@router.callback_query(F.data == "edit_post")
async def edit_post_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PostEditState.waiting_for_caption)
    await state.update_data(target_message_id=callback.message.message_id)
    await callback.message.answer("Yangi matnni yuboring (HTML teglari bilan):")
    await callback.answer()

@router.message(PostEditState.waiting_for_caption)
async def process_new_caption(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    msg_id = data.get("target_message_id")
    
    await bot.edit_message_caption(
        chat_id=message.chat.id,
        message_id=msg_id,
        caption=message.text,
        parse_mode="HTML",
        reply_markup=get_post_keyboard()
    )
    await state.clear()
    await message.answer("Post yangilandi! Endi tasdiqlashingiz mumkin.")
