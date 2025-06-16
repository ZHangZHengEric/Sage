# 📁 高级文件解析器 (Advanced File Parser)

> 功能强大的 MCP 文件解析服务器，支持多种文件格式的智能解析和文本提取

## 🚀 功能特点

- 📄 **多格式支持**: 支持20+种文件格式
- 🔍 **智能验证**: 文件格式、大小、权限自动验证
- 🌐 **网页解析**: 支持URL和HTML文件解析
- 📊 **批量处理**: 支持多文件批量解析
- ⚡ **高性能**: 优化的解析算法和错误处理
- 🛠️ **模块化**: 清晰的代码架构和扩展性

## 📋 支持的文件格式

### 📄 文档格式
- **PDF**: `.pdf` - 使用 pdfplumber 进行精确文本提取
- **Word**: `.docx`, `.doc` - 支持新旧格式Word文档
- **RTF**: `.rtf` - 富文本格式
- **OpenDocument**: `.odt` - 开放文档格式
- **LaTeX**: `.tex`, `.latex` - 学术文档格式

### 📊 表格格式  
- **Excel**: `.xlsx`, `.xls` - 转换为Markdown表格格式
- **CSV**: `.csv` - 逗号分隔值文件

### 🎯 演示文稿
- **PowerPoint**: `.pptx`, `.ppt` - 支持新旧格式PPT

### 🌐 网页格式
- **HTML**: `.html`, `.htm` - 网页文件
- **XML**: `.xml` - 结构化标记语言

### 📝 纯文本格式
- **文本**: `.txt` - 纯文本文件
- **Markdown**: `.md`, `.markdown` - 标记语言
- **JSON**: `.json` - 数据交换格式

### 📚 电子书
- **EPUB**: `.epub` - 电子出版物格式

## 🛠️ 核心功能

### 1. 📄 文件文本提取

#### `extract_text_from_file()`
高级文件文本提取工具

```python
result = await extract_text_from_file(
    input_file_path="document.pdf",
    start_index=0,
    max_length=5000,
    include_metadata=True
)
```

**参数说明**：
- `input_file_path` (str): 文件路径
- `start_index` (int): 文本开始位置，默认0
- `max_length` (int): 最大提取长度，默认5000
- `include_metadata` (bool): 是否包含元数据，默认False

**返回信息**：
```json
{
    "status": "success",
    "message": "成功解析 .pdf 文件",
    "text": "提取的文本内容...",
    "length": 1234,
    "total_length": 5678,
    "file_info": {
        "file_path": "/path/to/file.pdf",
        "file_extension": ".pdf",
        "file_size_mb": 2.5,
        "mime_type": "application/pdf"
    },
    "text_stats": {
        "characters": 5678,
        "words": 950,
        "lines": 120,
        "paragraphs": 25
    },
    "extraction_info": {
        "start_index": 0,
        "max_length": 5000,
        "processing_time": 0.85
    },
    "metadata": {
        "pages": 10,
        "metadata": {...}
    }
}
```

### 2. 🌐 URL文本提取

#### `extract_text_from_url()`
从网页URL提取文本内容

```python
result = await extract_text_from_url(
    url="https://example.com",
    start_index=0,
    max_length=5000,
    timeout=30
)
```

**特点**：
- 自动处理网页编码
- 智能HTML转文本
- 超时保护机制
- User-Agent伪装

### 3. 📊 批量处理

#### `batch_extract_text()`
批量处理多个文件

```python
result = await batch_extract_text(
    file_paths=["file1.pdf", "file2.docx", "file3.txt"],
    max_length=3000,
    include_metadata=False
)
```

**返回批量处理结果**：
```json
{
    "status": "success",
    "message": "批量处理完成，成功2个，失败1个",
    "summary": {
        "total_files": 3,
        "successful": 2,
        "failed": 1,
        "processing_time": 2.34
    },
    "results": [...]
}
```

### 4. 🔍 文件验证

#### `validate_file_format()`
验证文件格式和可读性

```python
result = await validate_file_format(file_path="document.pdf")
```

**验证项目**：
- 文件存在性
- 格式支持性
- 文件大小限制
- 读取权限
- MIME类型检测

### 5. 📋 格式查询

#### `get_supported_formats()`
获取支持的文件格式列表

```python
result = await get_supported_formats()
```

