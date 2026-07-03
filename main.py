import os
import re
import httpx
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
DEEPL_KEY = os.getenv("DEEPL_API_KEY")
TARGET_LANGS = os.getenv("TARGET_LANGUAGES", "ZH-HANT,JA").split(",")

app = FastAPI()
configuration = Configuration(access_token=LINE_TOKEN)
parser = WebhookParser(LINE_SECRET)

# 用來判斷整句話「是不是就是一個網址」
URL_PATTERN = re.compile(r'^https?://\S+$')

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

def detect_source_lang(text: str) -> str:
    if re.search(r'[\u3040-\u30ff]', text):
        return "JA"
    return "ZH-HANT"

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
                original_text = event.message.text.strip()

                if not original_text or original_text.startswith("/"):
                    continue

                # ✅ 防線 1：整句話就是一個純網址，直接跳過不回覆
                if URL_PATTERN.match(original_text):
                    continue

                source_code = detect_source_lang(original_text)

                reply_lines = []
                seen_texts = set()  # 用來記錄已經出現過的翻譯結果

                for lang in TARGET_LANGS:
                    lang = lang.strip()
                    if source_code == lang:
                        continue
                    try:
                        translated = await translate_text(original_text, lang)

                        # ✅ 防線 2：翻譯結果若跟已出現過的內容重複，就跳過
                        normalized = translated.strip().lower()
                        if normalized in seen_texts:
                            continue
                        seen_texts.add(normalized)

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
