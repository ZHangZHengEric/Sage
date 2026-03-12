"""
测试图片理解工具
"""
import asyncio
import os
from sagents.tool.impl.image_understanding_tool import ImageUnderstandingTool

async def test_image_understanding():
    """测试图片理解工具"""
    tool = ImageUnderstandingTool()
    
    # 测试图片路径
    image_path = "/Users/zhangzheng/zavixai/Sage/app/wiki/public/images/chat-workspace.png"
    
    print(f"🔍 测试图片理解工具")
    print(f"图片路径: {image_path}")
    print("-" * 50)
    
    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"❌ 图片文件不存在: {image_path}")
        return
    
    print(f"✅ 图片文件存在，大小: {os.path.getsize(image_path)} bytes")
    
    # 测试分析图片
    try:
        result = await tool.analyze_image(image_path)
        
        print("\n📊 测试结果:")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        if result.get('status') == 'success':
            print("\n📝 图片分析结果:")
            print(result.get('data', {}).get('description', '无描述'))
        else:
            print(f"\n❌ 错误: {result.get('message')}")
            
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_image_understanding())