**返回格式分类**：
- 按类别分组的格式列表
- 文件大小限制信息
- MIME类型映射

## 🏗️ 架构设计

### 核心类结构

#### 🔍 FileValidator
**文件验证器**
- 格式支持检查
- 文件大小验证
- 权限验证
- MIME类型检测

#### 📝 TextProcessor
**文本处理器**
- 编码自动检测
- 文本清理和格式化
- 安全截取
- 统计信息计算

#### 📄 PDFParser
**PDF解析器**
- 逐页文本提取
- 元数据获取
- 错误页面处理
- 结构化输出

#### 🏢 OfficeParser
**Office文档解析器**
- DOCX/DOC文档处理
- PPTX/PPT演示文稿处理
- 格式转换和清理

#### 📊 ExcelParser
**Excel解析器**
- 多工作表处理
- Markdown表格转换
- 空行列清理
- 数据类型处理

#### 🌐 WebParser
**网页解析器**
- HTML文件处理
- URL内容抓取
- 编码处理
- 链接和图片处理

#### 📝 PlainTextParser
**纯文本解析器**
- 编码自动检测
- Pandoc集成
- 多格式统一处理

## 📊 性能指标

### 处理能力
- **响应时间**: < 1秒 (小文件 < 1MB)
- **吞吐量**: 100+ 文件/分钟 (批量处理)
- **内存使用**: < 100MB (常规操作)
- **并发支持**: 50+ 并发请求

### 文件大小限制
```json
{
    ".pdf": "50MB",
    ".docx": "25MB", 
    ".doc": "25MB",
    ".pptx": "100MB",
    ".ppt": "100MB",
    ".xlsx": "25MB",
    ".xls": "25MB",
    ".txt": "10MB",
    ".csv": "50MB",
    ".json": "10MB",
    ".xml": "10MB",
    ".html": "5MB",
    ".htm": "5MB",
    ".md": "5MB",
    ".markdown": "5MB"
}
```

## 🛠️ 安装和配置

### 环境要求

```bash
# 基础依赖
pip install mcp starlette uvicorn

# 文件解析依赖
pip install pypandoc pdfplumber python-pptx openpyxl
pip install html2text requests chardet

# Office文档支持 (可选)
pip install aspose.slides
```

### 系统依赖

```bash
# Ubuntu/Debian
sudo apt-get install pandoc antiword

# macOS
brew install pandoc antiword

# Windows
# 请从官网下载安装 pandoc 和 antiword
```

### 启动服务器

```bash
cd mcp_servers/file_parser
python file_parser.py
```

服务器将在 `http://0.0.0.0:34001` 启动。

### MCP 客户端配置

在 `mcp_setting.json` 中添加：

```json
{
  "mcpServers": {
    "file_parser": {
      "sse_url": "http://127.0.0.1:34001/sse",
      "disabled": false
    }
  }
}
```

## 🧪 运行测试

执行完整的测试套件：

```bash
cd mcp_servers/file_parser
python test_file_parser.py
```

**测试覆盖**：
- ✅ 基础文件解析 (5种格式)
- ✅ 高级功能 (元数据、截取、批量)
- ✅ 网络功能 (URL解析)
- ✅ 验证功能 (格式验证、支持查询)
- ✅ 错误处理 (异常情况)
- ✅ 性能测试 (大文件处理)

## 📝 使用示例

### 示例1：学术论文解析

```python
# 解析PDF学术论文
result = await extract_text_from_file(
    input_file_path="research_paper.pdf",
    max_length=10000,
    include_metadata=True
)

print(f"论文标题: {result['metadata']['metadata'].get('Title', '未知')}")
print(f"页数: {result['metadata']['pages']}")
print(f"字符数: {result['text_stats']['characters']}")
print(f"段落数: {result['text_stats']['paragraphs']}")
```

### 示例2：Excel数据分析报告

```python
# 解析Excel数据文件
result = await extract_text_from_file(
    input_file_path="data_report.xlsx",
    max_length=15000
)

# 结果以Markdown表格格式返回，便于进一步处理
markdown_tables = result['text']
print("Excel数据转换为Markdown:")
print(markdown_tables)
```

### 示例3：网页内容抓取

