import re
import os
import json
import pytz
import logging
from typing import Any, List, Dict
from datetime import datetime
from collections import Counter

import discord
from discord.ext import commands

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from prompts import get_summary_agent_prompt

from dotenv import load_dotenv
load_dotenv(".env")

# =============================================
# Variables
# logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# timezone
taiwan_tz = pytz.timezone("Asia/Taipei")
current_time_taiwan = datetime.now(taiwan_tz)
version = current_time_taiwan.strftime("v%Y-%m%d-%H%M")

# discord chatbot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# llm setup
llm = ChatOpenAI(
    model="gpt-4o",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0,
    verbose=False,
)

# Message Records
messages_history = []

# =============================================
# Helper Function

def _safe_parse_json(text: str) -> dict:
    if isinstance(text, dict):
        return text
    if not text or not isinstance(text, str):
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```json|```", "", text).strip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError as e:
                print(f"fallback decode error: {e}\nOrigin Content: {text}")
                return {}
        else:
            print(f"無法找到 json object, Origin Content: {text}")
            return {}

def _stringify(obj: Any) -> str:
    """Pretty-print dict / list, otherwise str()."""
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return str(obj)

def _count_user_messages(messages_history: List[Dict]) -> Dict[str, int]:
    """
    count the number of messages sent by each user
    """
    user_counts = Counter(msg["user"] for msg in messages_history if "user" in msg)
    
    return dict(user_counts)

# Check Connection
@bot.event
async def on_ready():
    logger.info(f"✅ Bot 登入成功: {bot.user.name} (ID: {bot.user.id})")
    logger.info("--------------------------------")

@bot.event
async def on_message(message: discord.Message):
    count :int = 0

    mes = {
        "index": count,
        "content": message.content,
        "timestamp": current_time_taiwan.strftime("%Y-%m-%d %H:%M:%S"),
        "user": str(message.author)
    }
    messages_history.append(mes)
    count += 1

    logger.info(f"收到訊息: {message.content} (來自: {message.author})")

    # message.author.bot == True -> message from chatbot
    # ignore message from chatbot to avoid infinite loop
    if message.author.bot:
        return

    # scenario 1: user tag CPSAgent 
    if bot.user.mentioned_in(message):
        
        user_prompt = message.clean_content.replace(f"@{bot.user.name}", "").strip()

        """
        # scenario 1-1
        @CPSAgent --> summary historical messages 
        """      
        if not user_prompt:
            
            logger.info(f"Historical messages: {messages_history}")
            str_message = _stringify(messages_history)

            user_counts = _count_user_messages(messages_history)
            str_user_counts = _stringify(user_counts)
            logger.info(f"User message counts: {str_user_counts}")
            
            system_prompt = get_summary_agent_prompt(user_counts = str_user_counts, message_records = str_message)            
            response = await llm.ainvoke([SystemMessage(content=system_prompt)])
            json_response = _safe_parse_json(response.content)

            title = json_response.get("Title", "無法取得標題")
            summary = json_response.get("Summary", "無法取得內容")
            participation = json_response.get("Participation", "無法取得參與度評估")

            # discord embed message
            embed = discord.Embed(
                title=title,
                color=0x5865F2
            )
            embed.add_field(
                name="📝 會議摘要",
                value=summary,
                inline=False
            )
            embed.add_field(
                name="👥 成員參與狀況分析",
                value=participation,
                inline=False
            )

            await message.reply(embed=embed)
        
    await bot.process_commands(message)

# health check
@bot.command()
async def ping(ctx):
    await ctx.send("Pong! 🏓 WebSocket 連線正常！")

bot.run(os.getenv("CHATBOT_APPLICATION_TOKEN"))
