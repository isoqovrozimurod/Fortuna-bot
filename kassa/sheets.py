"""Google Sheets nusxa (ixtiyoriy): KASSA_SHEET_ID berilsa, har saqlash/yuborishda sinxronlanadi.
Xato bo'lsa faqat log'ga yoziladi — bot ishiga ta'sir qilmaydi."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

from .logic import fmt_date, net_income

logger = logging.getLogger(__name__)


SHEET_NAME = "Total"
SHEET_HEADERS = ["T/r", "Sana", "Kun boshiga qoldiq", "Bankdan olingan", "Tushum", "Chiqim", "Qoldiq", "Holat", "Yangilangan"]


def _sheet_row(row: dict) -> list:
    return [
        None,  # T/r — keyin to'ldiriladi
        fmt_date(row["sana"]),
        int(row["kun_boshiga"]),
        int(row["bank"]),
        net_income(row) - int(row["bank"]),
        int(row["jami_chiqim"]),
        int(row["qoldiq"]),
        row.get("status", ""),
        str(row.get("yangilangan", ""))[:19].replace("T", " "),
    ]


def _sync_sheets_blocking(row: dict) -> None:
    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = os.getenv("KASSA_SHEET_ID", "")
    b64 = os.getenv("GOOGLE_CREDENTIALS_B64", "")
    if not sheet_id or not b64:
        return
    info = json.loads(base64.b64decode(b64).decode())
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    sh = gspread.authorize(creds).open_by_key(sheet_id)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(SHEET_NAME, rows=500, cols=len(SHEET_HEADERS))
        ws.update(values=[SHEET_HEADERS], range_name="A1")
    dates = ws.col_values(2)  # 1-qator sarlavha
    values = _sheet_row(row)
    label = values[1]
    if label in dates[1:]:
        r = dates.index(label) + 1
        values[0] = r - 1
        ws.update(values=[values], range_name=f"A{r}:I{r}")
    else:
        r = max(len(dates), 1) + 1
        values[0] = r - 1
        ws.update(values=[values], range_name=f"A{r}:I{r}")


_bg_tasks: set = set()


def schedule_sheets_sync(row: dict) -> None:
    """Fon vazifasi: xato bo'lsa faqat log'ga yoziladi, bot ishiga ta'sir qilmaydi."""
    if not os.getenv("KASSA_SHEET_ID"):
        return

    async def _run():
        try:
            await asyncio.get_running_loop().run_in_executor(None, _sync_sheets_blocking, row)
        except Exception:
            logger.exception("Kassa Sheets sinxronida xato")

    task = asyncio.create_task(_run())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
