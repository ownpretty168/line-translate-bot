import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from langdetect import detect

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
DEEPL_KEY = os.getenv("DEEPL_API_KEY")
TARGET_LANGS = os.getenv("TARGET_LANGUAGES", "ZH,JA").split(",")

app = FastAPI()
configuration = Configuration(access_token=LINE_TOKEN)
parser = WebhookParser(LINE_SECRET)

async def translate_text(text: str, target_lang: str) -> str:
    url = "https://api-free.deepl.com/v2/translate"
    headers = {
        "Authorization": f"DeepL-Auth-Key {DEEPL_KEY}"
    }
    data = {
        "text": text,
        "target_lang": target_lang
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=data, headers=headers)
        resp.raise_for_status()
        result = resp.json()
        return result["translations"][0]["text"]

LANG_MAP = {
    "zh": "ZH", "zh-tw": "ZH", "zh-cn": "ZH",
    "en": "EN", "ja": "JA", "ko": "KO"
}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    with ApiClient(configuration) as api_client:
        line_api = MessagingApi(api_client)

        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                original_text = event.message.text

                if original_text.startswith("/") or not original_text.strip():
                    continue

                try:
                    detected = detect(original_text)
                except Exception:
                    detected = "unknown"

                source_code = LANG_MAP.get(detected, None)

                reply_lines = []
                for lang in TARGET_LANGS:
                    if source_code == lang:
                        continue
                    try:
                        translated = await translate_text(original_text, lang)
                        reply_lines.append(f"[{lang}] {translated}")
                    except Exception as e:
                        print(f"翻譯 {lang} 失敗: {e}")
                        continue

                if reply_lines:
                    reply_text = "\n".join(reply_lines)
                    line_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=reply_text)]
                        )
                    )

    return "OK"

@app.get("/")
async def health_check():
    return {"status": "running"}
