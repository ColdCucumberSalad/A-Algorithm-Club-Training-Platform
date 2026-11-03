# RBC Helper 商品配置与卡密验证 API

## 商城配置

执行 `python manage.py migrate`，新增迁移为 `0053_app_pro_codes`、`0054_card_consumed`、`0055_card_activation_receipt`，依次依赖 `0052_correct_empty_logic_scores`。迁移只增加商品/履约字段、卡密及接口限流记录，不修改旧商品、价格、库存、余额或用户数据。

在商城管理中新增“核销类（卡密）”商品，来源选择“内部 Pro 卡密”，应用选择“RBC Helper”，订阅天数默认 31 天，可设 1–36500 天。库存由管理员设置：`0` 不可购买、`-1` 不限量。已有购买记录的商品不能更换卡密来源。

购买时保存应用和订阅天数快照；修改商品时长或下架不影响已购买商品。购买者从背包领取时生成卡密，重复领取返回同一码。商城履约状态 `redeemed` 在此表示“已领取卡密”，不表示 App 已激活或已消费卡密。卡密哈希单独保存，可回看的原码沿用商城加密存储，部署必须保留原加密密钥。

## 第一步：验证并占用卡密

### 请求

- 方法：`POST`
- 路径：`/api/app/cards/verify`（无结尾斜杠）
- 传输：HTTPS
- 请求头：`Content-Type: application/json`
- 身份：无需网站账号、登录 Cookie、Bearer token 或设备凭据。

