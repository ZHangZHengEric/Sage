#!/usr/bin/env python3
"""
测试工作流功能的脚本
"""

import requests
import json
import time

def test_workflow_endpoint():
    """测试工作流接口"""
    
    # 测试数据 - 使用新的嵌套对象格式的工作流
    test_data = {
        "type": "chat",
        "messages": [
            {
                "role": "user",
                "content": "我想开发一个AI图像识别系统，请帮我规划开发流程",
                "message_id": "test-msg-1"
            }
        ],
        "use_deepthink": True,
        "use_multi_agent": True,
        "session_id": "test-session-123",
        "system_context": {
            "available_workflows": {
                "代码开发流程": {
                    "root": {
                        "id": "root",
                        "name": "代码开发流程",
                        "description": "完整的代码开发生命周期",
                        "order": 1,
                        "substeps": {
                            "analysis": {
                                "id": "analysis", 
                                "name": "需求分析",
                                "description": "理解项目需求和目标",
                                "order": 1,
                                "substeps": {
                                    "tech_selection": {
                                        "id": "tech_selection",
                                        "name": "技术选型",
                                        "description": "选择合适的技术栈",
                                        "order": 1
                                    },
                                    "architecture": {
                                        "id": "architecture",
                                        "name": "架构设计", 
                                        "description": "设计系统架构",
                                        "order": 2
                                    }
                                }
                            },
                            "implementation": {
                                "id": "implementation",
                                "name": "编码实现",
                                "description": "编写核心功能代码",
                                "order": 2,
                                "substeps": {
                                    "frontend": {
                                        "id": "frontend",
                                        "name": "前端开发",
                                        "description": "实现用户界面",
                                        "order": 1
                                    },
                                    "backend": {
                                        "id": "backend",
                                        "name": "后端开发",
                                        "description": "实现业务逻辑",
                                        "order": 2
                                    },
                                    "database": {
                                        "id": "database",
                                        "name": "数据库设计",
                                        "description": "设计数据存储方案",
                                        "order": 3
                                    }
                                }
                            },
                            "testing": {
                                "id": "testing",
                                "name": "测试验证",
                                "description": "进行各种测试",
                                "order": 3,
                                "substeps": {
                                    "unit_test": {
                                        "id": "unit_test",
                                        "name": "单元测试",
                                        "description": "测试各个组件",
                                        "order": 1
                                    },
                                    "integration_test": {
                                        "id": "integration_test",
                                        "name": "集成测试",
                                        "description": "测试系统整合",
                                        "order": 2
                                    }
                                }
                            },
                            "deployment": {
                                "id": "deployment",
                                "name": "部署上线",
                                "description": "部署到生产环境",
                                "order": 4
                            }
                        }
                    }
                },
                "AI项目开发": {
                    "root": {
                        "id": "ai_root",
                        "name": "AI项目开发",
                        "description": "人工智能项目的完整开发流程",
                        "order": 1,
                        "substeps": {
                            "problem_definition": {
                                "id": "problem_definition",
                                "name": "问题定义",
                                "description": "明确AI要解决的问题",
                                "order": 1,
                                "substeps": {
                                    "business_analysis": {
                                        "id": "business_analysis",
                                        "name": "业务分析",
                                        "description": "分析业务需求和场景",
                                        "order": 1
                                    },
                                    "success_metrics": {
                                        "id": "success_metrics",
                                        "name": "成功指标",
                                        "description": "定义项目成功的衡量标准",
                                        "order": 2
                                    }
                                }
                            },
                            "data_preparation": {
                                "id": "data_preparation",
                                "name": "数据准备",
                                "description": "准备训练和测试数据",
                                "order": 2,
                                "substeps": {
                                    "data_collection": {
                                        "id": "data_collection",
                                        "name": "数据收集",
                                        "description": "收集相关数据",
                                        "order": 1
                                    },
                                    "data_cleaning": {
                                        "id": "data_cleaning",
                                        "name": "数据清洗",
                                        "description": "清理和预处理数据",
                                        "order": 2
                                    },
                                    "data_labeling": {
                                        "id": "data_labeling",
                                        "name": "数据标注",
                                        "description": "为监督学习标注数据",
                                        "order": 3
                                    }
                                }
                            },
                            "model_development": {
                                "id": "model_development",
                                "name": "模型开发",
                                "description": "开发和训练AI模型",
                                "order": 3,
                                "substeps": {
                                    "model_selection": {
                                        "id": "model_selection",
                                        "name": "模型选择",
                                        "description": "选择合适的模型架构",
                                        "order": 1
                                    },
                                    "training": {
                                        "id": "training",
                                        "name": "模型训练",
                                        "description": "训练模型参数",
                                        "order": 2,
                                        "substeps": {
                                            "hyperparameter_tuning": {
                                                "id": "hyperparameter_tuning",
                                                "name": "超参数调优",
                                                "description": "优化模型超参数",
                                                "order": 1
                                            },
                                            "cross_validation": {
                                                "id": "cross_validation",
                                                "name": "交叉验证",
                                                "description": "验证模型泛化能力",
                                                "order": 2
                                            }
                                        }
                                    },
                                    "evaluation": {
                                        "id": "evaluation",
                                        "name": "模型评估",
                                        "description": "评估模型性能",
                                        "order": 3
                                    }
                                }
                            },
                            "deployment": {
                                "id": "ai_deployment",
                                "name": "模型部署",
                                "description": "将模型部署到生产环境",
                                "order": 4,
                                "substeps": {
                                    "model_optimization": {
                                        "id": "model_optimization",
                                        "name": "模型优化",
                                        "description": "优化模型以提高推理速度",
                                        "order": 1
                                    },
                                    "api_development": {
                                        "id": "api_development",
                                        "name": "API开发",
                                        "description": "开发模型服务API",
                                        "order": 2
                                    },
                                    "monitoring": {
                                        "id": "monitoring",
                                        "name": "监控系统",
                                        "description": "建立模型性能监控",
                                        "order": 3
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    
    print("🚀 开始测试工作流功能...")
    print(f"📊 测试数据: {json.dumps(test_data, ensure_ascii=False, indent=2)}")
    
    try:
        # 发送请求到后端
        url = "http://localhost:20039/api/chat-stream"
        headers = {"Content-Type": "application/json"}
        
        print(f"🌐 发送请求到: {url}")
        response = requests.post(url, json=test_data, headers=headers, stream=True)
        
        if response.status_code == 200:
            print("✅ 请求成功，开始接收流式响应...")
            
            # 处理流式响应
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        try:
                            data_str = line_str[6:]  # 去掉 'data: ' 前缀
                            if data_str.strip():
                                data = json.loads(data_str)
                                print(f"📦 收到数据: {data.get('type', 'unknown')} - {data.get('content', '')[:100]}...")
                                
                                # 如果收到工作流选择信息，特别显示
                                if 'workflow' in str(data).lower():
                                    print(f"🔄 工作流信息: {json.dumps(data, ensure_ascii=False, indent=2)}")
                                    
                        except json.JSONDecodeError as e:
                            print(f"⚠️ JSON解析失败: {e}")
                            print(f"原始数据: {data_str[:200]}...")
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保后端服务正在运行")
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")

def test_simple_api():
    """测试简单的API连接"""
    try:
        print("🔗 测试基础API连接...")
        response = requests.get("http://localhost:20039/", timeout=5)
        if response.status_code == 200:
            print("✅ 后端服务连接正常")
            return True
        else:
            print(f"⚠️ 后端服务响应异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 后端服务连接失败: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Sage 工作流功能测试")
    print("=" * 60)
    
    # 先测试基础连接
    if test_simple_api():
        print("\n" + "=" * 60)
        print("🔄 开始测试工作流功能")
        print("=" * 60)
        test_workflow_endpoint()
    else:
        print("❌ 基础连接测试失败，请检查服务状态")
    
    print("\n" + "=" * 60)
    print("🏁 测试完成")
    print("=" * 60) 