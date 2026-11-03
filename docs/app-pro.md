# RBC Helper 商品配置与卡密验证 API

## 商城配置

执行 `python manage.py migrate`，新增迁移为 `0053_app_pro_codes`，依赖 `0052_correct_empty_logic_scores`。迁移只增加商品/履约字段、卡密及接口限流记录，不修改旧商品、价格、库存、余额或用户数据。

在商城管理中新增“核销类（卡密）”商品，来源选择“内部 Pro 卡密”，应用选择“RBC Helper”，订阅天数默认 31 天，可设 1–36500 天。库存由管理员设置：`0` 不可购买、`-1` 不限量。已有购买记录的商品不能更换卡密来源。

购买时保存应用和订阅天数快照；修改商品时长或下架不影响已购买商品。购买者从背包领取时生成卡密，重复领取返回同一码。商城履约状态 `redeemed` 在此表示“已领取卡密”，不表示 App 已激活或已消费卡密。卡密哈希单独保存，可回看的原码沿用商城加密存储，部署必须保留原加密密钥。

## 验证接口

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
{"valid":true,"app":"rbc_helper","duration_days":31}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| valid | boolean | 卡密是否有效。 |
| app | string | 固定为 `rbc_helper`。 |
| duration_days | integer 或 null | 有效时为购买快照对应的订阅天数，范围 1–36500；无效时为 null。一天表示连续 24 小时。 |

有效条件：服务端存在对应卡密哈希，应用为 RBC Helper，订阅天数有效，关联商城履约为已领取状态。商品之后改价、修改天数或下架、购买账号停用均不改变已发卡密的快照；履约被收回则验证无效。仅持有码即可查询，不返回购买者或订单信息。

### 卡密无效：HTTP 200

```json
{"valid":false,"app":"rbc_helper","duration_days":null}
```

卡密不存在、应用不匹配、订阅天数无效或履约不处于已领取状态时统一返回此结果。App 必须检查 `valid`，不能只依据 HTTP 200 判断有效。

### 接口边界

此接口只读取卡密有效性和订阅天数。它不消费、核销或绑定卡密，不生成 token，不创建用户订阅，不设置到期时间，也不累计续期。重复或并发验证同一卡密返回同样的购买快照，不改变卡密、订单或用户数据。只有接口限流计数会更新。

App 自行处理订阅激活、计时及是否允许重复使用。接口返回的天数是卡密完整订阅时长，不是剩余天数，也不是服务端已开通的权益。服务端未提供一次性使用保证。旧 `/api/app/cards/redeem` 及账号登录/权益接口已移除，客户端应改用本接口。

### 错误与限流

非成功查询的错误格式为 `{"error":"错误说明"}`。

| HTTP 状态 | 含义 |
| --- | --- |
| 400 | JSON 格式错误、请求不是对象、code 缺失/类型错误/为空/超过长度限制。 |
| 403 | 未通过 HTTPS 访问（仅本地联调可关闭 HTTPS 要求）。 |
| 405 | 方法不是 POST，响应头含 `Allow: POST`。 |
| 429 | 同一客户端地址 5 分钟内超过 30 次请求，响应头含 `Retry-After: 300`。无效卡密和格式错误请求也计数。 |
| 503 | 系统备份恢复中，暂不可用。 |

接口响应带 `Cache-Control: private, no-store` 和 `Pragma: no-cache`。客户端应避免记录或公开完整卡密。

### 调用示例

```sh
curl -X POST 'https://your-domain.example/api/app/cards/verify' \
  -H 'Content-Type: application/json' \
  --data '{"code":"RBC-0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"}'
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
