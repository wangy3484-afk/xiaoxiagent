# 身份认证与资源授权

本系统首版使用本地账号与服务端会话，只为运营方案生成与读取提供身份边界。它不实现企业组织、角色分级或单点登录，也不把浏览器 Cookie 当作业务授权依据：所有业务资源仍必须在数据库查询中按当前用户的 `owner_id` 过滤。

## 安全模型

- 密码使用 `pwdlib` 推荐的 Argon2 参数哈希，数据库不保存明文密码；登录时未知邮箱与错误密码返回完全相同的错误。
- 登录成功后生成高熵随机会话令牌。浏览器只持有原始令牌，数据库只保存使用服务端密钥计算的 HMAC-SHA256 摘要。
- 会话具有服务端过期时间且可撤销。退出会撤销数据库会话并删除浏览器 Cookie。
- Cookie 固定使用 `HttpOnly` 和 `Path=/`，`Secure`、`SameSite=Lax|Strict` 由配置控制；生产环境强制启用 `Secure`。
- brief、job、evidence、report 和 export 查询都使用 `AuthorizationSubject.user_id` 加入所有者条件。无权限资源与不存在资源统一返回 `404 RESOURCE_NOT_FOUND`，不披露资源是否存在。
- 创建类请求使用 `Idempotency-Key`；记录按“用户 + 接口作用域 + 键”隔离，并绑定规范化请求体摘要。

首版浏览器部署边界是同源 Web/API。`SameSite` 是纵深防护，不应被视为完整 CSRF 方案；如果以后允许跨站前端或第三方客户端携带 Cookie，必须在开放前增加显式 Origin 校验及 CSRF Token 机制。TLS 终止、可信 Host 和跨域白名单将在生产反向代理任务中完成。

## 本地账号 API

以下示例假设 API 位于 `https://example.com`。本地 HTTP 开发环境需要将 `OPS_AGENT_SESSION_COOKIE_SECURE=false`；生产环境不得关闭该配置。密码长度为 12–1024 个字符。

### 创建账号

<!-- CONTRACT: POST /api/v1/auth/register -->

```bash
curl --fail-with-body \
  -X POST https://example.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"correct-horse-battery-staple"}'
```

成功返回 `201` 和不含密码字段的用户对象。邮箱已注册时返回 `409 EMAIL_ALREADY_REGISTERED`。

### 登录并保存会话 Cookie

<!-- CONTRACT: POST /api/v1/auth/login -->

```bash
curl --fail-with-body \
  -c cookies.txt \
  -X POST https://example.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"correct-horse-battery-staple"}'
```

成功返回 `200`，并通过 `Set-Cookie` 建立服务端会话。未知邮箱和错误密码都返回 `401 INVALID_CREDENTIALS`。

### 恢复当前会话

<!-- CONTRACT: GET /api/v1/auth/me -->

```bash
curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/auth/me
```

缺少、过期或已撤销的会话返回 `401 AUTHENTICATION_REQUIRED`。

### 退出

<!-- CONTRACT: POST /api/v1/auth/logout -->

```bash
curl --fail-with-body \
  -b cookies.txt \
  -c cookies.txt \
  -X POST https://example.com/api/v1/auth/logout
```

退出是幂等操作，成功返回 `204`。即使 Cookie 缺失或已失效，也会返回 `204` 并下发删除 Cookie 的响应头。

## 受保护资源示例

所有请求都必须携带登录 Cookie。当前元数据读取契约如下；跨用户访问与不存在 ID 的响应完全相同。

<!-- CONTRACT: GET /api/v1/briefs/{brief_id} -->
<!-- CONTRACT: GET /api/v1/jobs/{job_id} -->
<!-- CONTRACT: GET /api/v1/evidence/{evidence_id} -->
<!-- CONTRACT: GET /api/v1/reports/{report_id} -->
<!-- CONTRACT: GET /api/v1/exports/{export_id} -->
<!-- CONTRACT: POST /api/v1/reports/{report_version_id}/exports -->
<!-- CONTRACT: GET /api/v1/exports/{export_id}/download -->

```bash
curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/briefs/BRIEF_ID

curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/jobs/JOB_ID

curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/evidence/EVIDENCE_ID

curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/reports/REPORT_VERSION_ID

curl --fail-with-body \
  -b cookies.txt \
  https://example.com/api/v1/exports/EXPORT_ID
```

创建和下载导出文件同样执行所有者校验。创建接口要求幂等键；下载时服务端会重新校验文件大小和 SHA-256，过期临时文件返回与不存在文件一致的 `404 RESOURCE_NOT_FOUND`。

```bash
curl --fail-with-body \
  -b cookies.txt \
  -X POST https://example.com/api/v1/reports/REPORT_VERSION_ID/exports \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: export-report-001" \
  -d '{"format":"pdf","temporary":false}'

curl --fail-with-body \
  -b cookies.txt \
  --output operations-report.pdf \
  https://example.com/api/v1/exports/EXPORT_ID/download
```

创建简报还必须发送幂等键：

<!-- CONTRACT: POST /api/v1/briefs -->

```bash
curl --fail-with-body \
  -b cookies.txt \
  -X POST https://example.com/api/v1/briefs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: brief-create-001" \
  -d '{"brief_payload":{"operation_goal":"提高留存"},"classification_payload":{"primary_scene":"retention"}}'
```

相同键和相同请求体会重放首次 `201` 响应并返回 `Idempotency-Replayed: true`；相同键但不同请求体返回 `409 IDEMPOTENCY_CONFLICT`。

## OIDC/企业 SSO 替换点

本地账号实现被限制在 `ops_agent.auth.service.AuthService` 与 `/api/v1/auth/*` 路由中。业务 API 只依赖 `get_current_user` 产生的 `UserRecord`，以及从它派生的 `AuthorizationSubject`，不会读取密码或解析具体认证协议。

未来接入 OIDC 时应：

1. 新增身份提供方适配器，校验授权码、issuer、audience、nonce 和签名，并把稳定的 `issuer + subject` 映射到本地 `UserRecord`。
2. 用 OIDC 登录/回调替换本地注册和密码登录入口；服务端会话、当前用户依赖与业务仓储授权接口保持不变。
3. 迁移期间以独立身份映射表关联外部主体，不把邮箱当作永久 OIDC 主键，也不复用现有 `password_hash` 字段存放外部令牌。
4. 外部 access/refresh token 若确需保存，使用独立加密存储和最小权限策略；不得写入当前会话 Cookie、日志或业务报告。

这样可以更换身份来源，而不改变 brief、job、evidence、report 与 export 的资源隔离语义。
