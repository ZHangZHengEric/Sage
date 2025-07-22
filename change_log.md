# Sage 项目变更日志

## 2024-12-19

### sagents工具Excel解析器合并单元格支持
- **修改时间**: 2024-12-19
- **作者**: Eric ZZ
- **修改内容**: 同步修复sagents工具中Excel解析器的合并单元格处理问题，确保与mcp_servers保持一致
- **影响文件**: `sagents/tool/file_parser_tool.py`
- **技术细节**: 应用相同的合并单元格处理逻辑，关闭read_only模式并创建合并单元格值映射

### Excel解析器合并单元格支持
- **修改时间**: 2024-12-19
- **作者**: Eric ZZ
- **修改内容**: 修复Excel解析器中合并单元格处理问题，现在合并单元格的值会正确填充到所有被合并的单元格中
- **影响文件**: `mcp_servers/file_parser/file_parser.py`
- **技术细节**: 将read_only模式改为False以访问合并单元格信息，创建合并单元格值映射确保所有合并区域显示相同值