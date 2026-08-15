# Schema Data Forge

桌面版示例数据生成器：给定 **JSON Schema** 或 **XML Schema (XSD)**，调用 DeepSeek 以结构化输出生成示例数据，
并且**必须通过 schema 校验**才算成功——校验失败时把逐条校验错误回灌给模型自动修复，直到通过或达到最大尝试次数。

内置示例使用 Palantir Foundry 风格的本体模型（object type / link type / action type）XSD。

## 界面

- **左侧：AI 面板** — DeepSeek API Key、模型、Base URL、temperature、最大尝试次数；生成要求（追加到提示词）；
  生成按钮与生成/校验日志（每一次尝试的校验结果）。
- **右上：Schema 定义** — schema 类型、XSD 根元素、示例选择、打开文件；带语法高亮的编辑器。
- **右下：生成的数据 + 校验结果** — 可直接编辑并「重新校验」「格式化」「保存」；下方列出每条校验错误的位置、行号与信息，
  双击可跳到 XML 对应行。

## 运行

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

# 图形界面
DEEPSEEK_API_KEY=sk-... .venv/bin/python -m schema_data_forge.app

# 无界面（脚本 / CI 用）
DEEPSEEK_API_KEY=sk-... .venv/bin/python -m schema_data_forge.cli \
    --example palantir_ontology.xsd --out sample.xml
```

Windows PowerShell 下把 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`，
用 `$env:DEEPSEEK_API_KEY="sk-..."` 设置密钥。API Key 也可以直接填在左侧面板里（保存在本机 `QSettings`，不入库）。

## 工作原理

1. `generator.build_initial_messages` 把 schema、根元素、目标命名空间和用户额外要求组装成提示词，
   并要求模型用 JSON 信封返回（`{"data": ...}` 或 `{"xml": "..."}`），配合 DeepSeek 的 `response_format=json_object`
   保证结构化输出。
2. `validation.validate` 用 `jsonschema`（Draft 2020-12）或 `xmlschema` 校验，产出带位置/行号的错误列表。
3. 未通过时 `generator.build_repair_message` 把错误列表作为下一轮的修复指令，保留对话上下文继续修，
   直到通过（`GenerationResult.succeeded`）或用尽 `max_attempts`。未通过时 `document` 为 `None`，绝不返回未校验的数据。

## 示例 schema

| 文件 | 说明 |
| --- | --- |
| `src/schema_data_forge/example_schemas/palantir_ontology.xsd` | Palantir 本体模型：apiName 正则、dataset RID 正则、枚举、cardinality、`xs:key`/`xs:keyref`（link/action 必须引用已定义的对象类型）、属性 apiName 唯一性约束 |
| `src/schema_data_forge/example_schemas/palantir_object_set.schema.json` | 本体对象集合（Draft 2020-12）：`$defs`、`pattern`、`enum`、`uniqueItems`、`dependentRequired`、`additionalProperties: false` |

## 测试

```bash
.venv/bin/python -m pytest -m "not e2e"   # 单元测试：校验器 + 生成重试循环（无网络）
DEEPSEEK_API_KEY=sk-... .venv/bin/python -m pytest -m e2e   # 端到端：真实调用 DeepSeek
```

端到端测试断言 DeepSeek 生成的 XML/JSON 通过对应 schema 校验；没有设置 `DEEPSEEK_API_KEY` 时自动跳过。

## 代码检查

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
```
