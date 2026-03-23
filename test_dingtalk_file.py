"""Test script for DingTalk file sending"""

import asyncio
import httpx
import os

# Your DingTalk credentials
APP_KEY = "ding0r0dvbzyqzh4wcgb"
APP_SECRET = "B6CP3YlaVH4GDCNdjUMHlmA54y0wqR7tDiMXhnk7Z1ch03rAV4DKxsvMqME7iIjb"
USER_ID = "0357302154213522476"

async def get_access_token():
    """Get access token"""
    url = "https://oapi.dingtalk.com/gettoken"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"appkey": APP_KEY, "appsecret": APP_SECRET})
        data = resp.json()
        print(f"Token response: {data}")
        return data.get("access_token")

async def upload_file(access_token, file_path):
    """Upload file to get media_id"""
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
        print(f"Upload response: {data}")
        return data.get("media_id")

async def send_file_v1(access_token, media_id, user_id):
    """Test v1.0 API - sampleFile"""
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    payload = {
        "robotCode": APP_KEY,
        "userIds": [user_id],
        "msgKey": "sampleFile",
        "msgParam": f'{{"media_id": "{media_id}"}}'
    }
    print(f"\nTest v1.0 API (sampleFile):")
    print(f"URL: {url}")
    print(f"Payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"x-acs-dingtalk-access-token": access_token},
            json=payload
        )
        data = resp.json()
        print(f"Response: {data}")
        return data

async def send_file_v2(access_token, media_id, user_id):
    """Test using media_id directly in msgParam"""
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    payload = {
        "robotCode": APP_KEY,
        "userIds": [user_id],
        "msgKey": "sampleFile",
        "msgParam": f'"{media_id}"'  # Just the media_id as string
    }
    print(f"\nTest v2 API (media_id as string):")
    print(f"Payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"x-acs-dingtalk-access-token": access_token},
            json=payload
        )
        data = resp.json()
        print(f"Response: {data}")
        return data

async def send_file_v3(access_token, media_id, user_id):
    """Test using file_id instead of media_id"""
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    payload = {
        "robotCode": APP_KEY,
        "userIds": [user_id],
        "msgKey": "sampleFile",
        "msgParam": f'{{"file_id": "{media_id}"}}'
    }
    print(f"\nTest v3 API (file_id):")
    print(f"Payload: {payload}")
    
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
        f.write("This is a test file for DingTalk file sending.")
    
    # Get access token
    access_token = await get_access_token()
    if not access_token:
        print("Failed to get access token")
        return
    
    # Upload file
    media_id = await upload_file(access_token, test_file)
    if not media_id:
        print("Failed to upload file")
        return
    
    print(f"\nMedia ID: {media_id}")
    
    # Test different API formats
    await send_file_v1(access_token, media_id, USER_ID)
    await send_file_v2(access_token, media_id, USER_ID)
    await send_file_v3(access_token, media_id, USER_ID)
    
    # Cleanup
    os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
