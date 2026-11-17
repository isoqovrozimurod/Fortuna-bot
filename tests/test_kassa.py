"""kassa/ paketi sinovlari. Ishga tushirish:  pytest -q tests/test_kassa.py"""
import io
import os
import sys
import asyncio
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(ADMIN_ID="111", MY_ID="111", KASSA_BOSS_ID="222")

import kassa  # noqa: E402
from kassa import config as kcfg, logic as klogic, db as kdb, render as krender, handlers as khandlers  # noqa: E402
from PIL import Image  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import SendMessage, SendPhoto  # noqa: E402
from aiogram.types import Chat, Message, User, Update, CallbackQuery, Message as TgMessage  # noqa: E402


# ───────── sof funksiyalar ─────────

@pytest.mark.parametrize("text,exp", [
    ("90740600", 90740600), ("90 740 600", 90740600), ("90,740,600", 90740600),
    ("90.740.600", 90740600), ("0", 0), ("-", 0), ("  1 000  ", 1000),
    ("1,5", None), ("1.5", None), ("abc", None), ("-5", None), ("", None),
    ("12 34", 1234), ("9" * 14, None),
])
def test_parse_amount(text, exp):
    assert klogic.parse_amount(text) == exp


def test_parse_date():
    t = date(2026, 11, 16)
    assert klogic.parse_date("13.11.2026", t) == date(2026, 11, 13)
    assert klogic.parse_date("13.11", t) == date(2026, 11, 13)
    assert klogic.parse_date("kecha", t) == date(2026, 11, 15)
    assert klogic.parse_date("31.02.2026", t) is None
    assert klogic.parse_date("salom", t) is None


def test_compute_matches_excel_example():
    # Excel hisoboti (13.11.2026): boshiga 646 882 350, mijoz 90 740 600, kredit 164 000 000
    res = klogic.compute(646_882_350, {"mijoz_tushum": 90_740_600, "berilgan_kredit": 164_000_000})
    assert res == {"jami_tushum": 737_622_950, "jami_chiqim": 164_000_000, "qoldiq": 573_622_950}


def sample_row(**kw):
    vals = {"mijoz_tushum": 90_740_600, "berilgan_kredit": 164_000_000}
    vals.update(kw.pop("vals", {}))
    return make_row(date(2026, 11, 13), 646_882_350, vals, **kw)


def make_row(sana, boshi, vals, versiya=1, status="saqlangan"):
    row = {"sana": sana.isoformat(), "kun_boshiga": boshi, "versiya": versiya, "status": status,
           "yangilangan": "2026-11-13T09:00:00+05:00", "kun_boshiga_qolda": False}
    for k, _, _, _ in kcfg.FIELDS:
        row[k] = int(vals.get(k, 0))
    row.update(klogic.compute(boshi, vals))
    return row


def test_render_report_png(tmp_path):
    png = krender.render_report(sample_row())
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width > 800 and img.height > 600
    (tmp_path / "r.png").write_bytes(png)
    if os.getenv("KASSA_SAVE_PNG"):
        open(os.getenv("KASSA_SAVE_PNG"), "wb").write(png)


# ───────── Soxta baza ─────────

class FakeDB:
    def __init__(self):
        self.rows = {}
        self.fail_send_unmark = 0

    async def get(self, sana):
        r = self.rows.get(sana.isoformat())
        return dict(r) if r else None

    async def prev(self, sana):
        ks = sorted(k for k in self.rows if k < sana.isoformat())
        return dict(self.rows[ks[-1]]) if ks else None

    async def month(self, y, m):
        return [dict(self.rows[k]) for k in sorted(self.rows) if k.startswith(f"{y}-{m:02d}")]

    async def save(self, sana, boshi, qolda, vals, kim):
        old = self.rows.get(sana.isoformat())
        row = make_row(sana, boshi, vals, versiya=(old["versiya"] + 1) if old else 1)
        row["kun_boshiga_qolda"] = qolda
        self.rows[sana.isoformat()] = row
        return dict(row)

    async def mark_sent(self, sana, versiya):
        r = self.rows.get(sana.isoformat())
        if r and r["versiya"] == versiya and r["status"] == "saqlangan":
            r["status"] = "yuborilgan"
            return dict(r)
        return None

    async def unmark_sent(self, sana, versiya):
        r = self.rows[sana.isoformat()]
        r["status"] = "saqlangan"


