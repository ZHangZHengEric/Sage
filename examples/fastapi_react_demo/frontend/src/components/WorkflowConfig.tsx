import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Card,
  Form,
  Input,
  Button,
  List,
  Switch,
  Modal,
  message,
  Space,
  Alert,
  Popconfirm,
  Typography,
  Tooltip,
  Select,
  Tag,
  Divider,
  Tree,
  Row,
  Col,
  Badge,
  Collapse,
  Avatar,
  Progress,
  Empty
} from 'antd';
import {
  ForkOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  BranchesOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  CopyOutlined,
  ExportOutlined,
  ImportOutlined,
  SettingOutlined,
  RocketOutlined,
  ThunderboltOutlined,
  StarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  FileTextOutlined,
  DatabaseOutlined,
  TeamOutlined,
  BugOutlined,
  CloudOutlined,
  AppstoreOutlined
} from '@ant-design/icons';
import { useSystem, WorkflowTemplate, WorkflowStep } from '../context/SystemContext';

const { TextArea } = Input;
const { Text, Title } = Typography;
const { Option } = Select;
const { Panel } = Collapse;

// 工作流分类配置
const WORKFLOW_CATEGORIES = [
  { 
    value: 'research', 
    label: '研究分析', 
    color: '#1890ff',
    icon: <RocketOutlined />,
    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
  },
  { 
    value: 'development', 
    label: '代码开发', 
    color: '#52c41a',
    icon: <CodeOutlined />,
    gradient: 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)'
  },
  { 
    value: 'document', 
    label: '文档处理', 
    color: '#fa8c16',
    icon: <FileTextOutlined />,
    gradient: 'linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%)'
  },
  { 
    value: 'data', 
    label: '数据处理', 
    color: '#722ed1',
    icon: <DatabaseOutlined />,
    gradient: 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)'
  },
  { 
    value: 'communication', 
    label: '沟通协作', 
    color: '#eb2f96',
    icon: <TeamOutlined />,
    gradient: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)'
  },
  { 
    value: 'testing', 
    label: '测试验证', 
    color: '#13c2c2',
    icon: <BugOutlined />,
    gradient: 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)'
  },
  { 
    value: 'deployment', 
    label: '部署运维', 
    color: '#fa541c',
    icon: <CloudOutlined />,
    gradient: 'linear-gradient(135deg, #fad0c4 0%, #ffd1ff 100%)'
  },
  { 
    value: 'custom', 
    label: '自定义', 
    color: '#666666',
    icon: <AppstoreOutlined />,
    gradient: 'linear-gradient(135deg, #e3ffe7 0%, #d9e7ff 100%)'
  }
];

// 思维导图节点类型
interface MindMapNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  level: number;
  parentId?: string;
  children: string[];
  color: string;
}

