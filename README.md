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

---

## AnimeZ 保活 (`az_keepalive.py`)

从 AnimeZ 私有 RSS 选取体积最小的种子提交到 qBittorrent，满足"90 天内至少下载一个种子"的保活要求。

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

依赖：`requests`, `feedparser`, `torf`

---
