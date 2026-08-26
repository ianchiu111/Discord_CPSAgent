import re
import os
import json
import pytz
import logging
import asyncio
from typing import Any, List, Dict
from datetime import datetime
from collections import Counter

import discord
from discord.ext import commands

from langchain_core.messages import SystemMessage
# from langchain_openai import ChatOpenAI
from utils.openai_utils import llm
from prompts import get_intent_agent_prompt, get_summary_agent_prompt

from dotenv import load_dotenv
load_dotenv(".env")

# =============================================
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

# # llm setup
# llm = ChatOpenAI(
#     model="gpt-4o",
#     openai_api_key=os.getenv("OPENAI_API_KEY"),
#     temperature=0,
#     verbose=False,
# )

# Message Records
# 
global frequency, phase
frequency, phase = 0, 0

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

def _message_frequency(messages_history: List[Dict]) -> Dict[str, Any]:
    """
    count the frequency of messages sent by each user
    based on a dynamic threshold: 1 / (N + 1), where N is the total number of unique users.
    output: {
        "user name 1": frequency 1,
        "user name 2": frequency 2,
        "quiet_user": ["user name"]  which frequency percentage < 0.15
    }
    """

    message_frequency = Counter(msg["user"] for msg in messages_history if "user" in msg)
    num_users = len(message_frequency)
    result: Dict[str, Any] = dict(message_frequency)

    frequency_threshold = 2 * num_users + 1

    total_frequency = sum(message_frequency.values())
    if total_frequency > frequency_threshold:

        dynamic_threshold = 1.0 / (num_users + 1)

        quiet_users = [
            user for user, count in message_frequency.items()
            if (count / total_frequency) < dynamic_threshold
        ]
    else:
        quiet_users = []

    result["quiet_user"] = quiet_users
    return result
    

# =============================================
# Main Entry Point

@bot.event
async def on_ready():
    """
    Check Discord Bot Connection
    """
    logger.info(f"✅ Bot 登入成功: {bot.user.name} (ID: {bot.user.id})")
    logger.info("--------------------------------")

@bot.event
async def on_message(message: discord.Message):
    """
    Monitor Conversation 
    """

    if message.author.bot:
        """
        message.author.bot == True >>> message from chatbot
        - need to ignore message from chatbot to avoid infinite loop
        """
        return

    global frequency

    mes = {
        "index": frequency,
        "content": message.content,
        "timestamp": current_time_taiwan.strftime("%Y-%m-%d %H:%M:%S"),
        "user": str(message.author),
    }
    logger.info(f"收到訊息: \n{mes}")
    messages_history.append(mes)

    # check user intent
    intent_system_prompt = get_intent_agent_prompt(origin_query=messages_history)
    intent_response = await llm.ainvoke([SystemMessage(content=intent_system_prompt)])
    json_intent_response = _safe_parse_json(intent_response.content)
    intent = json_intent_response.get("Intent", False)
    logger.info(f"Index: {frequency},\n Intent: {intent}")

    if intent == "discussion":
        frequency += 1

        str_message_history = _stringify(messages_history)

        message_frequency = _message_frequency(messages_history)
        str_message_frequency = _stringify(message_frequency)

        if message_frequency["quiet_user"] != []:
            summary_system_prompt = get_summary_agent_prompt(message_frequency = str_message_frequency, message_history = str_message_history)            
            summary_response = await llm.ainvoke([SystemMessage(content=summary_system_prompt)])
            json_summary_response = _safe_parse_json(summary_response.content)

            participation = json_summary_response.get("Participation", "無法取得參與度評估")

            embed = discord.Embed(
                title="👥 成員參與狀況分析",
                description=participation,
                color=0x5865F2
            )

            await message.reply(embed=embed)

        return

    if bot.user.mentioned_in(message) or intent == "finished" :
        """
        Summary Phase 
        - @CPSAgent
        - intent == "finished" --> user has a summary intent
        """
            
        logger.info(f"Historical messages: {messages_history}")
        str_message_history = _stringify(messages_history)

        message_frequency = _message_frequency(messages_history)
        str_message_frequency = _stringify(message_frequency)
        logger.info(f"User message frequency: {str_message_frequency}")
        
        summary_system_prompt = get_summary_agent_prompt(message_frequency = str_message_frequency, message_history = str_message_history)            
        summary_response = await llm.ainvoke([SystemMessage(content=summary_system_prompt)])
        json_summary_response = _safe_parse_json(summary_response.content)

        title = json_summary_response.get("Title", "無法取得標題")
        summary =json_summary_response.get("Summary", "無法取得內容")
        participation = json_summary_response.get("Participation", "無法取得參與度評估")

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
