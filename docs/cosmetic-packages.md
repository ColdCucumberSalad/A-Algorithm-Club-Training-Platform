# 通用装扮资源与主题包 v1

## 管理员操作

管理工作台的“装扮管理”，以及 RBC 商店管理中的“装扮管理 / 主题包”，进入同一个资源库。

1. 在“可视化制作”中选择主题、徽章或头像框，填写稳定的标识和名称，上传素材。图片按序上传，全部上传请求结束前不能保存、关闭或切换资源；失败项会保留错误提示。主题可设置浅色、深色的语义色，或从主题色自动派生。左侧预览不会改变当前网站的实际主题。
2. 保存资源；取消“可在商品中选择”表示停用新销售，已有购买者的权益与素材快照仍保留。
3. 添加商品，类型选择“装扮”，勾选需要的资源。每项填写独立有效天数，0 表示永久。一个商品可只含一枚徽章，也可组合主题、徽章和头像框。
4. 设置价格、库存和上架状态。资源保存或主题包导入不会自动上架商品。

“上传主题包”提供校验与预览，确认导入后将资源一起保存。若从商品编辑中打开，导入成功会自动把所选资源加入当前商品，再由管理员保存商品。手动制作和导入使用相同的资源校验、渲染与购买接口，无需为每个新主题修改代码或提交 PR。

旧的实物、核销卡密、Pro 卡密、道具和称号保留原业务流程。原主题／徽章商品仍可编辑，保持原商品类型及历史记录。

## 包结构

ZIP 根目录必须是 `theme.json`，图片可放子目录。完整配置示例见 [theme-package-v1.json](../static/cosmetics/theme-package-v1.json)。此文件是配置模板，需配齐其引用的图片后一起压缩。

```text
theme.json
background.webp
badge.png
frame.png
```

```json
{
  "schema_version": 1,
  "name": "花园套装",
  "assets": [
    {
      "kind": "theme", "key": "garden", "name": "花园主题",
      "icon": "badge.png", "poster": "background.webp", "background": "background.webp",
      "duration_days": 30,
      "palettes": {"light": {"accent": "#bb788c"}, "dark": {"accent": "#dda3b5"}}
    },
    {"kind": "badge", "key": "garden", "name": "花园徽章", "icon": "badge.png", "duration_days": 0},
    {"kind": "frame", "key": "garden", "name": "花园头像框", "icon": "frame.png", "duration_days": 90}
  ],
  "components": [
    {"kind": "theme", "key": "garden", "days": 30},
    {"kind": "badge", "key": "garden", "days": 0},
    {"kind": "frame", "key": "garden", "days": 90}
  ]
}
```

资源身份是 `(kind, key)`，因此不同类型可以用相同 key。同类型 key 必须唯一，格式为小写字母开头、后续小写字母／数字／连字符，最多40字符。名称1–100字，说明最多1000字。导入不覆盖已存在资源，避免包之间互相覆盖；修改已有资源需在编辑器中读取当前版本并保存。

`assets[].duration_days` 是创建商品时建议使用的时长；`components[].days` 是套装实际销售时长。省略 `components` 时，默认包含包内全部资源并采用各自建议时长。一个包／商品最多12项资源，不能重复引用同类型同 key；商品也可引用已有资源，不必每次重新上传。

## 素材与主题样式

- ZIP 最多20MB、最多40个条目、解压大小合计最多64MB。单图最多8MB、1600万像素、任一边最多8192像素，配置文件最多128KB。
- 上传支持静态 PNG／JPG／WebP。徽章和头像框推荐透明 PNG；背景和海报建议压缩后提交。上传图会转成无元数据的 PNG，以内容散列保存，重复内容复用同一资源。
- 不执行包内 JS、CSS、HTML 或 SVG，不允许外部图片链接、加密文件、符号链接、重复文件或越界路径。已有随程序维护的静态 SVG 素材继续兼容；创作者上传新 SVG 时请先导出透明 PNG。
- 徽章沿用统一显示位：普通26px、榜单24px、手机22px。素材主体居中，避免过多透明留白。头像框使用圆角方形头像，不改变现有头像形状。
- 头像框 `geometry` 可设置 `scale`（1–2）、`x` 和 `y`（各 -1–1，均以头像尺寸为单位）。默认 `{"scale":1.25,"x":-0.125,"y":-0.225}`。检查小头像、大头像和列表间距。
- 主题使用语义色：`pageBackground`、`surface`、`surfaceElevated`、`separator`、`labelPrimary`、`labelSecondary`、`labelTertiary`、`fill`、`accent`、`overlayDim`。支持 `#RRGGBB`／`#RRGGBBAA`；未填角色使用默认色，浅色和深色分别配置。
- 背景、颜色通过原主题引擎应用，不修改全站布局或保存的个人色板。切换沿用实色双波动画，并遵守关闭动画、减少动态效果设置。