```json
{"code":"RBC-0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| code | string | 是 | 卡密原文。去除首尾空白后长度 1–200，区分大小写；商城生成的卡密为 `RBC-` 加 48 位大写十六进制字符。 |

### 卡密有效：HTTP 200

```json
{
  "valid": true,
  "app": "rbc_helper",
  "duration_days": 31,
  "activation_token": "64位小写十六进制随机凭据",
  "activation_expires_at": "2026-11-03T08:00:30+00:00",
  "confirmation_timeout_seconds": 30
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| valid | boolean | 本次验证是否有效并成功取得占用。 |
| app | string | 固定为 `rbc_helper`。 |
| duration_days | integer 或 null | 有效时为购买快照对应的订阅天数，范围 1–36500；无效时为 null。一天表示连续 24 小时。 |
| activation_token | string | 仅成功占用时返回，本次激活完成回执专用的随机凭据；服务端只存哈希，不用于账号登录或设备绑定。 |
| activation_expires_at | string | 仅成功占用时返回，服务端确认截止时间，带时区的 ISO 8601。 |
| confirmation_timeout_seconds | integer | 固定 30，仅成功占用时返回。 |

有效条件：卡密尚未消费且未处于有效占用期，服务端存在对应卡密哈希，应用为 RBC Helper，订阅天数有效，关联商城履约为已领取状态。商品之后改价、修改天数或下架、购买账号停用均不改变已发卡密的快照；履约被收回则验证无效。仅持有码即可查询，不返回购买者或订单信息。

### 卡密无效：HTTP 200

```json
{"valid":false,"app":"rbc_helper","duration_days":null}
```

卡密已消费、卡密不存在、应用不匹配、订阅天数无效或履约不处于已领取状态时统一返回此结果。App 必须检查 `valid`，不能只依据 HTTP 200 判断有效。

### 卡密占用：HTTP 409

```json
{"error":"错误，卡密占用，请稍后重试"}
```

返回 `Retry-After` 响应头，值为向上取整的剩余占用秒数。卡密在服务端处理有效验证时原子取得占用，持久保存占用期限，然后立即返回响应；不会让 HTTP 请求阻塞等待 30 秒。占用期限从服务端创建占用时起计 30 秒，见 `activation_expires_at`。并发请求只有一个取得占用，其余返回上述错误；同一个 App 的验证重试也不例外。

若 30 秒内未收到有效激活完成回执，卡密不作废、占用自动到期，下次验证可重新取得占用并生成新的回执凭据。无需定时任务；旧的占用字段可能仍保留在数据库，但超过截止时间就不再生效。

## 第二步：App 激活完成回执

App 收到有效响应并完成本地激活后，立即请求：

- 方法：`POST`
- 路径：`/api/app/cards/confirm`
- 请求头：`Content-Type: application/json`
- HTTPS，无需账号、Cookie 或设备凭据。

```json
{
  "code": "RBC-0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",
  "activation_token": "第一步返回的64位小写十六进制凭据"
}
```

`code` 沿用验证接口规则；`activation_token` 为必填字符串，必须使用第一步原样返回的 64 位小写十六进制凭据。不能仅凭卡密确认，以免其他请求误确认正在激活的卡密。

在当前占用截止前，凭据匹配且卡密履约仍有效时，服务端记录 `consumed_at` 将卡密作废，返回 HTTP 200：

```json
{"ok":true}
```

从此 `/verify` 返回 `valid=false`、`duration_days=null`。重复 `/confirm` 使用同一卡密及已经成功确认的同一凭据时，返回相同 `ok=true`，不再次修改消费时间；成功确认后此安全重试不受原 30 秒期限限制。

回执超时、凭据不匹配、卡密未取得占用或履约已收回时返回 HTTP 409：

```json
{"error":"激活回执无效或已过期，请重新验证卡密"}
```

在截止时间恰好到达时即视为超时。过期或被新一轮验证替换的旧凭据不能作废卡密，也不能释放当前新占用。`activation_token` 格式错误返回 HTTP 400。

## 网络失败与多次重试

1. **验证响应丢失**：服务器保留占用至 30 秒截止，期间再次 `/verify` 返回占用错误；App 等待截止后重新验证。卡密不会因未收到确认而被消费。
2. **激活完成回执或确认响应丢失**：App 使用同一个 `code` 和 `activation_token` 重发 `/confirm`。可按 1、2、4、8 秒间隔重试，但首次有效确认必须在 30 秒截止前被服务端处理。成功确认后的重试返回 `ok=true`，即使原截止时间已过也不会再次消费。
3. 网络错误或 5xx 可重试；400 应修正输入，409 应按占用或超时提示处理，429 按 `Retry-After` 退避。App 应保存待确认凭据，避免每次网络重试改用新的激活流程。

数据库提交和 HTTP 送达无法原子完成，本流程通过 App 主动完成回执决定消费时机，不把“发送了验证响应”视为已完成激活。若 App 已激活但从未在期限内完成确认，占用仍会超时释放；App 必须处理此结果并避免自行重复累计订阅。此仓库只实现服务端协议，不包含 App 自动重试或本地激活代码。

接口不绑定设备、不生成账号登录凭据、不创建用户订阅、不设置到期时间，也不累计续期。App 自行处理订阅激活与计时。返回天数是卡密完整订阅时长，不是剩余天数。旧 `/api/app/cards/redeem` 及账号登录/权益接口已移除。

## 错误与限流

非成功查询的错误格式为 `{"error":"错误说明"}`。

| HTTP 状态 | 含义 |
| --- | --- |
| 400 | JSON 格式错误、请求不是对象、code 缺失/类型错误/为空/超过长度限制，或确认凭据格式错误。 |
| 403 | 未通过 HTTPS 访问（仅本地联调可关闭 HTTPS 要求）。 |
| 405 | 方法不是 POST，响应头含 `Allow: POST`。 |
| 409 | 验证时卡密被占用，或确认时回执无效/过期。占用错误含剩余秒数 `Retry-After`。 |
| 429 | 每个接口各自按同一客户端地址 5 分钟最多 30 次请求计数，响应头含 `Retry-After: 300`。无效卡密和格式错误请求也计数。验证限流不消耗确认接口额度。 |
| 503 | 系统备份恢复中，暂不可用。 |

接口响应带 `Cache-Control: private, no-store` 和 `Pragma: no-cache`。客户端应避免记录或公开完整卡密及激活回执凭据。

## 调用示例

```sh
curl -X POST 'https://your-domain.example/api/app/cards/verify' \
  -H 'Content-Type: application/json' \
  --data '{"code":"RBC-0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"}'
```

App 完成本地激活后，用验证响应中的原始凭据确认：

```sh
curl -X POST 'https://your-domain.example/api/app/cards/confirm' \
  -H 'Content-Type: application/json' \
  --data '{"code":"RBC-0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF","activation_token":"替换为验证接口返回的凭据"}'
```

示例卡密为说明占位符，真实卡密须从对应服务的商城背包领取。

## 部署与测试

`APP_REQUIRE_HTTPS=1` 默认开启，仅本地 HTTP 联调可设为 `0`。`APP_TRUSTED_PROXY_CIDRS` 配置实际可信代理网段；仅当直连代理受信任时读取其覆盖的单一 `X-Real-IP`。代理应覆盖 `X-Forwarded-Proto` 和 `X-Real-IP`，后端 8000 端口不得公网直达。过期限流记录由接口请求触发小批量清理，无新增后台任务。

```sh
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test club.test_app_pro club.test_shop_fulfillment club.test_account_problem_migrations --noinput
```

并发测试须使用 PostgreSQL。测试卡只属于生成它的数据库；生产须部署接口并发放真实卡密后才能验证。本 PR 不包含 App 源码、安装包或正式部署。
