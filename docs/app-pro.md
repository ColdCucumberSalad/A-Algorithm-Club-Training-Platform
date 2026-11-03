# RBC Helper Pro 卡密与 App API

## 当前 App：只输入卡密（取代前述 App 登录流程）

新增0054_card_device迁移。App使用 POST /api/app/cards/redeem，请求 {"code":"RBC-...","device_secret":"本机安全存储的64位十六进制随机秘密"}，返回与原登录相同的授权结构。无需账号密码；持有码即视为持有兑换凭证。此响应凭据仅表示本机卡密授权，不是网站或原账号API登录token。卡密首次核销记录设备秘密hash，同设备重试返回当前有效期不重复加时，其他设备不能再次核销。连续续期卡须来自同一购买账号，后端沿用该账号订阅及管理审计。App仅核销时联网，按服务端有效期本地判断；原24h租约不再限制卡密模式。管理员离线撤销无法即时生效。旧账号API保留兼容，不是新App必经步骤。

测试卡仅在本机数据库生成，不随源码或迁移交付生产。App正式包指向正式域名，接口及正式卡密必须在生产完成部署/发放后才能实际核销；不可把本地测试卡宣称可在正式包直接兑换。

以下账号登录接口保留兼容；当前App使用上面的卡密接口。


## 配置与迁移

运行 `python manage.py migrate`，新增迁移 `0053_app_pro_codes` 依赖 `0052_correct_empty_logic_scores`。迁移仅增加字段和表，不修改已有商品、库存、余额或用户权益，不依据商品名称或商品 ID 识别 Pro。

在原商城管理中，将新建或尚无购买记录的商品设置为“核销类（卡密）”，来源选“内部 Pro 卡密”，应用选“RBC Helper”，时长默认 31 天，允许 1–36500 天。管理员必须明确选择应用并保存。已有购买记录的商品不能换卡密来源，需要另一种来源时新增商品。库存仍由管理员手工设置：`0` 不可购买、`-1` 不限量；升级不自动补库存或配置任何真实商品。

购买时扣款、扣库存并创建单件履约，保存应用和时长快照。背包领取时原子生成高随机卡密，不访问 HTTP；原履约保存加密可回看的码，独立记录保存唯一 SHA-256 哈希、购买者、应用、时长和兑换时间。领取仅购买者可见，重复领取返回同一码。加密沿用现有 `SECRET_KEY` 派生能力，部署须保留原密钥。

领取不会开通权益。购买者使用同一网站全局账号登录 App，首次兑换按 `max(server_now, expires_at) + duration_days` 开通或延长，一天为连续 24 小时。重复兑换返回当前状态，不再次加时；管理员撤销后，重放已兑换卡密不会恢复权益。尚未兑换的其他卡密仍可正常使用。不同账号不能兑换或查询别人的卡密。后续修改商品时长或下架不影响已购买的快照。

## 认证与传输

- 固定服务产品标识 `rbc_helper`，客户端无需传商品 ID、应用 ID 或 API Key。
- 除登录外，下面的 App 接口只接受 `Authorization: Bearer <token>`，不接受 session、Cookie、查询参数或请求体中的 token。
- token 为独立随机值，数据库只保存哈希和密码状态摘要，默认有效 2592000 秒（30 天），由 `APP_TOKEN_TTL_SECONDS` 设置。退出撤销当前 token，管理员可撤销账号全部 App token。密码更改、禁用或注销账号使原 token 失效；网站退出不等同于 App 退出。
- `APP_REQUIRE_HTTPS=1` 为默认值，生产必须使用 HTTPS。仅本地 HTTP 联调可明确设置 `APP_REQUIRE_HTTPS=0`。代理应覆盖客户端提供的 `X-Forwarded-Proto`，后端不直接公开，沿用项目的 HTTPS 代理配置。
- `APP_TRUSTED_PROXY_CIDRS` 为逗号分隔的可信代理网段，默认仅 `127.0.0.0/8,::1/128`。仅直接连接的 peer 位于这些网段时才读取 Nginx 覆盖的单一 `X-Real-IP`，非法/缺失头回退为 peer；从不采信 `X-Forwarded-For`。Docker 部署必须填实际 Nginx 所在私有代理网段（可用 `docker network inspect <network>` 查看，不能照抄其他机器的网段），且后端 8000 端口不能公网直达。现有 `deploy/nginx.conf` 已覆盖 `X-Real-IP`。本地网络经核对为 `172.18.0.0/16`，本机 compose override 配置该网段，重建/重建容器后生效；此本地配置不纳入交付源码。
- 浏览器商城与管理继续使用原 session 和 CSRF 保护；App Bearer 不能授权管理接口，管理 session 不能授权 App 接口。登录不创建网站 session 或登录 Cookie。
- App 响应均带 `Cache-Control: private, no-store`。客户端应使用系统凭据存储保管 token，不将 token 或卡密写入日志。

