# 网站更新与备份

管理工作台一级导航“更新与备份”包含网站更新和完整备份恢复。只有系统管理员可以访问网站更新接口。

默认每天北京时间 04:00 检查 `Monkey181x/A-Algorithm-Club-Training-Platform` 的 `main`，发现新版本自动更新。可在页面改为仅提醒、不检查，或调整时间。关闭定时检查后仍可立即检查及手动更新。

## 网络线路

2026-11-04 在线上服务器测试：GitHub Git 查询连续三次成功；codeload 固定版本源码下载连续三次成功，用时约 4.8、4.9、5.8 秒。延长测试后 Git 直连偶尔超时，官方 API 仍可用。加速站按其官方文档测试：GH-Proxy 和 GHFast 固定版本下载成功；优先官方、故障时再尝试经过文件校验的镜像。

- 版本查询：GitHub Git `ls-remote` 和 GitHub API，至少一路可用；两路同时可用但结果不一致时中止并稍后重试。
- 只允许主分支向前更新；线上存在未合并修复或分叉版本时拒绝降级，要求人工核对。
- 固定版本下载：GitHub codeload → GitHub API tarball → GH-Proxy → GHFast。始终下载已确认的完整提交 SHA，逐文件计算 Git blob 哈希并与 GitHub 官方提交树核对，拒绝缺失、多余或被替换的文件。官方树无法获取时停止，不降低校验要求。镜像不接收服务器密钥或 GitHub token。
- 所有下载线路都失败则保留当前版本。页面显示检查线路状态，宿主机保留详细操作日志；页面不接收自定义仓库、分支、下载地址或命令。

## 保护数据

更新服务先下载、构建新镜像，在隔离 PostgreSQL 副本演练迁移，并比较所有原有表及字段的逐行摘要。数据迁移会修改原有值、删除列或表时，自动更新保守中止，需要人工审查；不使用 `--fake` 或重跑初始化脚本。

正式切换停止 web、worker、beat，备份数据库、媒体、静态资源、部署配置和原环境文件，再执行迁移和同样的数据校验。保留数据库和 Redis 容器、密钥及数据挂载。新 Web 健康并通过公网检查后才恢复后台任务。失败时先校验备份，再在停止写入的状态下恢复旧数据库、文件、部署配置和镜像。若回退也失败，保留停写状态和备份，需人工恢复。

备份保存在服务器 `deploy-backups/managed-*`，日志和源码在 `releases/managed-*`，默认不自动删除。请定期检查磁盘并将备份复制到其他设备。

## 安装

这是宿主机服务，不在 Django/Celery 内执行 Docker，不向网站挂载 Docker socket。安装需由维护人员在宿主机完成一次：

针对当前线上 `/opt/club-platform` 部署，可直接运行 `sudo python3 deploy/install_site_updater.py`，安装前会保留 Compose 副本。该命令只安装协调器和控制目录挂载，网站应用新镜像重建后才会出现已连接状态。其他部署按以下步骤安装。

1. 将本目录的 `site_updater.py`、`site_update_audit.py` 安装至 `/opt/club-platform/site-updater/`，权限仅 root 可写。安装 Python 3.10+、git、Docker Compose。宿主机要能验证 GitHub HTTPS 证书。
2. 创建 `config.json`，字段为 `project`（部署目录）、`control`（状态队列目录）、`compose_project`、`network`、`health_url`（正式网站 HTTPS 健康页面）。这些设置仅宿主机维护人员可改。当前实现要求部署目录下存在 `compose.yaml`、`.env`、`data/media`、`data/static`，三个应用服务使用同一镜像；服务名为 web/worker/beat/db。
3. 仅为 web 增加控制目录绑定，例如 `/opt/club-platform/data/site-updater:/app/site-updater`；给 web 设置 `SITE_UPDATE_DIR=/app/site-updater`。源代码镜像无需包含线上环境配置。
4. 将 `site-updater.service` 安装为 systemd 服务，按实际目录修正路径，启用服务。安装当天在控制目录写入 `last-scheduled.json` 的 `date` 为北京时间当日，首次自动检查将在次日 04:00。`schedule.json` 默认值为 `{"mode":"auto","time":"04:00"}`。
5. 首次上线先在管理工作台“立即检查”，核对版本、线路及状态；备份恢复沿用原入口。

更新协调器独立于被更新网站，不会因 web 容器重启失去进度。协调器本身升级由维护人员审核后安装。若协调器重启时检测到中断中的更新，会显示失败信息，保留备份供人工核对。部署环境不匹配时保持禁用并显示未连接。

加速站用法参考：[GH-Proxy 官方文档](https://gh-proxy.com/docs/quick-start)、[GHFast](https://ghfast.top/)。可用性以服务器实测为准。
