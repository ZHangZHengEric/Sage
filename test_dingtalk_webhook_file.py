"""Test DingTalk file send via webhook API"""

import asyncio
import httpx
import os
import mimetypes

APP_KEY = "ding0r0dvbzyqzh4wcgb"
APP_SECRET = "B6CP3YlaVH4GDCNdjUMHlmA54y0wqR7tDiMXhnk7Z1ch03rAV4DKxsvMqME7iIjb"

async def get_access_token():
    url = "https://oapi.dingtalk.com/gettoken"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"appkey": APP_KEY, "appsecret": APP_SECRET})
        return resp.json().get("access_token")

async def upload_file(access_token, file_path):
    url = "https://oapi.dingtalk.com/media/upload"
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    
    async with httpx.AsyncClient() as client:
        with open(file_path, "rb") as f:
            files = {"media": (os.path.basename(file_path), f, mime_type)}
            resp = await client.post(
                url,
                params={"access_token": access_token, "type": "file"},
                files=files
            )
        return resp.json()

async def send_file_via_webhook(access_token, media_id):
    """Send file via webhook API"""
    url = f"https://oapi.dingtalk.com/robot/send"
    payload = {
        "msgtype": "file",
        "file": {
            "media_id": media_id
        }
    }
    
    print(f"\nSending file via webhook:")
    print(f"URL: {url}")
    print(f"Payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params={"access_token": access_token},
            json=payload
        )
        data = resp.json()
        print(f"Response: {data}")
        return data

async def main():
    # Create test file
    test_file = "/tmp/test_webhook.txt"
    with open(test_file, "w") as f:
        f.write("This is a test file for webhook file sending.")
    
    # Get access token
    access_token = await get_access_token()
    print(f"Access token: {access_token[:20]}...")
    
    # Upload file
    upload_result = await upload_file(access_token, test_file)
    print(f"Upload result: {upload_result}")
    
    media_id = upload_result.get("media_id")
    if media_id:
        # Send file via webhook
        result = await send_file_via_webhook(access_token, media_id)
    else:
        print("Failed to get media_id")
    
    # Cleanup
    os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
