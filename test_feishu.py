#!/usr/bin/env python3
"""
飞书连接测试脚本
用于验证飞书 App ID 和 App Secret 是否有效，并检查必要的权限
"""

import asyncio
import httpx
import sys

# 飞书配置
APP_ID = "cli_a935550491b8dccd"
APP_SECRET = "fNbNaFUyq1BR8232VstpIeuGflb2PYWy"

async def test_feishu_connection():
    """测试飞书连接和权限"""
    
    print("=" * 60)
    print("飞书连接测试")
    print("=" * 60)
    print(f"App ID: {APP_ID}")
    print()
    
    token = None
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 步骤 1: 获取 tenant_access_token
        print("步骤 1: 获取 tenant_access_token...")
        try:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": APP_ID, "app_secret": APP_SECRET}
            )
            data = resp.json()
            
            if data.get("code") != 0:
                print(f"❌ 获取 token 失败: {data.get('msg')} (错误码: {data.get('code')})")
                print()
                print("可能的原因:")
                print("  - App ID 错误")
                print("  - App Secret 错误")
                print("  - 应用被删除")
                return False
            
            token = data.get("tenant_access_token")
            expire = data.get("expire")
            print(f"✅ Token 获取成功")
            print(f"   Token 预览: {token[:20]}...")
            print(f"   有效期: {expire} 秒 ({expire // 60} 分钟)")
            print()
            
        except Exception as e:
            print(f"❌ 获取 token 时出错: {e}")
            return False
        
        # 步骤 2: 测试 Bot 信息
        print("步骤 2: 检查 Bot 信息...")
        try:
            resp = await client.get(
                "https://open.feishu.cn/open-apis/bot/v3/info/",
                headers={"Authorization": f"Bearer {token}"}
            )
            data = resp.json()
            
            if data.get("code") == 0:
                bot_info = data.get("data", {}).get("bot", {})
                activate_status = bot_info.get('activate_status', 0)
                
                print(f"✅ Bot 信息获取成功")
                print(f"   Bot 名称: {bot_info.get('bot_name', '未设置')}")
                print(f"   激活状态: {'✅ 已激活' if activate_status == 1 else '❌ 未激活'}")
                
                if activate_status != 1:
                    print()
                    print("⚠️  警告: Bot 未激活")
                    print("   解决方法:")
                    print("   1. 进入飞书开放平台 → 你的应用")
                    print("   2. 点击'版本管理与发布'")
                    print("   3. 创建新版本并发布")
            elif data.get("code") == 99991663:
                print(f"⚠️  没有获取 Bot 信息的权限")
                print(f"   这通常意味着应用未发布或缺少权限")
            else:
                print(f"⚠️  获取 Bot 信息失败: {data.get('msg')} (错误码: {data.get('code')})")
            print()
            
        except Exception as e:
            print(f"⚠️  检查 Bot 信息时出错: {e}")
            print()
        
        # 步骤 3: 检查应用信息
        print("步骤 3: 检查应用详情...")
        try:
            resp = await client.get(
                "https://open.feishu.cn/open-apis/application/v3/apps/",
                headers={"Authorization": f"Bearer {token}"}
            )
            data = resp.json()
            
            if data.get("code") == 0:
                apps = data.get("data", {}).get("apps", [])
                print(f"✅ 应用列表获取成功")
                print(f"   应用数量: {len(apps)}")
                for app in apps[:3]:  # 只显示前3个
                    print(f"   - {app.get('app_name')} ({app.get('app_id')})")
            elif data.get("code") == 99991663:
                print(f"⚠️  没有权限获取应用列表")
                print(f"   错误码: 99991663")
                print()
                print("解决方法:")
                print("  1. 确认应用已发布（版本管理与发布 → 创建版本）")
                print("  2. 确认有权限管理应用")
            else:
                print(f"⚠️  获取应用列表失败: {data.get('msg')} (错误码: {data.get('code')})")
            print()
            
        except Exception as e:
            print(f"⚠️  检查应用详情时出错: {e}")
            print()
        
        # 步骤 4: 检查可访问的群组
        print("步骤 4: 检查群组访问权限...")
        try:
            resp = await client.get(
                "https://open.feishu.cn/open-apis/im/v1/chats",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 5}
            )
            data = resp.json()
            
            if data.get("code") == 0:
                chats = data.get("data", {}).get("items", [])
                print(f"✅ 群组列表获取成功")
                print(f"   可访问群组数: {len(chats)}")
                for chat in chats[:3]:
                    print(f"   - {chat.get('name', '未命名')}")
            elif data.get("code") == 99991663:
                print(f"⚠️  没有权限获取群组列表")
                print(f"   需要在飞书后台添加权限: im:chat:readonly")
            else:
                print(f"⚠️  获取群组列表失败: {data.get('msg')} (错误码: {data.get('code')})")
            print()
            
        except Exception as e:
            print(f"⚠️  检查群组权限时出错: {e}")
            print()
        
        # 总结
        print("=" * 60)
        print("测试总结")
        print("=" * 60)
        print("✅ 凭证有效: App ID 和 App Secret 正确")
        print()
        print("下一步操作:")
        print("  1. 进入飞书开放平台: https://open.feishu.cn/")
        print("  2. 找到你的应用，点击进入")
        print("  3. 权限管理 → 添加以下权限:")
        print("     - im:message:send (发送消息)")
        print("     - im:message:readonly (接收消息)")
        print("     - im:chat:readonly (读取群组)")
        print("  4. 事件订阅 → 开启长连接 → 添加事件:")
        print("     - im.message.receive_v1")
        print("  5. 版本管理与发布 → 创建版本 → 申请发布")
        print()
        print("应用必须在发布后才能在群组中使用！")
        print()
        
        return True

if __name__ == "__main__":
    success = asyncio.run(test_feishu_connection())
    sys.exit(0 if success else 1)
