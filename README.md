ql repo https://github.com/wuyaos/ql-ck.git

---

## 脚本列表

| 文件 | 功能 | cron | 环境变量 |
| --- | --- | --- | --- |
| `ck_ptsite.py` | PT多站签到（GGPT/HDtime/siqi），支持 CookieCloud | `0 10,16,22 * * *` | `PT_CHECKIN_CONFIG` |
| `ck_siyuan.py` | 思源笔记社区 (ld246.com) 签到 | `0 10 0 * * *` | `SIYUAN_USERNAME` / `SIYUAN_PASSWORD` |
| `ck_wps.py` | WPS 会员签到 | `12 6 * * *` | `WPS_COOKIE` |
| `ck_enshan.py` | 恩山论坛签到 | `1 0 * * *` | `COOKIE_ENSHAN` |
| `az_keepalive.py` | AnimeZ 保活（RSS 选种提交 qBittorrent） | `17 3 * * 0` | `AZ_KEEPALIVE_CONFIG` |
| `ins_qinglong_backup.py` | 青龙面板数据备份 | `0 2 * * *` | `QLBK_*` |
| `ins_qinglong_task_delete.py` | 批量删除青龙任务 | 手动 | `DELETE_NAME` / `IPPORT` |

---

## PT多站签到 (`ck_ptsite.py`)

通过单一环境变量 `PT_CHECKIN_CONFIG`（JSON）配置，支持直接填 Cookie 或从 CookieCloud 自动获取。

```json
{
  "cookie_cloud": { "url": "...", "uuid": "...", "password": "..." },
  "sites": {
    "GGPT": "",
    "HDtime": null,
    "siqi": "uid=789; pass=xyz;"
  }
}
```

站点值为空字符串或 `null` 时从 CookieCloud 获取；非空字符串则直接使用该 Cookie。

---

## 思源笔记签到 (`ck_siyuan.py`)

登录 ld246.com 并完成每日签到，获取积分和排行信息。

环境变量：`SIYUAN_USERNAME`、`SIYUAN_PASSWORD`

---

## WPS 签到 (`ck_wps.py`)

WPS 会员每日签到。

环境变量：`WPS_COOKIE`

---

## 恩山论坛签到 (`ck_enshan.py`)

恩山论坛每日签到，返回用户积分和最后签到时间。

环境变量：`COOKIE_ENSHAN`

---

## AnimeZ 保活 (`az_keepalive.py`)

从 AnimeZ 私有 RSS 选取体积最小的种子提交到 qBittorrent，满足"90 天内至少下载一个种子"的保活要求。每周日 03:17 运行，距上次成功超过 75 天才触发实际下载。

```json
{
  "rss_url": "https://animez.to/YOUR_PRIVATE_RSS_URL",
  "qbittorrent": {
    "url": "http://127.0.0.1:8080",
    "username": "admin",
    "password": "adminadmin",
    "category": "AnimeZ",
    "tags": "keepalive"
  }
}
```

依赖：`requests`、`feedparser`、`torf`

---

## 青龙备份 (`ins_qinglong_backup.py`)

每日凌晨 2 点将青龙数据目录打包为 `.tar.gz`，保留最近 N 份（默认 5）。

可选环境变量：`QLBK_BACKUPS_PATH`、`QLBK_MAX_FLIES`、`QLBK_EXCLUDE_NAMES`

---

## 批量删除任务 (`ins_qinglong_task_delete.py`)

按名称前缀批量删除青龙任务及其脚本文件，手动触发。

环境变量：`DELETE_NAME`（支持 `&` 分隔多个前缀）、`IPPORT`（默认 `localhost:5700`）