# ───────── Soxta Telegram sessiyasi ─────────

class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._mid = 100
        self.fail_for_chat = set()

    async def close(self): ...
    async def stream_content(self, *a, **k): ...

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendPhoto)):
            if getattr(method, "chat_id", None) in self.fail_for_chat:
                from aiogram.exceptions import TelegramForbiddenError
                raise TelegramForbiddenError(method=method, message="bot was blocked by the user")
            self._mid += 1
            return Message(message_id=self._mid, date=datetime.now(),
                           chat=Chat(id=int(method.chat_id), type="private"),
                           from_user=User(id=1, is_bot=True, first_name="bot"))
        return True


def sent(session, cls):
    return [c for c in session.calls if isinstance(c, cls)]


class Harness:
    def __init__(self):
        self.session = FakeSession()
        self.bot = Bot("123456:TEST", session=self.session,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher(storage=MemoryStorage())
        kassa.router._parent_router = None   # har sinovda yangi Dispatcher'ga ulash uchun
        self.dp.include_router(kassa.router)
        self.uid = 111
        self.upd = 0
        self.last_prompt_id = 100

    async def text(self, text, uid=None):
        self.upd += 1
        uid = uid or self.uid
        from aiogram.types import MessageEntity
        ents = None
        if text.startswith("/"):
            ents = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
        msg = Message(message_id=1000 + self.upd, date=datetime.now(),
                      chat=Chat(id=uid, type="private"), from_user=User(id=uid, is_bot=False, first_name="U"),
                      text=text, entities=ents)
        await self.dp.feed_update(self.bot, Update(update_id=self.upd, message=msg))

    async def press(self, data, uid=None):
        self.upd += 1
        uid = uid or self.uid
        # tugma bosilgan xabar = botning oxirgi xabari
        bot_msg = Message(message_id=self.session._mid, date=datetime.now(),
                          chat=Chat(id=uid, type="private"), from_user=User(id=1, is_bot=True, first_name="bot"),
                          text="x")
        cb = CallbackQuery(id=str(self.upd), from_user=User(id=uid, is_bot=False, first_name="U"),
                           chat_instance="ci", message=bot_msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self.upd, callback_query=cb))

    def last_text(self):
        for c in reversed(self.session.calls):
            if isinstance(c, SendMessage):
                return c.text
        return None


