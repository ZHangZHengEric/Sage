"""Test script for DingTalk file sending - trying different msgKeys"""

import asyncio
import httpx
import os
import json

# Your DingTalk credentials
APP_KEY = "ding0r0dvbzyqzh4wcgb"
APP_SECRET = "B6CP3YlaVH4GDCNdjUMHlmA54y0wqR7tDiMXhnk7Z1ch03rAV4DKxsvMqME7iIjb"
USER_ID = "0357302154213522476"

async def get_access_token():
    url = "https://oapi.dingtalk.com/gettoken"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"appkey": APP_KEY, "appsecret": APP_SECRET})
        data = resp.json()
        return data.get("access_token")

async def upload_file(access_token, file_path):
    import mimetypes
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
        data = resp.json()
        return data.get("media_id")

async def send_with_msgkey(access_token, media_id, user_id, msg_key, msg_param):
    """Test sending with specific msgKey and msgParam"""
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    payload = {
        "robotCode": APP_KEY,
        "userIds": [user_id],
        "msgKey": msg_key,
        "msgParam": msg_param
    }
    print(f"\nTest msgKey='{msg_key}':")
    print(f"msgParam: {msg_param}")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"x-acs-dingtalk-access-token": access_token},
            json=payload
        )
        data = resp.json()
        print(f"Response: {data}")
        return data

async def main():
    # Create test file
    test_file = "/tmp/test_dingtalk.txt"
    with open(test_file, "w") as f:
        f.write("Test content")
    
    access_token = await get_access_token()
    media_id = await upload_file(access_token, test_file)
    
    print(f"Media ID: {media_id}")
    
    # Test different msgKey formats
    test_cases = [
        # File message variations
        ("sampleFile", json.dumps({"media_id": media_id})),
        ("sampleFileMsg", json.dumps({"media_id": media_id})),
        
        # Try sending as link with file URL
        ("sampleLink", json.dumps({
            "title": "Test File",
            "text": "Click to download",
            "messageUrl": f"https://oapi.dingtalk.com/media/download?access_token={access_token}&media_id={media_id}",
            "picUrl": ""
        })),
        
        # Try text with file reference
        ("sampleText", json.dumps({
            "content": f"File uploaded. Media ID: {media_id}"
        })),
        
        # Try markdown with file link
        ("sampleMarkdown", json.dumps({
            "title": "File",
            "text": f"[Download File](https://oapi.dingtalk.com/media/download?access_token={access_token}&media_id={media_id})"
        })),
    ]
    
    for msg_key, msg_param in test_cases:
        await send_with_msgkey(access_token, media_id, USER_ID, msg_key, msg_param)
    
    # Cleanup
    os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