// 思维导图画板组件
const MindMapCanvas: React.FC<{
  nodes: MindMapNode[];
  onNodesChange: (nodes: MindMapNode[]) => void;
  key?: string | number; // 添加key属性来强制重新渲染
}> = ({ nodes, onNodesChange }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  
  // 新增缩放和平移相关状态
  const [scale, setScale] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // 文字换行
  const wrapText = (ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] => {
    const words = text.split('');
    const lines: string[] = [];
    let currentLine = '';
    
    for (const char of words) {
      const testLine = currentLine + char;
      const metrics = ctx.measureText(testLine);
      
      if (metrics.width > maxWidth && currentLine.length > 0) {
        lines.push(currentLine);
        currentLine = char;
      } else {
        currentLine = testLine;
      }
    }
    
    if (currentLine.length > 0) {
      lines.push(currentLine);
    }
    
    return lines;
  };

  // 颜色调整
  const adjustColor = (color: string, amount: number): string => {
    const num = parseInt(color.replace("#", ""), 16);
    const amt = Math.round(2.55 * amount);
    const R = (num >> 16) + amt;
    const G = (num >> 8 & 0x00FF) + amt;
    const B = (num & 0x0000FF) + amt;
    return "#" + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
      (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
      (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1);
  };

  // 绘制函数
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // 清空画布
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // 保存当前变换状态
    ctx.save();
    
    // 应用缩放和平移
    ctx.translate(panOffset.x, panOffset.y);
    ctx.scale(scale, scale);

    // 绘制连接线
    nodes.forEach(node => {
      if (node.parentId) {
        const parent = nodes.find(n => n.id === node.parentId);
        if (parent) {
          ctx.strokeStyle = '#94a3b8';
          ctx.lineWidth = 2;
          ctx.lineCap = 'round';
          
          // 绘制贝塞尔曲线连接线
          ctx.beginPath();
          const startX = parent.x + parent.width;
          const startY = parent.y + parent.height / 2;
          const endX = node.x;
          const endY = node.y + node.height / 2;
          
          const controlPointOffset = Math.min(50, Math.abs(endX - startX) / 2);
          const cp1X = startX + controlPointOffset;
          const cp1Y = startY;
          const cp2X = endX - controlPointOffset;
          const cp2Y = endY;
          
          ctx.moveTo(startX, startY);
          ctx.bezierCurveTo(cp1X, cp1Y, cp2X, cp2Y, endX, endY);
          ctx.stroke();
          
          // 绘制箭头
          const arrowSize = 8;
          const angle = Math.atan2(endY - cp2Y, endX - cp2X);
          
          ctx.beginPath();
          ctx.moveTo(endX, endY);
          ctx.lineTo(
            endX - arrowSize * Math.cos(angle - Math.PI / 6),
            endY - arrowSize * Math.sin(angle - Math.PI / 6)
          );
          ctx.moveTo(endX, endY);
          ctx.lineTo(
            endX - arrowSize * Math.cos(angle + Math.PI / 6),
            endY - arrowSize * Math.sin(angle + Math.PI / 6)
          );
          ctx.stroke();
        }
      }
    });

    // 绘制节点
    nodes.forEach(node => {
      const isSelected = selectedNode === node.id;
      const isEditing = editingNode === node.id;
      
      // 绘制阴影
      if (!isEditing) {
        ctx.shadowColor = 'rgba(0, 0, 0, 0.1)';
        ctx.shadowBlur = isSelected ? 8 : 4;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = isSelected ? 4 : 2;
      }
      
      // 节点背景
      ctx.fillStyle = isSelected ? adjustColor(node.color, -10) : node.color;
      ctx.strokeStyle = isSelected ? '#3b82f6' : adjustColor(node.color, -20);
      ctx.lineWidth = isSelected ? 2 : 1;
      
      // 绘制圆角矩形
      const radius = node.level === 0 ? 12 : 8;
      ctx.beginPath();
      ctx.moveTo(node.x + radius, node.y);
      ctx.lineTo(node.x + node.width - radius, node.y);
      ctx.quadraticCurveTo(node.x + node.width, node.y, node.x + node.width, node.y + radius);
      ctx.lineTo(node.x + node.width, node.y + node.height - radius);
      ctx.quadraticCurveTo(node.x + node.width, node.y + node.height, node.x + node.width - radius, node.y + node.height);
      ctx.lineTo(node.x + radius, node.y + node.height);
      ctx.quadraticCurveTo(node.x, node.y + node.height, node.x, node.y + node.height - radius);
      ctx.lineTo(node.x, node.y + radius);
      ctx.quadraticCurveTo(node.x, node.y, node.x + radius, node.y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      
      // 清除阴影设置
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;

      // 节点文字
      if (!isEditing) {
        ctx.fillStyle = '#ffffff';
        ctx.font = `${node.level === 0 ? 'bold 16px' : node.level === 1 ? '600 14px' : '12px'} system-ui, -apple-system, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        
        const lines = wrapText(ctx, node.text, node.width - 24);
        const lineHeight = node.level === 0 ? 20 : 16;
        const totalHeight = lines.length * lineHeight;
        const startY = node.y + node.height / 2 - totalHeight / 2 + lineHeight / 2;
        
        // 添加文字阴影效果
        ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
        ctx.shadowBlur = 1;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 1;
        
        lines.forEach((line, index) => {
          ctx.fillText(line, node.x + node.width / 2, startY + index * lineHeight);
        });
        
        // 清除文字阴影
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 0;
      }
    });
    
    // 恢复变换状态
    ctx.restore();
  }, [nodes, selectedNode, editingNode, wrapText, adjustColor, scale, panOffset]);

  // 画布尺寸更新（高分辨率支持）
  const updateCanvasSize = useCallback(() => {
    if (canvasRef.current && containerRef.current) {
      const container = containerRef.current;
      const canvas = canvasRef.current;
      const rect = container.getBoundingClientRect();
      
      // 获取设备像素比，提高分辨率
      const dpr = window.devicePixelRatio || 1;
      
      // 设置canvas实际尺寸（CSS像素）
      canvas.style.width = rect.width + 'px';
      canvas.style.height = Math.max(600, rect.height) + 'px';
      
      // 设置canvas内部尺寸（设备像素）
      canvas.width = rect.width * dpr;
      canvas.height = Math.max(600, rect.height) * dpr;
      
      // 缩放绘图上下文以匹配设备像素比
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.scale(dpr, dpr);
      }
      
      // 重新绘制
      draw();
    }
  }, [draw]);

  // 获取鼠标位置（考虑缩放和平移）
  const getMousePos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    
    const rect = canvas.getBoundingClientRect();
    const rawX = e.clientX - rect.left;
    const rawY = e.clientY - rect.top;
    
    // 转换为画布坐标（考虑缩放和平移）
    return {
      x: (rawX - panOffset.x) / scale,
      y: (rawY - panOffset.y) / scale
    };
  };

  // 查找指定位置的节点
  const findNodeAt = (x: number, y: number): MindMapNode | null => {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const node = nodes[i];
      if (x >= node.x && x <= node.x + node.width &&
          y >= node.y && y <= node.y + node.height) {
        return node;
      }
    }
    return null;
  };

  // 鼠标按下事件
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getMousePos(e);
    const node = findNodeAt(pos.x, pos.y);
    
    if (e.button === 2 || e.ctrlKey) { // 右键或Ctrl+左键开始平移
      setIsPanning(true);
      setPanStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
      e.preventDefault();
      return;
    }
    
    if (node) {
      setSelectedNode(node.id);
      setIsDragging(true);
      setDragOffset({
        x: pos.x - node.x,
        y: pos.y - node.y
      });
    } else {
      setSelectedNode(null);
    }
  };

  // 鼠标移动事件
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isPanning) {
      setPanOffset({
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y
      });
    } else if (isDragging && selectedNode) {
      const pos = getMousePos(e);
      const newNodes = nodes.map(node => 
        node.id === selectedNode 
          ? { ...node, x: pos.x - dragOffset.x, y: pos.y - dragOffset.y }
          : node
      );
      onNodesChange(newNodes);
    }
  };

  // 鼠标抬起事件
  const handleMouseUp = () => {
    setIsDragging(false);
    setIsPanning(false);
  };

  // 鼠标滚轮事件（缩放）
  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = Math.max(0.2, Math.min(3, scale * zoomFactor));
    
    // 计算缩放后的偏移，保持鼠标位置不变
    const newPanX = mouseX - (mouseX - panOffset.x) * (newScale / scale);
    const newPanY = mouseY - (mouseY - panOffset.y) * (newScale / scale);
    
    setScale(newScale);
    setPanOffset({ x: newPanX, y: newPanY });
  };

  // 双击编辑
  const handleDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getMousePos(e);
    const node = findNodeAt(pos.x, pos.y);
    
    if (node) {
      setEditingNode(node.id);
      setEditText(node.text);
    }
  };

  // 添加子节点
  const addChildNode = () => {
    if (!selectedNode) return;
    
    const parent = nodes.find(n => n.id === selectedNode);
    if (!parent) return;
    
    const newId = `node-${Date.now()}`;
    // 现代化配色方案 - 蓝色调为主
    const colors = [
      '#4f46e5', // 靛蓝色
      '#06b6d4', // 青色
      '#10b981', // 绿色
      '#f59e0b', // 琥珀色
      '#ef4444', // 红色
      '#8b5cf6', // 紫色
      '#ec4899'  // 粉色
    ];
    const childCount = parent.children.length;
    
    const newNode: MindMapNode = {
      id: newId,
      x: parent.x + parent.width + 50,
      y: parent.y + childCount * 80,
      width: parent.level === 0 ? 150 : 120,
      height: parent.level === 0 ? 60 : 50,
      text: '新步骤',
      level: parent.level + 1,
      parentId: parent.id,
      children: [],
      color: colors[childCount % colors.length]
    };

    const updatedParent = {
      ...parent,
      children: [...parent.children, newId]
    };

    const newNodes = nodes.map(n => n.id === parent.id ? updatedParent : n);
    newNodes.push(newNode);
    
    onNodesChange(newNodes);
    setSelectedNode(newId);
  };

  // 删除节点
  const deleteNode = () => {
    if (!selectedNode) return;
    
    const nodeToDelete = nodes.find(n => n.id === selectedNode);
    if (!nodeToDelete) return;

    // 递归查找所有子节点
    const findChildNodes = (nodeId: string): string[] => {
      const node = nodes.find(n => n.id === nodeId);
      if (!node) return [];
      
      let childIds: string[] = [nodeId];
      node.children.forEach(childId => {
        childIds = childIds.concat(findChildNodes(childId));
      });
      
      return childIds;
    };

    const nodesToDelete = findChildNodes(selectedNode);
    
    // 更新父节点的children数组
    const updatedNodes = nodes
      .filter(n => !nodesToDelete.includes(n.id))
      .map(n => ({
        ...n,
        children: n.children.filter(childId => !nodesToDelete.includes(childId))
      }));
    
    onNodesChange(updatedNodes);
    setSelectedNode(null);
  };

  // 保存编辑
  const saveEdit = () => {
    if (editingNode && editText.trim()) {
      const newNodes = nodes.map(node => 
        node.id === editingNode 
          ? { ...node, text: editText.trim() }
          : node
      );
      onNodesChange(newNodes);
    }
    setEditingNode(null);
    setEditText('');
  };

  // 键盘事件处理
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (editingNode) {
        if (e.key === 'Enter') {
          e.preventDefault();
          saveEdit();
        } else if (e.key === 'Escape') {
          setEditingNode(null);
          setEditText('');
        }
      } else if (selectedNode) {
        if (e.key === 'Delete') {
          deleteNode();
        } else if (e.key === 'Tab') {
          e.preventDefault();
          addChildNode();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [editingNode, selectedNode, editText]);

  // 监听节点变化，重新绘制和自动缩放
  useEffect(() => {
    // 如果节点有自动适应信息，应用它
    if (nodes.length > 0 && (nodes as any).autoFit) {
      const autoFit = (nodes as any).autoFit;
      setScale(autoFit.scale);
      setPanOffset({ x: autoFit.panX, y: autoFit.panY });
    }
    draw();
  }, [draw]);

  // 自动适应功能
  const autoFitNodes = () => {
    if (nodes.length === 0) return;
    
    const canvas = canvasRef.current;
    if (!canvas) return;
    
    // 计算所有节点的边界
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    
    nodes.forEach(node => {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x + node.width);
      minY = Math.min(minY, node.y);
      maxY = Math.max(maxY, node.y + node.height);
    });
    
    // 添加边距
    const margin = 80;
    const contentWidth = maxX - minX + 2 * margin;
    const contentHeight = maxY - minY + 2 * margin;
    
    // 获取实际画布大小
    const rect = canvas.getBoundingClientRect();
    const canvasWidth = rect.width;
    const canvasHeight = rect.height;
    
    // 计算缩放比例
    const scaleX = canvasWidth / contentWidth;
    const scaleY = canvasHeight / contentHeight;
    const newScale = Math.min(scaleX, scaleY, 1.2); // 最大放大到1.2倍
    
    // 计算居中偏移
    const scaledContentWidth = contentWidth * newScale;
    const scaledContentHeight = contentHeight * newScale;
    const panX = (canvasWidth - scaledContentWidth) / 2 - (minX - margin) * newScale;
    const panY = (canvasHeight - scaledContentHeight) / 2 - (minY - margin) * newScale;
    
    setScale(newScale);
    setPanOffset({ x: panX, y: panY });
  };

  // 监听容器大小变化
  useEffect(() => {
    updateCanvasSize();
    
    const resizeObserver = new ResizeObserver(updateCanvasSize);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }
    
    return () => resizeObserver.disconnect();
  }, [updateCanvasSize]);

  return (
    <div 
      ref={containerRef}
      style={{ 
        width: '100%', 
        height: '600px', 
        border: '1px solid #e5e7eb', 
        borderRadius: '12px',
        position: 'relative',
        background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 50%, #cbd5e1 100%)',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)'
      }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onDoubleClick={handleDoubleClick}
        onWheel={handleWheel}
        onContextMenu={(e) => e.preventDefault()}
        style={{ 
          cursor: isPanning ? 'grabbing' : (isDragging ? 'grabbing' : 'grab'),
          borderRadius: '12px'
        }}
      />
      
      {/* 编辑输入框 */}
      {editingNode && (
        <div
          style={{
            position: 'absolute',
            left: nodes.find(n => n.id === editingNode)?.x || 0,
            top: nodes.find(n => n.id === editingNode)?.y || 0,
            zIndex: 1000
          }}
        >
          <Input
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onPressEnter={saveEdit}
            onBlur={saveEdit}
            autoFocus
            style={{ 
              width: nodes.find(n => n.id === editingNode)?.width || 120,
              fontSize: '13px',
              borderRadius: '8px',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
              border: '2px solid #3b82f6'
            }}
          />
        </div>
      )}
      
      {/* 操作按钮 */}
      {selectedNode && (
        <div style={{ 
          position: 'absolute', 
          top: 16, 
          right: 16, 
          background: 'rgba(255, 255, 255, 0.95)',
          backdropFilter: 'blur(8px)',
          padding: '12px',
          borderRadius: '12px',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.05)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <Space>
            <Button 
              size="small" 
              type="primary"
              icon={<PlusOutlined />} 
              onClick={addChildNode}
              style={{ borderRadius: '8px' }}
            >
              添加子步骤
            </Button>
            <Button 
              size="small" 
              danger 
              icon={<DeleteOutlined />} 
              onClick={deleteNode}
              style={{ borderRadius: '8px' }}
            >
              删除
            </Button>
          </Space>
        </div>
      )}
      
      {/* 缩放控制按钮 */}
      <div style={{ 
        position: 'absolute', 
        top: 16, 
        left: 16,
        background: 'rgba(255, 255, 255, 0.95)',
        backdropFilter: 'blur(8px)',
        padding: '8px',
        borderRadius: '10px',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
        border: '1px solid rgba(255, 255, 255, 0.2)'
      }}>
        <Space direction="vertical" size="small">
          <Button 
            size="small" 
            onClick={() => setScale(Math.min(3, scale * 1.2))}
            style={{ borderRadius: '6px', fontSize: '16px', width: 32, height: 32, padding: 0 }}
          >
            +
          </Button>
          <div style={{ textAlign: 'center', fontSize: '12px', color: '#64748b' }}>
            {Math.round(scale * 100)}%
          </div>
          <Button 
            size="small" 
            onClick={() => setScale(Math.max(0.2, scale * 0.8))}
            style={{ borderRadius: '6px', fontSize: '16px', width: 32, height: 32, padding: 0 }}
          >
            -
          </Button>
          <Button 
            size="small" 
            onClick={() => { setScale(1); setPanOffset({ x: 0, y: 0 }); }}
            style={{ borderRadius: '6px', fontSize: '10px', width: 32, height: 28, padding: 0 }}
          >
            重置
          </Button>
          <Button 
            size="small" 
            onClick={autoFitNodes}
            style={{ borderRadius: '6px', fontSize: '9px', width: 32, height: 28, padding: 0 }}
          >
            适应
          </Button>
        </Space>
      </div>

      {/* 操作提示 */}
      <div style={{ 
        position: 'absolute', 
        bottom: 16, 
        left: 16,
        background: 'rgba(255, 255, 255, 0.95)',
        backdropFilter: 'blur(8px)',
        padding: '10px 14px',
        borderRadius: '10px',
        fontSize: '13px',
        color: '#64748b',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
        border: '1px solid rgba(255, 255, 255, 0.2)'
      }}>
        <Text style={{ color: '#64748b', fontSize: '13px' }}>
          💡 滚轮缩放，右键拖拽平移，双击编辑文本
        </Text>
      </div>
    </div>
  );
};

// 将思维导图节点转换为工作流步骤（嵌套对象格式）
const convertNodesToSteps = (nodes: MindMapNode[]): { [key: string]: WorkflowStep } => {
  const steps: { [key: string]: WorkflowStep } = {};

  // 递归转换节点
  const convertNode = (node: MindMapNode): WorkflowStep => {
    const step: WorkflowStep = {
      id: node.id,
      name: node.text,
      description: node.text,
      order: parseInt(node.id.replace('step', '')) || node.level
    };
    
    // 如果有子节点，转换为substeps
    if (node.children.length > 0) {
      step.substeps = {};
      node.children.forEach((childId, index) => {
        const childNode = nodes.find(n => n.id === childId);
        if (childNode) {
          const childStep = convertNode(childNode);
          step.substeps![childId] = childStep;
        }
      });
    }
    
    return step;
  };

  // 找到中心节点（level 0）
  const centerNode = nodes.find(n => n.level === 0);
  if (centerNode && centerNode.children.length > 0) {
    // 转换中心节点的所有子节点（主步骤）
    centerNode.children.forEach((childId, index) => {
      const childNode = nodes.find(n => n.id === childId);
      if (childNode) {
        const step = convertNode(childNode);
        steps[childId] = step;
      }
    });
  } else {
    // 如果没有中心节点，查找所有level=1的节点作为主步骤
    const mainSteps = nodes.filter(n => n.level === 1);
    mainSteps.forEach((node, index) => {
      const step = convertNode(node);
      steps[node.id] = step;
    });
  }

  return steps;
};

// 将工作流步骤（嵌套对象格式）转换为思维导图节点
const convertStepsToNodes = (steps: { [key: string]: WorkflowStep }, workflowName: string): MindMapNode[] => {
  if (Object.keys(steps).length === 0) {
    // 创建默认根节点
    return [{
      id: 'root',
      x: 50,
      y: 200,
      width: 200,
      height: 80,
      text: workflowName || '我的工作流',
      level: 0,
      children: [],
      color: '#1e40af'
    }];
  }

  const nodes: MindMapNode[] = [];
  // 现代化配色方案
  const colors = [
    '#4f46e5', // 靛蓝色
    '#06b6d4', // 青色
    '#10b981', // 绿色
    '#f59e0b', // 琥珀色
    '#ef4444', // 红色
    '#8b5cf6', // 紫色
    '#ec4899'  // 粉色
  ];

  // 首先创建根节点（工作流名称）
  const rootNode: MindMapNode = {
    id: 'root',
    x: 50,
    y: 300, // 调整根节点Y位置与主步骤对齐
    width: 200,
    height: 80,
    text: workflowName || '工作流',
    level: 0,
    children: Object.keys(steps),
    color: '#1e40af'
  };
  nodes.push(rootNode);

  // 预先计算所有节点的位置和大小
  const calculateNodeLayout = (steps: { [key: string]: WorkflowStep }) => {
    const nodeLayouts: Array<{
      id: string;
      level: number;
      parentId?: string;
      x: number;
      y: number;
      width: number;
      height: number;
    }> = [];

    // 第一步：计算第一级节点（主步骤）
    const rootStepIds = Object.keys(steps).sort((a, b) => steps[a].order - steps[b].order);
    const level1Spacing = 200; // 增加主步骤间距到200px
    const level1StartY = 300 - (rootStepIds.length - 1) * level1Spacing / 2;

    rootStepIds.forEach((stepId, index) => {
      const step = steps[stepId];
      nodeLayouts.push({
        id: stepId,
        level: 1,
        parentId: 'root',
        x: 320,
        y: level1StartY + index * level1Spacing,
        width: 200,
        height: 80
      });
    });

    // 第二步：计算第二级节点（子步骤）
    rootStepIds.forEach((stepId) => {
      const step = steps[stepId];
      if (step.substeps) {
        const parentLayout = nodeLayouts.find(n => n.id === stepId)!;
        const substepIds = Object.keys(step.substeps).sort((a, b) => 
          step.substeps![a].order - step.substeps![b].order
        );
        
        const level2Spacing = 120; // 增加子步骤间距
        const level2StartY = parentLayout.y - (substepIds.length - 1) * level2Spacing / 2;

        substepIds.forEach((substepId, index) => {
          nodeLayouts.push({
            id: substepId,
            level: 2,
            parentId: stepId,
            x: 580,
            y: level2StartY + index * level2Spacing,
            width: 180,
            height: 70
          });
        });

        // 第三步：计算第三级节点（子子步骤）
        substepIds.forEach((substepId) => {
          const substep = step.substeps![substepId];
          if (substep.substeps) {
            const substepLayout = nodeLayouts.find(n => n.id === substepId)!;
            const subsubstepIds = Object.keys(substep.substeps).sort((a, b) => 
              substep.substeps![a].order - substep.substeps![b].order
            );
            
            const level3Spacing = 100; // 增加第三级间距
            const level3StartY = substepLayout.y - (subsubstepIds.length - 1) * level3Spacing / 2;

            subsubstepIds.forEach((subsubstepId, subIndex) => {
              nodeLayouts.push({
                id: subsubstepId,
                level: 3,
                parentId: substepId,
                x: 840,
                y: level3StartY + subIndex * level3Spacing,
                width: 160,
                height: 60
              });
            });
          }
        });
      }
    });

    return nodeLayouts;
  };

  const nodeLayouts = calculateNodeLayout(steps);

  // 递归转换步骤，使用预计算的位置
  const convertStep = (stepId: string, step: WorkflowStep, level: number, parentId?: string) => {
    const layout = nodeLayouts.find(n => n.id === stepId);
    if (!layout) return;

    const node: MindMapNode = {
      id: stepId,
      x: layout.x,
      y: layout.y,
      width: layout.width,
      height: layout.height,
      text: step.name,
      level,
      parentId,
      children: step.substeps ? Object.keys(step.substeps) : [],
      color: level === 1 ? '#2563eb' : colors[(level - 2) % colors.length]
    };
    
    nodes.push(node);
    
    // 转换子步骤
    if (step.substeps) {
      const substepIds = Object.keys(step.substeps).sort((a, b) => 
        step.substeps![a].order - step.substeps![b].order
      );
      
      substepIds.forEach((substepId) => {
        const substep = step.substeps![substepId];
        convertStep(substepId, substep, level + 1, stepId);
      });
    }
  };

  // 转换所有根步骤
  const rootStepIds = Object.keys(steps).sort((a, b) => steps[a].order - steps[b].order);
  rootStepIds.forEach((stepId) => {
    const step = steps[stepId];
    convertStep(stepId, step, 1, 'root');
  });

  // 计算自动缩放以适应所有节点
  const calculateAutoFit = () => {
    if (nodes.length === 0) return { scale: 1, panX: 0, panY: 0 };
    
    // 计算所有节点的边界
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    
    nodes.forEach(node => {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x + node.width);
      minY = Math.min(minY, node.y);
      maxY = Math.max(maxY, node.y + node.height);
    });
    
    // 添加边距
    const margin = 50;
    const contentWidth = maxX - minX + 2 * margin;
    const contentHeight = maxY - minY + 2 * margin;
    
    // 假设画布大小（会在渲染时更新）
    const canvasWidth = 1000;
    const canvasHeight = 600;
    
    // 计算缩放比例
    const scaleX = canvasWidth / contentWidth;
    const scaleY = canvasHeight / contentHeight;
    const scale = Math.min(scaleX, scaleY, 1); // 不要放大，只缩小
    
    // 计算居中偏移
    const scaledContentWidth = contentWidth * scale;
    const scaledContentHeight = contentHeight * scale;
    const panX = (canvasWidth - scaledContentWidth) / 2 - (minX - margin) * scale;
    const panY = (canvasHeight - scaledContentHeight) / 2 - (minY - margin) * scale;
    
    return { scale, panX, panY };
  };

  // 为节点添加自动适应信息
  (nodes as any).autoFit = calculateAutoFit();

  return nodes;
};

interface WorkflowConfigProps {}

const WorkflowConfig: React.FC<WorkflowConfigProps> = () => {
  const { state, dispatch } = useSystem();
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<WorkflowTemplate | null>(null);
  const [searchText, setSearchText] = useState<string>('');
  const [editingNodes, setEditingNodes] = useState<MindMapNode[]>([]);
  const [jsonModalVisible, setJsonModalVisible] = useState(false);
  const [currentWorkflowJSON, setCurrentWorkflowJSON] = useState<string>('');
  const [canvasKey, setCanvasKey] = useState<number>(0); // 用于强制重新渲染画板

  // 添加新工作流
  const handleAddWorkflow = async () => {
    try {
      const steps = convertNodesToSteps(editingNodes);
      const rootNode = editingNodes.find(n => n.level === 0);
      const workflowName = rootNode?.text || '未命名工作流';
      
      const newWorkflow: WorkflowTemplate = {
        id: Date.now().toString(),
        name: workflowName,
        description: workflowName,
        category: 'custom',
        tags: [],
        steps,
        enabled: true,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      
      dispatch({ type: 'ADD_WORKFLOW_TEMPLATE', payload: newWorkflow });
      form.resetFields();
      setEditingNodes([]);
      setIsModalVisible(false);
      setCanvasKey(prev => prev + 1); // 强制重新渲染
      message.success('工作流模板创建成功！');
    } catch (error) {
      message.error('创建工作流模板失败');
    }
  };

  // 编辑工作流
  const handleEditWorkflow = async () => {
    if (!editingWorkflow) return;
    
    try {
      const steps = convertNodesToSteps(editingNodes);
      const rootNode = editingNodes.find(n => n.level === 0);
      const workflowName = rootNode?.text || '未命名工作流';
      
      dispatch({
        type: 'UPDATE_WORKFLOW_TEMPLATE',
        payload: {
          id: editingWorkflow.id,
          updates: {
            name: workflowName,
            description: workflowName,
            steps,
            updatedAt: new Date().toISOString(),
          }
        }
      });
      
      editForm.resetFields();
      setEditingNodes([]);
      setEditModalVisible(false);
      setEditingWorkflow(null);
      setCanvasKey(prev => prev + 1); // 强制重新渲染
      message.success('工作流模板更新成功！');
    } catch (error) {
      message.error('更新工作流模板失败');
    }
  };

  // 启用/禁用工作流
  const handleToggleWorkflow = (workflow: WorkflowTemplate) => {
    dispatch({
      type: 'UPDATE_WORKFLOW_TEMPLATE',
      payload: {
        id: workflow.id,
        updates: { enabled: !workflow.enabled }
      }
    });
    message.success(workflow.enabled ? '工作流已禁用' : '工作流已启用');
  };

  // 删除工作流
  const handleDeleteWorkflow = (workflowId: string) => {
    dispatch({ type: 'DELETE_WORKFLOW_TEMPLATE', payload: workflowId });
    message.success('工作流模板删除成功');
  };

  // 复制工作流
  const handleCopyWorkflow = (workflow: WorkflowTemplate) => {
    const newWorkflow: WorkflowTemplate = {
      ...workflow,
      id: Date.now().toString(),
      name: `${workflow.name} - 副本`,
      description: `${workflow.description} - 副本`,
      enabled: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    dispatch({ type: 'ADD_WORKFLOW_TEMPLATE', payload: newWorkflow });
    message.success('工作流模板复制成功');
  };

  // 显示工作流JSON
  const showWorkflowJSON = (workflow: WorkflowTemplate) => {
    setCurrentWorkflowJSON(JSON.stringify(workflow, null, 2));
    setJsonModalVisible(true);
  };

  // 打开编辑模态框
  const openEditModal = (workflow: WorkflowTemplate) => {
    setEditingWorkflow(workflow);
    
    // 转换工作流步骤为思维导图节点
    const nodes = convertStepsToNodes(workflow.steps, workflow.name);
    setEditingNodes(nodes);
    setCanvasKey(prev => prev + 1); // 强制重新渲染画板
    
    editForm.setFieldsValue({
      name: workflow.name,
      description: workflow.description
    });
    
    setEditModalVisible(true);
  };

  // 打开创建模态框
  const openCreateModal = () => {
    // 创建默认节点
    const defaultNodes: MindMapNode[] = [{
      id: 'root',
      x: 50,
      y: 200,
      width: 200,
      height: 80,
      text: '我的工作流',
      level: 0,
      children: [],
      color: '#667eea'
    }];
    
    setEditingNodes(defaultNodes);
    setCanvasKey(prev => prev + 1); // 强制重新渲染画板
    setIsModalVisible(true);
  };

  // 过滤工作流
  const filteredWorkflows = state.workflowTemplates.filter(workflow =>
    workflow.name.toLowerCase().includes(searchText.toLowerCase()) ||
    workflow.description.toLowerCase().includes(searchText.toLowerCase())
  );



  // 计算总步骤数
  const getTotalSteps = (steps: { [key: string]: WorkflowStep }): number => {
    let totalSteps = 0;
    
    const countSteps = (stepObj: { [key: string]: WorkflowStep }) => {
      Object.values(stepObj).forEach(step => {
        totalSteps++;
        if (step.substeps) {
          countSteps(step.substeps);
        }
      });
    };
    
    countSteps(steps);
    return totalSteps;
  };

  return (
    <div style={{ padding: '24px 0' }}>
      {/* 头部 */}
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: 24 
      }}>
        <div>
          <Title level={4} style={{ margin: 0, color: '#1890ff' }}>
            <BranchesOutlined style={{ marginRight: 8 }} />
            工作流配置
          </Title>
          <Text type="secondary" style={{ fontSize: 14 }}>
            创建和管理您的AI工作流程，让AI按照您的思路工作
          </Text>
        </div>
        <Space size="middle">
          <Input.Search
            placeholder="搜索工作流..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 300 }}
            allowClear
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={openCreateModal}
            size="large"
            style={{
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              border: 'none',
              boxShadow: '0 4px 12px rgba(102, 126, 234, 0.3)'
            }}
          >
            创建工作流
          </Button>
        </Space>
      </div>

      {/* 说明部分 */}
      <Alert
        message="工作流配置说明"
        description="工作流配置是您对AI助手执行任务的结构化指导，包括具体步骤、执行顺序、注意事项等。启用的工作流会在合适的场景下自动应用。"
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        style={{ 
          marginBottom: 24,
          borderRadius: '12px',
          border: '1px solid #e6f7ff',
          background: 'linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%)'
        }}
      />

      {/* 工作流列表 */}
      <div style={{ 
        background: '#fff',
        borderRadius: '16px',
        border: '1px solid #f0f0f0',
        overflow: 'hidden'
      }}>
        {filteredWorkflows.length === 0 ? (
          <div style={{ 
            textAlign: 'center', 
            padding: '60px 0', 
            background: 'linear-gradient(135deg, #fafbfc 0%, #f5f7fa 100%)',
            borderRadius: '16px',
            border: '1px dashed #d9d9d9'
          }}>
            <BranchesOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
            <div style={{ fontSize: 16, color: '#666', marginBottom: 8 }}>暂无工作流模板</div>
            <div style={{ fontSize: 14, color: '#999' }}>
              点击"创建工作流"开始配置您的任务流程
            </div>
          </div>
        ) : (
          <List
            dataSource={filteredWorkflows}
            renderItem={(workflow, index) => {
              const totalSteps = getTotalSteps(workflow.steps);
              
              return (
                <List.Item
                  key={workflow.id}
                  style={{
                    padding: '20px 24px',
                    borderBottom: index === filteredWorkflows.length - 1 ? 'none' : '1px solid #f5f5f5',
                    background: workflow.enabled ? '#fff' : '#fafafa',
                    transition: 'all 0.3s ease'
                  }}
                  actions={[
                    <Tooltip title={workflow.enabled ? '禁用' : '启用'}>
                      <Switch
                        checked={workflow.enabled}
                        onChange={() => handleToggleWorkflow(workflow)}
                        style={{
                          background: workflow.enabled ? '#52c41a' : '#d9d9d9'
                        }}
                      />
                    </Tooltip>,
                    <Tooltip title="编辑">
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => openEditModal(workflow)}
                        style={{
                          color: '#1890ff',
                          borderRadius: '6px'
                        }}
                      />
                    </Tooltip>,
                    <Tooltip title="复制">
                      <Button
                        type="text"
                        icon={<CopyOutlined />}
                        onClick={() => handleCopyWorkflow(workflow)}
                        style={{
                          color: '#1890ff',
                          borderRadius: '6px'
                        }}
                      />
                    </Tooltip>,
                    <Tooltip title="详情">
                      <Button
                        type="text"
                        icon={<InfoCircleOutlined />}
                        onClick={() => showWorkflowJSON(workflow)}
                        style={{
                          color: '#1890ff',
                          borderRadius: '6px'
                        }}
                      />
                    </Tooltip>,
                    <Popconfirm
                      title="确认删除"
                      description="确定要删除这个工作流吗？"
                      onConfirm={() => handleDeleteWorkflow(workflow.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Tooltip title="删除">
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          style={{
                            borderRadius: '6px'
                          }}
                        />
                      </Tooltip>
                    </Popconfirm>
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Text strong style={{ 
                          color: workflow.enabled ? '#1890ff' : '#999',
                          fontSize: 16
                        }}>
                          {workflow.name}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          (共 {totalSteps} 个步骤)
                        </Text>
                        {!workflow.enabled && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            (已禁用)
                          </Text>
                        )}
                      </Space>
                    }
                    description={
                      <Text 
                        type="secondary" 
                        style={{ 
                          display: 'block',
                          maxWidth: '600px',
                          whiteSpace: 'pre-wrap',
                          opacity: workflow.enabled ? 1 : 0.6,
                          lineHeight: 1.6,
                          marginTop: 8
                        }}
                      >
                        {workflow.description.length > 100 
                          ? `${workflow.description.substring(0, 100)}...` 
                          : workflow.description
                        }
                      </Text>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </div>

      {/* 创建工作流模态框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <PlusOutlined style={{ marginRight: '8px', color: '#667eea' }} />
            创建新工作流
          </div>
        }
        open={isModalVisible}
        onCancel={() => {
          setIsModalVisible(false);
          setEditingNodes([]);
          setCanvasKey(prev => prev + 1);
        }}
        footer={[
          <Button key="cancel" onClick={() => {
            setIsModalVisible(false);
            setEditingNodes([]);
            setCanvasKey(prev => prev + 1);
          }}>
            取消
          </Button>,
          <Button key="submit" type="primary" onClick={handleAddWorkflow}>
            创建工作流
          </Button>
        ]}
        width={1200}
        style={{ top: 20 }}
        destroyOnClose
      >
        <div style={{ marginBottom: '16px' }}>
          <Alert
            message="使用思维导图设计您的工作流"
            description="双击节点编辑文本，选中节点后按Tab键添加子步骤，Delete键删除节点"
            type="info"
            showIcon
            style={{ marginBottom: '16px' }}
          />
        </div>
        
        <MindMapCanvas
          key={`create-${canvasKey}`}
          nodes={editingNodes}
          onNodesChange={setEditingNodes}
        />
      </Modal>

      {/* 编辑工作流模态框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <EditOutlined style={{ marginRight: '8px', color: '#667eea' }} />
            编辑工作流: {editingWorkflow?.name}
          </div>
        }
        open={editModalVisible}
        onCancel={() => {
          setEditModalVisible(false);
          setEditingWorkflow(null);
          setEditingNodes([]);
          setCanvasKey(prev => prev + 1);
        }}
        footer={[
          <Button key="cancel" onClick={() => {
            setEditModalVisible(false);
            setEditingWorkflow(null);
            setEditingNodes([]);
            setCanvasKey(prev => prev + 1);
          }}>
            取消
          </Button>,
          <Button key="submit" type="primary" onClick={handleEditWorkflow}>
            更新工作流
          </Button>
        ]}
        width={1200}
        style={{ top: 20 }}
        destroyOnClose
      >
        <div style={{ marginBottom: '16px' }}>
          <Alert
            message="编辑您的工作流结构"
            description="双击节点编辑文本，选中节点后按Tab键添加子步骤，Delete键删除节点"
            type="info"
            showIcon
            style={{ marginBottom: '16px' }}
          />
        </div>
        
        <MindMapCanvas
          key={`edit-${canvasKey}`}
          nodes={editingNodes}
          onNodesChange={setEditingNodes}
        />
      </Modal>

      {/* JSON详情模态框 */}
      <Modal
        title="工作流详情"
        open={jsonModalVisible}
        onCancel={() => setJsonModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setJsonModalVisible(false)}>
            关闭
          </Button>
        ]}
        width={800}
      >
        <pre style={{ 
          background: '#f5f5f5', 
          padding: '16px', 
          borderRadius: '8px',
          maxHeight: '500px',
          overflow: 'auto',
          fontSize: '12px'
        }}>
          {currentWorkflowJSON}
        </pre>
      </Modal>
    </div>
  );
};

export default WorkflowConfig; 