@pytest.fixture
def h(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(kdb, "_db", db)
    monkeypatch.setattr(khandlers, "today_tz", lambda: date(2026, 11, 16))
    hh = Harness()
    hh.db = db
    return hh


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ───────── Oqim sinovlari ─────────

def test_full_flow_asosiy_save_and_send(h):
    async def go():
        await h.text("/kassa")
        assert "16.11.2026" in h.last_text()
        await h.press("ks:mode:asosiy")
        assert "birinchi" in h.last_text().lower()          # kechagi hisobot yo'q
        await h.text("646 882 350")                         # kun boshiga
        assert "1/3" in h.last_text()
        await h.text("90740600")                            # mijoz
        await h.press("ks:zero:1")                          # bank = 0
        await h.text("164000000")                           # kredit
        assert "573 622 950" in h.last_text()               # tasdiqlash oynasi
        await h.press("ks:save")
        row = h.db.rows["2026-11-16"]
        assert row["qoldiq"] == 573_622_950 and row["status"] == "saqlangan"
        assert len(sent(h.session, SendPhoto)) == 1         # rasm adminga
        # ikki marta bosish himoyasi: "saqlash" qayta ishlamaydi
        await h.press("ks:save")
        assert h.db.rows["2026-11-16"]["versiya"] == 1
        # boshliqqa yuborish
        await h.press("ks:send:2026-11-16")
        photos = sent(h.session, SendPhoto)
        assert len(photos) == 2 and photos[1].chat_id == 222
        assert h.db.rows["2026-11-16"]["status"] == "yuborilgan"
        # ikkinchi bosish — qayta yuborilmaydi
        await h.press("ks:send:2026-11-16")
        assert len(sent(h.session, SendPhoto)) == 2
    run(go())


def test_prev_balance_suggested_and_manual_override_flagged(h):
    async def go():
        h.db.rows["2026-11-15"] = make_row(date(2026, 11, 15), 100, {"mijoz_tushum": 50})
        await h.text("/kassa")
        await h.press("ks:mode:asosiy")
        assert "150" in h.last_text() and "To'g'rimi" in h.last_text()
        await h.press("ks:boshi:edit")
        await h.text("140")
        for v in ("10", "0", "0"):
            await h.text(v)
        assert "qo'lda o'zgartirilgan" in h.last_text()
        await h.press("ks:save")
        assert h.db.rows["2026-11-16"]["kun_boshiga_qolda"] is True
    run(go())


def test_negative_balance_blocked(h):
    async def go():
        await h.text("/kassa")
        await h.press("ks:mode:asosiy")
        await h.text("100")
        await h.text("0"); await h.text("0"); await h.text("500")
        assert "manfiy" in h.last_text()
        await h.press("ks:save")
        assert "2026-11-16" not in h.db.rows
    run(go())


def test_bad_input_keeps_state(h):
    async def go():
        await h.text("/kassa")
        await h.press("ks:mode:asosiy")
        await h.text("100")
        await h.text("1,5")                                 # kasr — rad etiladi
        assert "Faqat raqam" in h.last_text()
        await h.text("abc")
        assert "Faqat raqam" in h.last_text()
        await h.text("20")
        assert "2/3" in h.last_text()
    run(go())


def test_stale_button_ignored(h):
    async def go():
        await h.text("/kassa")
        await h.press("ks:mode:hammasi")
        await h.text("100")                                  # boshi
        await h.text("5")                                    # 1-qator
        n_before = len(h.session.calls)
        await h.press("ks:zero:0")                           # eskirgan (idx=0, hozir idx=1)
        assert "2/8" in h.last_text()                        # oldinga o'tmadi
    run(go())


def test_strangers_are_ignored(h):
    async def go():
        await h.text("/kassa", uid=999)
        assert h.session.calls == []
        await h.press("ks:send:2026-11-16", uid=999)
        assert h.session.calls == []
    run(go())


def test_edit_after_send_marks_corrected(h):
    async def go():
        h.db.rows["2026-11-16"] = make_row(date(2026, 11, 16), 100, {"mijoz_tushum": 50}, status="yuborilgan")
        await h.text("/kassa")
        assert "YUBORILGAN" in h.last_text()                 # ogohlantirish
        await h.press("ks:mode:asosiy")
        await h.text("100")
        await h.text("60"); await h.text("0"); await h.text("0")
        await h.press("ks:save")
        assert h.db.rows["2026-11-16"]["versiya"] == 2 and h.db.rows["2026-11-16"]["status"] == "saqlangan"
        await h.press("ks:send:2026-11-16")
        boss_photo = sent(h.session, SendPhoto)[-1]
        assert boss_photo.chat_id == 222 and "Tuzatilgan" in boss_photo.caption
    run(go())


def test_boss_blocked_bot_reverts_status(h):
    async def go():
        h.db.rows["2026-11-16"] = make_row(date(2026, 11, 16), 100, {})
        h.session.fail_for_chat.add(222)
        await h.press("ks:send:2026-11-16")
        assert h.db.rows["2026-11-16"]["status"] == "saqlangan"   # qayta urinish mumkin
    run(go())


def test_hisobot_and_oy_commands(h):
    async def go():
        h.db.rows["2026-11-13"] = make_row(date(2026, 11, 13), 646_882_350,
                                           {"mijoz_tushum": 90_740_600, "berilgan_kredit": 164_000_000})
        await h.text("/hisobot 13.11.2026")
        assert len(sent(h.session, SendPhoto)) == 1
        await h.text("/hisobot 01.01.2026")
        assert "topilmadi" in h.last_text()
        await h.text("/oy 11.2026")
        t = h.last_text()
        assert "Noyabr 2026" in t and "573 622 950" in t and "Hisobot kiritilmagan kunlar" in t
    run(go())
