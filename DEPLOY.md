# SDP 工单自动处理脚本 - 阿里云部署指南

## 一、环境要求

| 项目 | 要求 |
|------|------|
| 系统 | Ubuntu 20.04+ / Debian 11+ |
| Python | 3.8+ |
| 内存 | 至少 2GB |
| 网络 | 可访问 SDP 和飞书 |

## 二、Git 部署方式

### 1. 克隆代码

```bash
# 克隆仓库
git clone https://github.com/danielzhouling/Ticket_acknowledge.git
cd Ticket_acknowledge
```

### 2. 安装依赖

```bash
# 更新包列表
sudo apt-get update

# 安装 Playwright 所需系统库
sudo apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libpulse-mainloop-glib0

# 安装 pip（如果未安装）
sudo apt-get install -y python3-pip

# 安装 Python 依赖
pip3 install requests python-dotenv playwright

# 安装 Chromium 浏览器
python3 -m playwright install chromium
```

### 3. 配置环境变量

```bash
# 复制环境变量文件（本地手动创建，不要提交到 Git）
cp _env.example _env

# 编辑配置
vim _env
```

确保 `_env` 配置正确：

```env
# SDP 配置
SDP_USERNAME=frg0023@smretailinc.com
SDP_PASSWORD=SMRetailinc@2026
SDP_BASE_URL=https://servicedeskplus.smretailinc.com

# 飞书 Bitable 配置
BITABLE_APP_TOKEN=SyY3bxIBCabMLasV9TFcbjo8nvh
BITABLE_TABLE_ID=tblAcVEt9CBty154
FEISHU_APP_ID=cli_a932aed4ec389bcb
FEISHU_APP_SECRET=VEDSStFLUfeYWJe86oQwnhOxdUiaTiaN
```

## 三、首次运行（创建登录状态）

```bash
# 首次运行需要手动登录（使用 VNC 或有浏览器的方式）
# 这会保存 auth.json，后续运行可自动登录
python3 ticket_cloud.py
```

> **重要**：首次运行需要在有图形界面的环境，或通过 VNC 远程桌面手动登录一次。登录成功后 `auth.json` 会被保存，后续即可无人值守运行。

## 四、定时任务配置

### 1. 编辑 crontab

```bash
crontab -e
```

### 2. 添加定时任务

```cron
# 每小时运行一次 Open 工单处理
0 * * * * cd /home/user/Ticket_acknowledge && python3 /home/user/Ticket_acknowledge/ticket_cloud.py >> /home/user/Ticket_acknowledge/logs/cron.log 2>&1

# 每小时运行一次 Assigned 工单处理
30 * * * * cd /home/user/Ticket_acknowledge && python3 /home/user/Ticket_acknowledge/ticket_assign_cloud.py >> /home/user/Ticket_acknowledge/logs/cron_assign.log 2>&1
```

### 3. 定时任务说明

| 表达式 | 说明 |
|--------|------|
| `0 * * * *` | 每小时整点运行 |
| `30 * * * *` | 每小时半点运行 |

## 五、日志查看

```bash
# 查看最近运行日志
tail -f logs/info.log

# 查看云端专用日志
tail -f logs/operation_detail.log
```

## 六、故障排查

### 问题 1：Chromium 无法启动

```bash
# 重新安装 Chromium
python3 -m playwright install chromium
```

### 问题 2：SDP 登录失败

- 检查 `auth.json` 是否存在
- 删除 `auth.json` 重新运行手动登录
- 检查网络是否能访问 SDP

### 问题 3：飞书同步失败

- 检查 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确
- 检查飞书 API token 是否过期

### 问题 4：headless 模式被检测

当前脚本已添加反检测参数，如仍被拦截可尝试：
- 使用真实浏览器 user-agent
- 添加随机延时

## 七、Git 推送本地更新

```bash
# 查看变更
git status

# 添加文件
git add .

# 提交
git commit -m "update: 修改内容"

# 推送到远程
git push origin main
```

## 八、服务器更新代码

```bash
# 进入项目目录
cd /home/user/<repo>

# 拉取最新代码
git pull origin main

# 重启定时任务（如需要）
```

## 九、文件结构

```
/home/user/Ticket_acknowledge/
├── .gitignore              # Git 忽略配置
├── _env.example            # 环境变量示例（不要包含敏感信息）
├── ticket.py               # Open 工单处理（本地版）
├── ticket_assign.py        # Assigned 工单处理（本地版）
├── ticket_cloud.py         # Open 工单处理（云端版）
├── ticket_assign_cloud.py # Assigned 工单处理（云端版）
├── DEPLOY.md               # 部署文档
├── auth.json               # 登录状态（自动生成，不提交 Git）
└── logs/                   # 日志目录
    ├── info.log
    └── operation_detail.log
```

## 十、注意事项

1. **安全**：不要将 `_env` 文件提交到 Git，已在 `.gitignore` 中排除
2. **监控**：建议设置告警，当日志出现 ERROR 时通知
3. **资源**：每次运行约需 5-10 分钟，确保 cron 间隔足够
4. **备份**：定期备份 `auth.json`

## 十一、常用命令

```bash
# 手动运行测试
python3 ticket_cloud.py

# 查看定时任务
crontab -l

# 删除定时任务
crontab -r

# 查看运行中的 Python 进程
ps aux | grep python

# 停止脚本
pkill -f ticket_cloud.py

# 拉取最新代码
git pull origin main
```
