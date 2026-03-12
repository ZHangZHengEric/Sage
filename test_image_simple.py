"""
简单测试图片理解工具的核心功能
"""
import base64
from pathlib import Path

def test_base64_encoding():
    """测试 base64 编码功能"""
    image_path = "/Users/zhangzheng/zavixai/Sage/app/wiki/public/images/chat-workspace.png"
    
    print(f"🔍 测试图片 base64 编码")
    print(f"图片路径: {image_path}")
    print("-" * 50)
    
    # 检查文件是否存在
    path_obj = Path(image_path)
    if not path_obj.exists():
        print(f"❌ 图片文件不存在: {image_path}")
        return False
    
    print(f"✅ 图片文件存在，大小: {path_obj.stat().st_size} bytes")
    
    # 测试 base64 编码
    try:
        with open(path_obj, 'rb') as f:
            image_data = f.read()
        base64_data = base64.b64encode(image_data).decode('utf-8')
        print(f"✅ Base64 编码成功，长度: {len(base64_data)} 字符")
        
        # 验证 base64 可以解码
        decoded = base64.b64decode(base64_data)
        print(f"✅ Base64 解码成功，长度: {len(decoded)} bytes")
        
        return True
    except Exception as e:
        print(f"❌ Base64 编码失败: {e}")
        return False

def test_mime_type():
    """测试 MIME 类型获取"""
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
    }
    
    test_cases = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
    
    print("\n🔍 测试 MIME 类型获取")
    print("-" * 50)
    
    for ext in test_cases:
        mime = mime_types.get(ext.lower(), 'image/jpeg')
        print(f"  {ext} -> {mime}")
    
    return True

if __name__ == "__main__":
    success1 = test_base64_encoding()
    success2 = test_mime_type()
    
    print("\n" + "=" * 50)
    if success1 and success2:
        print("✅ 所有测试通过")
    else:
        print("❌ 部分测试失败")
