# 报告模板与品牌配置

报告内容由 `OperationsReport` 决定，品牌配置只允许改变展示层的标题前缀、Logo 和页眉。它不得新增、删除或重排执行摘要、诊断、案例、策略、行动、指标、实验、资源、风险、假设、质量说明和证据附录，也不得改变证据编号。

## 部署配置

后端导出接口读取以下环境变量：

| 变量 | 用途 | 默认行为 |
| --- | --- | --- |
| `OPS_AGENT_REPORT_BRAND_TITLE` | 加在报告标题前的组织或产品名 | 仅显示报告原始标题 |
| `OPS_AGENT_REPORT_BRAND_HEADER` | PDF 页眉、HTML/Markdown 品牌头文字 | 使用报告标题 |
| `OPS_AGENT_REPORT_BRAND_LOGO_PATH` | 容器内 PNG/JPEG 文件绝对路径 | 不显示 Logo |

生产 Compose 可以把只读品牌目录挂载到 API 与 Worker 容器：

```yaml
services:
  api:
    environment:
      OPS_AGENT_REPORT_BRAND_TITLE: "示例公司运营中心"
      OPS_AGENT_REPORT_BRAND_HEADER: "内部运营决策支持报告"
      OPS_AGENT_REPORT_BRAND_LOGO_PATH: "/app/branding/logo.png"
    volumes:
      - ./branding:/app/branding:ro
```

Logo 必须是可读取的 PNG 或 JPEG。建议使用横向、透明背景图片，宽高比约 3:1，避免在 PDF 中使用过细文字。不要把密钥、用户信息或环境名称放入 Logo 文件名。

## 代码调用

需要离线渲染时，对三种格式传入同一个 `ReportBranding`：

```python
from pathlib import Path

from ops_agent.artifacts import (
    ReportBranding,
    render_operations_report_html,
    render_operations_report_markdown,
    render_operations_report_pdf,
)

branding = ReportBranding(
    title="示例公司运营中心",
    header_text="内部运营决策支持报告",
    logo_path=Path("branding/logo.png"),
    logo_alt="示例公司",
)

html = render_operations_report_html(report, branding=branding)
markdown = render_operations_report_markdown(report, branding=branding)
pdf = render_operations_report_pdf(report, branding=branding)
```

HTML 与 Markdown 会把 Logo 内嵌为 Data URI，PDF 会把图片嵌入文件。这样导出文件不依赖外部图片地址。品牌配置错误时，导出 API 返回稳定错误码 `REPORT_BRAND_CONFIGURATION_INVALID`，不会生成缺少品牌素材的半成品。

## 变更验收

每次调整品牌配置后应验证：

1. HTML、Markdown 和 PDF 的章节标题及顺序完全一致。
2. 表格数量、字段、证据编号与未配置品牌时一致。
3. Logo 没有拉伸、遮挡标题或进入页边距。
4. PDF 页眉页脚、长表格分页和链接仍然正常。
5. 决策支持、适用条件和验证责任说明没有被品牌文案覆盖。

品牌配置属于展示配置，不需要重新生成 Agent 报告版本；报告内容或证据发生变化时，仍必须创建新的不可变报告版本。
