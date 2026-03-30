import asyncio
import os
import re
import logging
import requests
import json
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# 版本号: v4.9.2_MailCheck_Cloud
# 变更点:
# 1. 云端部署版本：headless=True，适配无GUI服务器环境
# 2. 添加反检测参数：--disable-blink-features=AutomationControlled
# 3. 添加安全参数：--no-sandbox, --disable-dev-shm-usage
# 4. 增加详细日志，便于排查问题

def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s]: %(message)s')
    logger = logging.getLogger("DmallFullTrace")
    logger.setLevel(logging.DEBUG)
    info_handler = TimedRotatingFileHandler(os.path.join(log_dir, "info.log"), when="midnight", interval=1, backupCount=30, encoding="utf-8")
    info_handler.setLevel(logging.DEBUG)
    info_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(info_handler); logger.addHandler(console_handler)
    return logger

log = setup_logger()
load_dotenv("_env")

class FeishuClient:
    def __init__(self):
        self.config = {"app_id": os.getenv("FEISHU_APP_ID"), "app_secret": os.getenv("FEISHU_APP_SECRET"), "app_token": os.getenv("BITABLE_APP_TOKEN"), "table_id": os.getenv("BITABLE_TABLE_ID")}
        self.token = self._get_token()
        log.info(f"📡 [DEBUG] 飞书客户端初始化, app_id={self.config['app_id'][:10]}...")

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        log.info(f"📡 [DEBUG] 获取飞书 token, url={url}")
        try:
            res = requests.post(url, json={"app_id": self.config["app_id"], "app_secret": self.config["app_secret"]}).json()
            if res.get("code") == 0:
                log.info("📡 [DEBUG] 飞书 token 获取成功")
                return res.get("tenant_access_token")
            else:
                log.error(f"📡 [ERROR] 飞书 token 获取失败: {res}")
                return None
        except Exception as e:
            log.error(f"📡 [ERROR] 获取飞书 token 异常: {e}")
            return None

    def check_exists(self, ticket_no):
        log.info(f"📡 [DEBUG] 检查工单是否存在飞书: {ticket_no}")
        if not self.token:
            log.warning("📡 [WARNING] 飞书 token 为空，跳过检查")
            return False
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records/search"
        try:
            res = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"filter": {"conjunction": "and", "conditions": [{"field_name": "Ticket No", "operator": "contains", "value": [str(ticket_no)]}]}}).json()
            total = res.get("data", {}).get("total", 0)
            log.info(f"📡 [DEBUG] 飞书检查结果: {ticket_no} -> {total} 条记录")
            return total > 0
        except Exception as e:
            log.error(f"📡 [ERROR] 检查飞书记录异常: {e}")
            return False

    def sync_record(self, fields):
        log.info(f"📡 [DEBUG] 准备发送数据到飞书: {fields['Ticket No']['text']}")
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records"
        try:
            response = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": fields})
            res_data = response.json()
            if res_data.get("code") == 0:
                log.info(f"✅ 飞书同步成功: {fields['Ticket No']['text']}")
            else:
                log.error(f"❌ 飞书 API 报错: {res_data.get('msg')} (Code: {res_data.get('code')})")
        except Exception as e:
            log.error(f"❌ 飞书通讯严重异常: {e}")

PRIORITY_MAP = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}

def parse_sdp_date(date_str):
    try:
        dt = datetime.strptime(" ".join(date_str.split()), "%b %d, %Y %I:%M %p")
        return int(dt.timestamp() * 1000)
    except: return int(datetime.now().timestamp() * 1000)

