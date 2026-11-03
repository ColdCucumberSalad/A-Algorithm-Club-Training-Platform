# RBC Helper 商品配置与 App 卡密验证

只包含商城 Pro 商品配置、购买领卡所需的数据及 App 卡密验证接口。App 无需网站账号密码；持有码即视为持有兑换凭证。

## 商品配置与领卡

执行 `python manage.py migrate`，新增迁移为 `0053_app_pro_codes`、`0054_card_device`。迁移只增加商品/履约字段、权益、卡密及接口限流记录，不修改旧商品、价格、库存、余额或用户数据。

在商城管理中新增“核销类（卡密）”商品，来源选择“内部 Pro 卡密”，应用选择“RBC Helper”，时长默认 31 天，可设 1–36500 天。库存由管理员明确设置：`0` 不可购买、`-1` 不限量。已有购买记录的商品不能更换卡密来源。

购买时保存应用和时长快照；以后修改商品时长或下架不影响已购买商品。购买者从背包领取时生成卡密，重复领取返回同一码。领取不会开通权益，首次在 App 核销后才开始计时。卡密哈希单独保存，可回看的原码沿用商城加密存储，部署必须保留原加密密钥。

## 唯一 App 接口

`POST /api/app/cards/redeem`，路径无结尾斜杠，使用 HTTPS 和 `Content-Type: application/json`：

```json
{"code":"RBC-...","device_secret":"64位小写十六进制随机秘密"}
```

App 首次使用时生成设备秘密并保存到系统安全存储，续期和重试沿用同一个值，不使用公开设备编号。首次核销将卡密绑定到设备秘密的 SHA-256 哈希。

成功响应 HTTP 200，保留现有 App 授权结构：

```json
{
  "token": "请求中的device_secret",
  "token_expires_at": "8999-01-01T00:00:00+00:00",
  "user": {"id": "card:123", "username": "卡密授权"},
  "pro": {
    "active": true,
    "expires_at": "2026-12-04T08:00:00+00:00",
    "server_time": "2026-11-03T08:00:00+00:00"
  }
}
```

`token` 仅为兼容 App 的本机卡密凭据，不是网站登录 token；`token_expires_at` 也不是 Pro 到期时间。App 必须依据 `pro.active`、`pro.expires_at` 和服务器时间判断权益。

权益归属于购买账号，同设备的续期卡须来自同一购买账号。首次核销按 `max(server_now, expires_at) + duration_days` 叠加时长，一天为连续 24 小时。同设备重试返回当前状态，不重复加时；已核销卡密不能在另一设备再次使用。停用账号不能核销。App 日常在本地判断到期，仅核销时联网，无法即时感知服务端状态变化。

错误格式为 `{"error":"错误说明"}`：400 输入或卡密无效、账号不可用或日期溢出；403 非 HTTPS；405 方法错误；409 设备冲突或续期卡购买账号不同；429 请求过于频繁，带 `Retry-After`；503 系统备份恢复中。响应带 `Cache-Control: private, no-store`。

## 部署与验证

`APP_REQUIRE_HTTPS=1` 默认开启，仅本地 HTTP 联调可设为 `0`。`APP_TRUSTED_PROXY_CIDRS` 配置实际可信代理网段；仅当直连代理受信任时读取其覆盖的单一 `X-Real-IP`。代理应覆盖 `X-Forwarded-Proto` 和 `X-Real-IP`，后端 8000 端口不得公网直达。每个客户端地址 5 分钟最多 30 次核销请求；过期限流记录由接口请求触发小批量清理，无新增后台任务。

```sh
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test club.test_app_pro club.test_shop_fulfillment club.test_account_problem_migrations --noinput
```

并发测试须使用 PostgreSQL。测试卡只属于生成它的数据库；正式 App 必须在正式服务部署并发放卡密后才能核销。本 PR 不包含 App 源码、安装包或正式部署。
