"""Test script for WeChat Work file handling.

企业微信文件处理功能测试脚本
"""

import os
import sys
import asyncio
import tempfile
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from mcp_servers.im_server.providers.wechat_work.file_handler import (
    FileDecryptor,
    FileDownloader,
    FileManager,
    download_wechat_file,
    get_file_manager,
    get_file_downloader
)


async def test_decrypt():
    """Test AES-256-CBC decryption"""
    print("\n" + "="*60)
    print("Test 1: AES-256-CBC Decryption (with Base64 key)")
    print("="*60)
    
    try:
        # 创建测试数据 (模拟加密数据)
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        import base64
        
        # 32字节原始密钥
        raw_key = b"0123456789abcdef0123456789abcdef"
        # Base64 编码后的密钥 (企业微信返回的格式)
        test_key_b64 = base64.b64encode(raw_key).decode('utf-8')
        
        print(f"Raw key: {raw_key}")
        print(f"Base64 encoded key: {test_key_b64}")
        
        original_data = b"Hello, WeChat Work File!"
        
        # 加密测试数据 (使用原始密钥)
        iv = raw_key[:16]
        
        padder = padding.PKCS7(256).padder()
        padded_data = padder.update(original_data) + padder.finalize()
        
        cipher = Cipher(algorithms.AES(raw_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
        
        print(f"Original: {original_data}")
        print(f"Encrypted: {encrypted_data.hex()[:50]}...")
        
        # 测试解密 (传入 Base64 编码的密钥)
        decrypted_data = FileDecryptor.decrypt(encrypted_data, test_key_b64)
        
        assert decrypted_data == original_data, "Decryption mismatch!"
        print(f"Decrypted: {decrypted_data}")
        print("✅ AES decryption test passed!")
        
    except Exception as e:
        print(f"❌ Decryption test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_file_downloader():
    """Test file download functionality with new path structure"""
    print("\n" + "="*60)
    print("Test 2: File Downloader (with new path structure)")
    print("="*60)
    
    try:
        downloader = FileDownloader()
        
        # 测试下载一个小文件 (使用公开的测试文件)
        test_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        test_provider = "wechat_work"
        test_chat_id = "chat_group_123"
        test_user_id = "user_abc123"
        
        print(f"Downloading from: {test_url}")
        print(f"Provider: {test_provider}")
        print(f"Chat ID: {test_chat_id}")
        print(f"User ID: {test_user_id}")
        
        # 测试群聊场景 (使用 chat_id)
        file_info = await downloader.download(
            url=test_url,
            aes_key=None,
            filename="test_group_file.pdf",
            provider=test_provider,
            chat_id=test_chat_id,
            user_id=test_user_id
        )
        
        print(f"✅ Downloaded successfully (group chat):")
        print(f"   Name: {file_info.name}")
        print(f"   Size: {file_info.size} bytes")
        print(f"   MIME: {file_info.mime_type}")
        print(f"   Path: {file_info.local_path}")
        
        # 验证路径结构: ~/.sage/files/im/{provider}/{chat_id}/
        assert "im" in file_info.local_path, "Path should contain 'im'!"
        assert test_provider in file_info.local_path, "Path should contain provider!"
        assert test_chat_id in file_info.local_path, "Path should contain chat_id!"
        print("✅ Path structure verification passed!")
        
        # 验证文件存在
        assert os.path.exists(file_info.local_path), "File not found!"
        print("✅ File exists verification passed!")
        
        # 清理
        os.remove(file_info.local_path)
        
        # 测试单聊场景 (只使用 user_id)
        print("\n--- Testing private chat scenario ---")
        file_info2 = await downloader.download(
            url=test_url,
            aes_key=None,
            filename="test_private_file.pdf",
            provider=test_provider,
            chat_id=None,  # 单聊没有 chat_id
            user_id=test_user_id
        )
        
        print(f"✅ Downloaded successfully (private chat):")
        print(f"   Path: {file_info2.local_path}")
        assert test_user_id in file_info2.local_path, "Path should contain user_id!"
        print("✅ Private chat path verification passed!")
        
        os.remove(file_info2.local_path)
        
        await downloader.close()
        
    except Exception as e:
        print(f"❌ Download test failed: {e}")
        import traceback
        traceback.print_exc()


def test_get_sage_files_dir():
    """Test the new path structure"""
    print("\n" + "="*60)
    print("Test 3: New Path Structure")
    print("="*60)
    
    try:
        from mcp_servers.im_server.providers.wechat_work.file_handler import get_sage_files_dir
        
        # 测试1: 基础路径
        base_dir = get_sage_files_dir()
        print(f"Base dir: {base_dir}")
        assert "im" in str(base_dir), "Base path should contain 'im'"
        
        # 测试2: 带 provider
        provider_dir = get_sage_files_dir(provider="wechat_work")
        print(f"Provider dir: {provider_dir}")
        assert "wechat_work" in str(provider_dir), "Path should contain provider"
        
        # 测试3: 带 provider 和 chat_id (群聊)
        group_dir = get_sage_files_dir(provider="wechat_work", chat_id="group_123")
        print(f"Group dir: {group_dir}")
        assert "group_123" in str(group_dir), "Path should contain chat_id"
        
        # 测试4: 带 provider 和 user_id (单聊)
        user_dir = get_sage_files_dir(provider="wechat_work", user_id="user_456")
        print(f"User dir: {user_dir}")
        assert "user_456" in str(user_dir), "Path should contain user_id"
        
        # 测试5: chat_id 优先于 user_id
        mixed_dir = get_sage_files_dir(provider="feishu", chat_id="chat_abc", user_id="user_xyz")
        print(f"Mixed dir (chat_id优先): {mixed_dir}")
        assert "chat_abc" in str(mixed_dir), "Path should contain chat_id (priority)"
        
        print("✅ New path structure test passed!")
        
    except Exception as e:
        print(f"❌ Path structure test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_file_manager():
    """Test file manager functionality"""
    print("\n" + "="*60)
    print("Test 4: File Manager")
    print("="*60)
    
    try:
        manager = FileManager(max_age_hours=1)
        
        # 创建测试文件
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        temp_file.write(b"Test file content")
        temp_file.close()
        
        from dataclasses import dataclass, field
        from datetime import datetime
        
        @dataclass
        class MockFileInfo:
            name: str
            size: int
            mime_type: str
            local_path: str
            url: str = None
            aes_key: str = None
            download_time: datetime = field(default_factory=datetime.now)
            
            @property
            def is_encrypted(self):
                return self.aes_key is not None
        
        file_info = MockFileInfo(
            name="test.txt",
            size=17,
            mime_type="text/plain",
            local_path=temp_file.name
        )
        
        # 注册文件
        file_id = manager.register_file(file_info)
        print(f"✅ Registered file with ID: {file_id}")
        
        # 获取文件
        retrieved = manager.get_file(file_id)
        assert retrieved is not None, "File not found in manager!"
        print(f"✅ Retrieved file: {retrieved.name}")
        
        # 获取统计
        stats = manager.get_stats()
        print(f"✅ Stats: {stats}")
        
        # 清理
        os.remove(temp_file.name)
        
        print("✅ File manager test passed!")
        
    except Exception as e:
        print(f"❌ File manager test failed: {e}")
        import traceback
        traceback.print_exc()


def test_mime_detection():
    """Test MIME type detection"""
    print("\n" + "="*60)
    print("Test 4: MIME Type Detection")
    print("="*60)
    
    try:
        downloader = FileDownloader()
        
        test_cases = [
            (b"\x89PNG\r\n\x1a\n", "image.png", "image/png"),
            (b"\xff\xd8\xff\xe0", "image.jpg", "image/jpeg"),
            (b"GIF87a", "image.gif", "image/gif"),
            (b"%PDF-1.4", "doc.pdf", "application/pdf"),
            (b"PK\x03\x04", "archive.zip", "application/zip"),
            (b"Hello World", "text.txt", "text/plain"),
        ]
        
        for data, filename, expected in test_cases:
            detected = downloader._detect_mime_type(filename, data)
            status = "✅" if detected == expected else "❌"
            print(f"{status} {filename}: {detected}")
        
        print("✅ MIME detection test completed!")
        
    except Exception as e:
        print(f"❌ MIME detection test failed: {e}")


async def test_message_parsing():
    """Test message parsing with file info"""
    print("\n" + "="*60)
    print("Test 5: Message Parsing (File Types)")
    print("="*60)
    
    # 模拟企业微信消息格式
    test_messages = [
        {
            "name": "Text Message",
            "body": {
                "msgtype": "text",
                "text": {"content": "Hello World"}
            }
        },
        {
            "name": "Image Message",
            "body": {
                "msgtype": "image",
                "image": {
                    "url": "https://example.com/image.jpg",
                    "aeskey": "0123456789abcdef0123456789abcdef"
                }
            }
        },
        {
            "name": "File Message",
            "body": {
                "msgtype": "file",
                "file": {
                    "url": "https://example.com/doc.pdf",
                    "aeskey": "0123456789abcdef0123456789abcdef",
                    "filename": "report.pdf"
                }
            }
        },
        {
            "name": "Voice Message",
            "body": {
                "msgtype": "voice",
                "voice": {
                    "url": "https://example.com/voice.mp3",
                    "aeskey": "0123456789abcdef0123456789abcdef"
                }
            }
        },
        {
            "name": "Video Message",
            "body": {
                "msgtype": "video",
                "video": {
                    "url": "https://example.com/video.mp4",
                    "aeskey": "0123456789abcdef0123456789abcdef"
                }
            }
        }
    ]
    
    for msg in test_messages:
        body = msg["body"]
        msg_type = body.get("msgtype")
        print(f"\nTesting: {msg['name']} (type: {msg_type})")
        
        # 模拟解析逻辑
        if msg_type == "text":
            content = body.get("text", {}).get("content", "")
            print(f"  Content: {content}")
        elif msg_type in ["image", "voice", "file", "video"]:
            media_data = body.get(msg_type, {})
            file_url = media_data.get("url")
            aes_key = media_data.get("aeskey")
            filename = media_data.get("filename", f"{msg_type}_file")
            
            print(f"  URL: {file_url}")
            print(f"  AES Key: {aes_key[:10]}..." if aes_key else "  No encryption")
            print(f"  Filename: {filename}")
        
        print("  ✅ Parsed successfully")
    
    print("\n✅ Message parsing test completed!")


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("WeChat Work File Handler Test Suite")
    print("="*60)
    
    await test_decrypt()
    await test_file_downloader()
    test_get_sage_files_dir()  # 新增：测试新路径结构
    await test_file_manager()
    test_mime_detection()
    await test_message_parsing()
    
    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
