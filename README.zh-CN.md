# Schema Data Forge

[English](./README.md) | **简体中文**

桌面编辑器：根据 JSON Schema 和 XML Schema 生成 JSON/XML 样例数据，并强制做模式校验。AI 生成是可选的。

## 0.2.0 更新

可以从内置的 Palantir 示例模式打出启动包，**不必调用大模型**：

```bash
python -m schema_data_forge.cli --pack ./starter-pack
```

输出目录里包含模式文件、已校验的 JSON/XML 样例，以及记录校验结果的 `manifest.json`。

## 功能
- JSON Schema → 样例数据
- XML Schema → 样例数据
- 可选的 AI 辅助生成
- 强制模式校验
- 离线启动包（`--pack`）
- 桌面应用

## 验证

```bash
pytest tests -k "not e2e"
```
