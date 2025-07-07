from dotenv import load_dotenv
import os

from dataclasses import dataclass

# .env faylni yuklaymiz
load_dotenv()

@dataclass
class Config:
    bot_token: str
    my_id: int

def load_config() -> Config:
    return Config(
        bot_token=os.getenv("BOT_TOKEN"),
        my_id=int(os.getenv("MY_ID")),
    )
