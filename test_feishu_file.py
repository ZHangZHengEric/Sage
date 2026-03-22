#!/usr/bin/env python3
"""
飞书文件发送功能测试脚本

测试内容:
1. 获取 tenant_access_token
2. 发送文本消息
3. 上传文件
4. 发送文件消息
5. 上传图片
6. 发送图片消息

使用方法:
    python3 test_feishu_file.py [chat_id]

参数:
    chat_id: 飞书群聊 ID（可选，如果不提供则只测试上传功能）

环境变量:
    FEISHU_APP_ID: 飞书 App ID
    FEISHU_APP_SECRET: 飞书 App Secret
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 飞书配置 - 从环境变量或默认值读取
APP_ID = os.environ.get("FEISHU_APP_ID", "cli_a935550491b8dccd")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "fNbNaFUyq1BR8232VstpIeuGflb2PYWy")

# 测试文件路径
TEST_DIR = Path("/tmp/feishu_test")
TEST_TEXT_FILE = TEST_DIR / "test_document.txt"
TEST_IMAGE_FILE = TEST_DIR / "test_image.png"


async def setup_test_files():
    """创建测试文件"""
    TEST_DIR.mkdir(exist_ok=True)
    
    # 创建测试文本文件
    TEST_TEXT_FILE.write_text(
        "这是飞书文件发送测试\n"
        "测试时间: " + str(asyncio.get_event_loop().time()) + "\n"
        "测试内容: Sage 自动生成的测试文档\n"
    )
    print(f"✅ 创建测试文本文件: {TEST_TEXT_FILE}")
    
    # 创建测试图片（简单的 1x1 像素 PNG）
    if not TEST_IMAGE_FILE.exists():
        # 最简单的 PNG 图片数据（1x1 像素，红色）
        png_data = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG 签名
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 像素
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
            0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xFE,
            0xD7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
            0x44, 0xAE, 0x42, 0x60, 0x82
        ])
        TEST_IMAGE_FILE.write_bytes(png_data)
    print(f"✅ 创建测试图片文件: {TEST_IMAGE_FILE}")


async def test_get_token():
    """测试 1: 获取 tenant_access_token"""
    print("\n" + "=" * 60)
    print("测试 1: 获取 tenant_access_token")
    print("=" * 60)
    
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": APP_ID, "app_secret": APP_SECRET}
            )
            data = resp.json()
            
            if data.get("code") == 0:
                token = data.get("tenant_access_token")
                expire = data.get("expire")
                print(f"✅ Token 获取成功")
                print(f"   Token 预览: {token[:30]}...")
                print(f"   有效期: {expire} 秒 ({expire // 60} 分钟)")
                return token
            else:
                print(f"❌ Token 获取失败")
                print(f"   错误码: {data.get('code')}")
                print(f"   错误信息: {data.get('msg')}")
                return None
    except Exception as e:
        print(f"❌ 获取 Token 时出错: {e}")
        return None


async def test_upload_file(token: str) -> str:
    """测试 2: 上传文件"""
    print("\n" + "=" * 60)
    print("测试 2: 上传文件")
    print("=" * 60)
    print(f"文件: {TEST_TEXT_FILE}")
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(TEST_TEXT_FILE, "rb") as f:
                files = {"file": ("test_document.txt", f, "text/plain")}
                data = {"file_type": "stream", "file_name": "test_document.txt"}
                
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/files",
                    headers={"Authorization": f"Bearer {token}"},
                    data=data,
                    files=files,
                )
            
            result = resp.json()
            if result.get("code") == 0:
                file_key = result.get("data", {}).get("file_key")
                print(f"✅ 文件上传成功")
                print(f"   file_key: {file_key}")
                return file_key
            else:
                print(f"❌ 文件上传失败")
                print(f"   错误码: {result.get('code')}")
                print(f"   错误信息: {result.get('msg')}")
                return None
    except Exception as e:
        print(f"❌ 上传文件时出错: {e}")
        return None


async def test_send_file_message(token: str, file_key: str, chat_id: str = None):
    """测试 3: 发送文件消息"""
    print("\n" + "=" * 60)
    print("测试 3: 发送文件消息")
    print("=" * 60)
    
    if not chat_id:
        print("⚠️  未提供 chat_id，跳过发送消息测试")
        print("   如需测试发送消息，请提供 chat_id 参数")
        return False
    
    try:
        import httpx
        import json
        
        content = json.dumps({"file_key": file_key}, ensure_ascii=False)
        message = {
            "receive_id": chat_id,
            "msg_type": "file",
            "content": content
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={"Authorization": f"Bearer {token}"},
                json=message,
            )
        
        result = resp.json()
        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id")
            print(f"✅ 文件消息发送成功")
            print(f"   message_id: {message_id}")
            return True
        else:
            print(f"❌ 文件消息发送失败")
            print(f"   错误码: {result.get('code')}")
            print(f"   错误信息: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"❌ 发送文件消息时出错: {e}")
        return False


async def test_upload_image(token: str) -> str:
    """测试 4: 上传图片"""
    print("\n" + "=" * 60)
    print("测试 4: 上传图片")
    print("=" * 60)
    print(f"图片: {TEST_IMAGE_FILE}")
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(TEST_IMAGE_FILE, "rb") as f:
                files = {"image": ("test.png", f, "image/png")}
                data = {"image_type": "message"}
                
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/images",
                    headers={"Authorization": f"Bearer {token}"},
                    data=data,
                    files=files,
                )
            
            result = resp.json()
            if result.get("code") == 0:
                image_key = result.get("data", {}).get("image_key")
                print(f"✅ 图片上传成功")
                print(f"   image_key: {image_key}")
                return image_key
            else:
                print(f"❌ 图片上传失败")
                print(f"   错误码: {result.get('code')}")
                print(f"   错误信息: {result.get('msg')}")
                return None
    except Exception as e:
        print(f"❌ 上传图片时出错: {e}")
        return None


async def test_send_image_message(token: str, image_key: str, chat_id: str = None):
    """测试 5: 发送图片消息"""
    print("\n" + "=" * 60)
    print("测试 5: 发送图片消息")
    print("=" * 60)
    
    if not chat_id:
        print("⚠️  未提供 chat_id，跳过发送消息测试")
        return False
    
    try:
        import httpx
        import json
        
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)
        message = {
            "receive_id": chat_id,
            "msg_type": "image",
            "content": content
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={"Authorization": f"Bearer {token}"},
                json=message,
            )
        
        result = resp.json()
        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id")
            print(f"✅ 图片消息发送成功")
            print(f"   message_id: {message_id}")
            return True
        else:
            print(f"❌ 图片消息发送失败")
            print(f"   错误码: {result.get('code')}")
            print(f"   错误信息: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"❌ 发送图片消息时出错: {e}")
        return False


async def main():
    """主测试函数"""
    # 获取命令行参数
    chat_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    print("=" * 60)
    print("飞书文件发送功能测试")
    print("=" * 60)
    print(f"App ID: {APP_ID}")
    if chat_id:
        print(f"测试群聊 ID: {chat_id}")
    else:
        print("模式: 仅测试上传功能（不提供 chat_id）")
    print()
    
    # 创建测试文件
    await setup_test_files()
    
    # 测试 1: 获取 Token
    token = await test_get_token()
    if not token:
        print("\n❌ 测试终止: 无法获取 access token")
        return 1
    
    # 测试 2: 上传文件
    file_key = await test_upload_file(token)
    if file_key and chat_id:
        # 测试 3: 发送文件消息
        await test_send_file_message(token, file_key, chat_id)
    
    # 测试 4: 上传图片
    image_key = await test_upload_image(token)
    if image_key and chat_id:
        # 测试 5: 发送图片消息
        await test_send_image_message(token, image_key, chat_id)
    
    # 总结
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    if not chat_id:
        print("\n提示: 如需测试消息发送功能，请提供 chat_id:")
        print(f"  python3 {sys.argv[0]} <chat_id>")
    print()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