## 拥有、佩戴与续期

商品购买或管理员发放在原有事务中逐项授予装扮。权益按账号共享，主题按账号启用，徽章、头像框按团队独立选择。购买不自动换装；主题到期后，仍有效的徽章或头像框继续可用。

各项天数独立计算：有限期从 `max(当前服务器时间, 原有效期截止)` 继续加天数；永久权益保持永久。整套全为已永久拥有的装扮时拒绝再次购买；若套装仍有可续期或未拥有项，则正常购买。永久资格保留在原购买／发放来源；其他套装按本次销售期限单独记录，不复制该永久资格。同一来源已有的永久权益不降级。账号聚合所有有效来源，收回原永久来源后只保留其他来源各自的有效期。称号的有限期续购也沿用累加规则。一次购买／发放一套，请求重试复用原编号，不重复扣币、扣库存或续期。

购买记录保存资源定义、版本、时长与授予后的到期时间快照。修改资源或商品只影响之后的购买，不覆盖历史购买记录。再次购买该资源时使用新版本，并在原剩余时长上继续累加。停用资源不使已经拥有的版本失效；下架商品不撤销原权益；收回来源库存则停止该来源。原实物会徽永久赠品仍按独立购买赠品记录保留。

## 通用接口

下列管理接口均要求系统管理员身份，并沿用站点的 CSRF 校验：

| 接口 | 格式与用途 |
| --- | --- |
| `GET /api/management/cosmetic-assets` | 读取资源库，含停用项与 `revision` |
| `POST /api/management/cosmetic-assets` | JSON 新建／编辑资源；编辑提交原 `revision`，防止覆盖其他操作 |
| `POST /api/management/cosmetic-assets/upload` | multipart 的 `file` 上传单图，返回受控图片 URL |
| `POST /api/management/cosmetic-assets/package` | multipart 的 `file` 上传 ZIP，校验、提供预览配置；此步不创建资源记录或商品 |
| `POST /api/management/cosmetic-assets/import` | JSON 提交预览返回的 `assets` 与 `components`；全部成功或全部回滚 |
| `POST/PUT /api/currency/admin/shop` | `item_type: "cosmetic"`，`cosmetic_bundle` 为 `{kind,key,days}` 列表，其他价格库存字段不变 |

资源 JSON 字段包括 `kind`、`key`、`name`、`description`、`duration_days`、`icon`、`poster`、`background`、`palettes`、`geometry`、`is_active`。图片 URL 必须是上传接口返回的地址或程序中已有的受控静态素材。编辑不可改变身份或类型，使用旧版本号保存会报错。

`GET/POST /api/profile/cosmetics` 仍是拥有与换装接口。客户端从服务端元数据读取素材、色板和有效期，不再按塔菲等名称写白名单。保留统一到期计时和状态版本保护，不新增高频轮询。

## 更新与验证

迁移至 `0066_universal_cosmetics`、`0067_purchase_badge_snapshot`，把现有塔菲主题、两种徽章和护目镜头像框登记为可编辑资源；旧赠品继续兼容。旧 `CosmeticGrant` 和实物赠品记录补入原资源定义，不重置到期时间或佩戴。此分支包含实物赠品迁移0065；已部署该迁移时不会重复发放。

更新前备份数据库、媒体和当前代码。执行迁移、静态资源收集，同步更新并重启 Web／Worker／Beat。不增加新容器。上传图片属于媒体数据，后续备份和迁移需带上媒体目录。

验证重点：包校验与整批回滚、未授权操作、资源版本冲突、购买失败、重复请求、独立到期与续期、永久权益、多个团队、源库存收回、旧资源兼容、两种外观及手机布局。后端测试入口 `club.test_universal_cosmetics`，前端入口 `tests/dynamic-cosmetics.test.cjs`。