## API 格式

所有请求体为 `Content-Type: application/json`，路径无结尾斜杠。时间均为带时区的 ISO 8601 字符串。`active` 按服务器时间判断，到期瞬间失效；未开通时 `expires_at` 为 `null`。

### POST /api/app/auth/login

请求：

```json
{"username":"网站全局登录账号","password":"网站密码"}
```

成功 HTTP 200：

```json
{
  "token": "仅此处返回的随机token",
  "token_expires_at": "2026-12-03T08:00:00+00:00",
  "user": {"id": 123, "username": "student"},
  "pro": {"active": false, "expires_at": null, "server_time": "2026-11-03T08:00:00+00:00"}
}
```

账号为全局登录用户名，不是团队展示名，不要求已加入团队。每账号 5 分钟最多 10 次登录尝试，每可信解析后的客户端地址最多 60 次，成功尝试也计数。不存在的用户名共用该客户端地址的桶，避免随机用户名逐个产生记录。已知账号的额度仍跨客户端共享，不能通过更换客户端地址绕开。部署需同时正确配置可信代理和代理侧限流。

### GET /api/app/pro

请求头：`Authorization: Bearer <token>`。成功 HTTP 200，直接返回 Pro 对象：

```json
{"active":true,"expires_at":"2026-12-04T08:00:00+00:00","server_time":"2026-11-03T08:00:00+00:00"}
```

### POST /api/app/pro/redeem

请求头同上，请求：

```json
{"code":"RBC-购买者背包领取的卡密"}
```

成功 HTTP 200：

```json
{"pro":{"active":true,"expires_at":"2026-12-04T08:00:00+00:00","server_time":"2026-11-03T08:00:00+00:00"}}
```

同一卡密重试幂等，无需另传请求编号；同账号不同卡密并发兑换串行累计。每账号 5 分钟最多 60 次兑换请求。累计日期超出可保存范围时返回 HTTP 400，权益、卡密兑换状态及审计均不变，管理员修正到期后可重试。

### POST /api/app/auth/logout

请求头同上，请求体 `{}`。成功 HTTP 200：`{"ok":true}`。后续使用此 token 返回 401；其他独立 token 不受影响。

### 错误

格式为 `{"error":"可显示给用户的错误说明"}`。HTTP 400：输入无效、无效或非本人卡密、日期溢出；401：登录失败、token 缺失/无效/过期/撤销或账号不可用；403：非 HTTPS；405：方法不支持；429：限流，带 `Retry-After`；503：系统备份恢复中。无效和非本人卡密返回相同错误，不披露归属或兑换信息。

## 管理与审计

原“全局账号管理”详情增加 Pro 分区，系统管理员可查看状态、待兑换卡密数量及最近 50 条审计，手动延长、设置到期、撤销 Pro 或全部 App 登录。表单时间按本地时区输入，提交时转换为带时区 ISO 8601。操作须填原因，管理响应不返回 token、完整卡密或哈希。

`GET /api/management/accounts/<user_id>/pro` 返回 `app/active/expires_at/server_time/revision/unredeemed_codes/audit`。`POST` 使用管理 session 和 CSRF：

```json
{
  "action": "extend",
  "days": 31,
  "reason": "人工补偿",
  "request_id": "b6cde232-7849-453b-aef4-1206bd73db35",
  "expected_revision": 0
}
```

`extend` 携带 `days`；`set_expiry` 携带带时区 `expires_at`；`revoke` 将到期设为现在；`revoke_tokens` 撤销全部 App token。UUID 请求编号在同一管理员、目标及完整请求下支持重试；更改请求复用编号或版本过期返回 409。权益修改与审计同事务，记录操作者、目标、动作、修改前后到期、原因及时间。停用/注销账号只读，管理员测试身份不能修改真实权益。

## 清理与验证

Celery Beat 每 60 秒运行 `club.tasks.cleanup_app_credentials`，每类每批最多 5000 条，清理窗口超过一天的限流记录及已过期/撤销超过 30 天的 token 哈希，不清理卡密凭证和 Pro 审计。上线需同步更新 Web、Worker、Beat。备份不包含 App token/限流桶，恢复也强制清除，防止恢复已撤销登录。

使用独立 PostgreSQL 测试数据库，不用 SQLite 替代并发验收，测试不修改真实商城数据：

```sh
python manage.py makemigrations --check --dry-run
python manage.py test club.test_app_pro club.test_shop_fulfillment club.test_global_accounts club.test_account_lifecycle club.test_admin_test_mode club.test_system_management --noinput
node --test tests/pro-management.test.cjs
```

后端测试覆盖真实 PostgreSQL 多连接并发领取、同卡重试、不同卡叠加，以及快照、隐私、权限、CSRF、token 生命周期、限流清理、日期溢出回滚和管理审计。前端测试覆盖表单无嵌套、审计转义、停用账号只读及条件输入切换。