async def run_automation():
    log.info("="*50)
    log.info("🚀 启动 SDP 自动化 (v4.9.2 MailCheck Cloud)...")
    log.info("="*50)

    auth_file = "auth.json"
    feishu = FeishuClient()
    base_url = os.getenv("SDP_BASE_URL")

    log.info(f"📝 [DEBUG] SDP_BASE_URL={base_url}")
    log.info(f"📝 [DEBUG] auth_file exists: {os.path.exists(auth_file)}")

    async with async_playwright() as p:
        log.info("🌐 [DEBUG] 启动 Chromium 浏览器...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )
        log.info("✅ [DEBUG] 浏览器启动成功")

        context = await browser.new_context(storage_state=auth_file) if os.path.exists(auth_file) else await browser.new_context()
        log.info(f"✅ [DEBUG] 浏览器上下文创建成功, has_storage_state: {os.path.exists(auth_file)}")

        page = await context.new_page()
        page.set_default_timeout(120000)  # 增加超时到120秒
        log.info("✅ [DEBUG] 新页面创建成功")

        try:
            log.info(f"🌐 [DEBUG] 访问 SDP: {base_url}/app/itdesk/ui/requests")
            await page.goto(base_url + "/app/itdesk/ui/requests", wait_until="domcontentloaded", timeout=120000)
            log.info("✅ [DEBUG] 页面加载完成")

            # 检查是否需要登录
            try:
                log.info("🔍 [DEBUG] 检查登录状态...")
                target = await page.wait_for_selector("#searchReq, .requestlistview_header, #userNameInput", timeout=15000)
                element_id = await target.get_attribute("id")
                log.info(f"🔍 [DEBUG] 检测到元素 id: {element_id}")

                if element_id == "userNameInput":
                    log.info("🔐 [INFO] 需要登录，执行自动登录...")
                    await page.locator("#userNameInput").fill(os.getenv("SDP_USERNAME"))
                    await page.locator("#passwordInput").fill(os.getenv("SDP_PASSWORD"))
                    await page.locator("#submitButton").click()
                    log.info("✅ [INFO] 登录表单已提交，等待 10 秒...")
                    await page.wait_for_timeout(10000)
                    await context.storage_state(path=auth_file)
                    log.info(f"✅ [INFO] 登录状态已保存到 {auth_file}")
                else:
                    log.info("✅ [INFO] 已登录，跳过登录步骤")
            except Exception as e:
                log.warning(f"⚠️ [WARNING] 登录检查异常: {e}，可能已登录")

            # 视图切换
            try:
                log.info("🔄 [DEBUG] 点击 FRG ITS - Dmall 按钮...")

                # 先截图看看页面内容
                await page.screenshot(path="debug_page.png")
                log.info("📸 [DEBUG] 已截图保存到 debug_page.png")

                # 打印页面所有按钮
                buttons = await page.get_by_role("button").all()
                log.info(f"🔍 [DEBUG] 页面共有 {len(buttons)} 个按钮:")
                for btn in buttons[:10]:
                    try:
                        name = (await btn.inner_text()).strip()
                        if name:
                            log.info(f"  按钮: {name}")
                    except: pass

                await page.get_by_role("button", name="FRG ITS - Dmall").first.click()
                await page.wait_for_timeout(6000)
                log.info("✅ [DEBUG] 视图切换完成")

                log.info("🔄 [DEBUG] 点击排序按钮...")
                sort_h = page.locator('th[data-column-index="7"]').first
                await sort_h.click(force=True); await page.wait_for_timeout(4000)
                await sort_h.click(force=True); await page.wait_for_timeout(5000)
                log.info("✅ [DEBUG] 排序完成")

                log.info("🔄 [DEBUG] 打开搜索面板...")
                await page.locator("#searchReq, .list-search-icon").first.click(); await page.wait_for_timeout(4000)

                log.info("🔄 [DEBUG] 输入搜索条件: status=Open")
                st_input = page.locator('div[data-search-field-name="status"] input').first
                await st_input.fill("Open")
                await page.locator(".sdp-table-search-go button, .sdp-table-search-go .btn").first.click(); await page.wait_for_timeout(8000)
                log.info("✅ [DEBUG] 搜索完成")
            except Exception as e:
                log.warning(f"⚠️ [WARNING] 视图切换异常: {e}")

            # 抓取逻辑
            log.info("🔍 [DEBUG] 开始抓取工单数据...")
            headers = await page.locator(".requestlistview_header td, th").all_inner_texts()
            log.info(f"🔍 [DEBUG] 表头: {headers[:5]}...")

            tickets = await page.evaluate("""() => {
                const results = [];
                const seen = new Set();
                const links = Array.from(document.querySelectorAll('a'))
                                   .filter(a => /\\/app\\/itdesk\\/ui\\/requests\\/\\d+\\/details/.test(a.href));
                console.log('Found links:', links.length);
                links.forEach(link => {
                    const row = link.closest('tr');
                    if (row) {
                        const cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                        let tNo = cells[4] || "N/A";
                        if (seen.has(tNo)) return;
                        if (cells[10] && cells[10].toLowerCase().includes("open") && !/\\d/.test(cells[14]||"")) {
                            seen.add(tNo);
                            results.push({ no: tNo, subject: link.innerText.trim() || cells[5], priority: cells[9], date: cells[7], url: link.href });
                        }
                    }
                });
                return results;
            }""")

            log.info(f"📈 [DEBUG] 扫描结束: 发现 {len(tickets)} 个工单")
            if len(tickets) > 0:
                log.info(f"📋 [DEBUG] 工单列表: {tickets}")

            if len(tickets) == 0:
                log.warning("⚠️ [WARNING] 未发现任何待处理工单")
            else:
                for t in tickets:
                    log.info(f"--- 🛠️ 处理工单: {t['no']} ---")

                    # 检查飞书是否已存在
                    if feishu.check_exists(t['no']):
                        log.info(f"⏭️ [INFO] 工单 {t['no']} 已存在于飞书，跳过")
                        continue

                    log.info(f"🔗 [DEBUG] 跳转详情页: {t['url']}")
                    await page.goto(t['url'])
                    await asyncio.sleep(6)

                    try:
                        # 1. 点击 Reply All 并等待加载
                        log.info(f"🖱️ [DEBUG] 点击 Reply All 按钮...")
                        await page.get_by_text("Reply All").click(); await asyncio.sleep(4)
                        log.info("✅ [DEBUG] Reply All 点击完成")

                        # 2. [核心优化] 检查收件人地址是否为空
                        try:
                            to_input = page.locator("input#to").first
                            current_to = await to_input.input_value()
                            log.info(f"📧 [DEBUG] 当前收件人: '{current_to}'")
                            if not current_to.strip():
                                default_mail = "smm.its.pos@smmarkets.com.ph"
                                log.warning(f"⚠️ [MailCheck] 工单 {t['no']} 收件人为空，正在自动填充默认地址: {default_mail}")
                                await to_input.fill(default_mail)
                            else:
                                log.info(f"✅ [MailCheck] 工单 {t['no']} 已有收件人: {current_to}")
                        except Exception as mail_e:
                            log.error(f"❌ [MailCheck] 检查收件人框时出错: {mail_e}")

                        # 3. 选择模板
                        log.info(f"🖱️ [DEBUG] 点击模板选择器...")
                        await page.locator("span:has-text('Default Reply Template'), #template_selector_link").first.click(); await asyncio.sleep(2)
                        log.info(f"🖱️ [DEBUG] 选择模板 Dmall Helpdesk Response...")
                        await page.get_by_text("Dmall Helpdesk Response", exact=True).click()
                        try:
                            await page.locator("button:has-text('Yes')").first.click(timeout=2000)
                            log.info("✅ [DEBUG] 点击 Yes 确认")
                        except: pass

                        # 4. 发送
                        log.info(f"🖱️ [DEBUG] 点击 Send 按钮...")
                        await asyncio.sleep(1); await page.locator("button:has-text('Send')").first.click()
                        log.info(f"📩 邮件已发送: {t['no']}")

                        # 5. 同步飞书
                        fields = {
                            "Ticket No": {"text": t['no'], "link": t['url']},
                            "Subject": t['subject'],
                            "Priority": PRIORITY_MAP.get(t['priority'], "P3"),
                            "Create date": parse_sdp_date(t['date']),
                            "Status": "Following"
                        }
                        feishu.sync_record(fields)

                    except Exception as e:
                        log.error(f"❌ [ERROR] 工单 {t['no']} 处理异常: {e}")

        finally:
            await browser.close()
            log.info("🔌 浏览器已关闭")
            log.info("🏁 任务流结束")

if __name__ == "__main__":
    asyncio.run(run_automation())