```python
# 抓取网页内容
result = await extract_text_from_url(
    url="https://example.com/article",
    max_length=8000,
    timeout=15
)

print(f"网页文本长度: {result['length']}")
print(f"处理时间: {result['extraction_info']['processing_time']}秒")
```

### 示例4：批量文档处理

```python
# 批量处理多个文档
files = [
    "contract1.pdf",
    "presentation.pptx", 
    "data.xlsx",
    "notes.md"
]

result = await batch_extract_text(
    file_paths=files,
    max_length=5000
)

print(f"处理结果: {result['summary']['successful']}/{result['summary']['total_files']} 成功")
for file_result in result['results']:
    file_path = file_result['file_path']
    status = file_result['result']['status']
    print(f"  {file_path}: {status}")
```

## 🎯 最佳实践

### 1. 性能优化

```python
# 大文件处理 - 使用较小的max_length
result = await extract_text_from_file(
    input_file_path="large_document.pdf",
    max_length=3000,  # 减少内存使用
    include_metadata=False  # 跳过元数据提取
)

# 批量处理 - 合理控制并发
batch_size = 10  # 每次处理10个文件
for i in range(0, len(all_files), batch_size):
    batch = all_files[i:i+batch_size]
    result = await batch_extract_text(batch)
```

### 2. 错误处理

```python
# 总是检查返回状态
result = await extract_text_from_file("document.pdf")
if result["status"] == "success":
    text = result["text"]
    # 处理成功提取的文本
else:
    error_msg = result["message"]
    # 处理错误情况
    print(f"解析失败: {error_msg}")
```

### 3. 格式选择

```python
# 检查文件格式支持
validation = await validate_file_format("unknown_file.xyz")
if validation["valid"]:
    # 文件格式支持，继续处理
    result = await extract_text_from_file("unknown_file.xyz")
else:
    print(f"不支持的格式: {validation['message']}")
```

### 4. 文本处理

```python
# 获取详细的文本统计
result = await extract_text_from_file(
    input_file_path="document.pdf",
    include_metadata=True
)

stats = result["text_stats"]
print(f"文档分析:")
print(f"  总字符数: {stats['characters']:,}")
print(f"  总词数: {stats['words']:,}")
print(f"  总行数: {stats['lines']:,}")
print(f"  段落数: {stats['paragraphs']:,}")
```

## 🔧 故障排除

### 常见问题

#### 1. PDF解析失败
```
错误: PDF解析失败: 文件已损坏
解决: 检查PDF文件完整性，尝试重新下载或转换格式
```

#### 2. DOC文件处理失败
```
错误: 未找到antiword工具
解决: 安装antiword - sudo apt-get install antiword
```

#### 3. 文件大小超限
```
错误: 文件过大: 60.0MB > 50MB
解决: 
- 压缩文件或分割处理
- 调整max_length参数减少内存使用
```

#### 4. 编码问题
```
错误: 文本文件解析失败: 编码错误
解决: 文件编码自动检测，通常自动处理
```

#### 5. URL访问失败
```
错误: URL访问失败: 连接超时
解决: 
- 检查网络连接
- 增加timeout参数
- 确认URL有效性
```

### 性能调优

#### 内存优化
- 使用较小的 `max_length` 参数
- 批量处理时控制并发数量
- 及时释放大文件的处理结果

#### 速度优化
- 预验证文件格式避免无效处理
- 使用批量处理接口
- 合理设置超时时间

## 🔮 未来规划

### v2.1.0 计划功能
- 📸 **图像OCR**: 支持图片文字识别
- 🗜️ **压缩文件**: 支持ZIP、RAR等压缩包
- 🔄 **格式转换**: 文件格式相互转换
- 📱 **移动格式**: 支持更多移动端文件格式

### v2.2.0 计划功能
- 🤖 **AI增强**: 智能内容摘要和分析
- ☁️ **云存储**: 支持云盘文件直接解析
- 📊 **可视化**: 集成图表和图像处理
- 🔐 **加密文档**: 支持加密文件解析

### v2.3.0 计划功能
- 🎵 **多媒体**: 音频视频字幕提取
- 🌍 **多语言**: 增强国际化支持
- 📈 **分析报告**: 文档质量和结构分析
- 🔧 **插件系统**: 自定义解析器扩展

---

**🎉 感谢使用高级文件解析器！欢迎反馈问题和建议。** 