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

def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s]: %(message)s')
    logger = logging.getLogger("DmallFullTrace")
    logger.setLevel(logging.DEBUG)
    info_handler = TimedRotatingFileHandler(os.path.join(log_dir, "info.log"), when="midnight", interval=1, backupCount=30, encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(info_handler); logger.addHandler(console_handler)
    return logger

log = setup_logger()
load_dotenv("_env")

class FeishuClient:
    def __init__(self):
        self.config = {"app_id": os.getenv("FEISHU_APP_ID"), "app_secret": os.getenv("FEISHU_APP_SECRET"), "app_token": os.getenv("BITABLE_APP_TOKEN"), "table_id": os.getenv("BITABLE_TABLE_ID")}
        self.token = self._get_token()

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            res = requests.post(url, json={"app_id": self.config["app_id"], "app_secret": self.config["app_secret"]}).json()
            return res.get("tenant_access_token") if res.get("code") == 0 else None
        except: return None

    def check_exists(self, ticket_no):
        if not self.token: return False
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records/search"
        try:
            res = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"filter": {"conjunction": "and", "conditions": [{"field_name": "Ticket No", "operator": "contains", "value": [str(ticket_no)]}]}}).json()
            return res.get("data", {}).get("total", 0) > 0
        except: return False

    def sync_record(self, fields):
        log.info(f"📡 [DEBUG] 准备发送数据到飞书: {fields['Ticket No']['text']}")
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records"
        try:
            response = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": fields})
            res_data = response.json()
            if res_data.get("code") == 0:
                log.info(f"✅ 飞书同步成功!")
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
    async with async_playwright() as p:
        log.info("🚀 启动 SDP 自动化 (v4.9.2 MailCheck)...")
        auth_file = "auth.json"
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )
        context = await browser.new_context(storage_state=auth_file) if os.path.exists(auth_file) else await browser.new_context()
        page = await context.new_page()
        feishu = FeishuClient()
        base_url = os.getenv("SDP_BASE_URL")

        try:
            await page.goto(base_url + "/app/itdesk/ui/requests")
            try:
                target = await page.wait_for_selector("#searchReq, .requestlistview_header, #userNameInput", timeout=15000)
                if await target.get_attribute("id") == "userNameInput":
                    await page.locator("#userNameInput").fill(os.getenv("SDP_USERNAME"))
                    await page.locator("#passwordInput").fill(os.getenv("SDP_PASSWORD"))
                    await page.locator("#submitButton").click()
                    await page.wait_for_timeout(10000)
                    await context.storage_state(path=auth_file)
            except: pass

            # 视图切换
            try:
                await page.get_by_role("button", name="FRG ITS - Dmall").first.click(); await page.wait_for_timeout(6000)
                sort_h = page.locator('th[data-column-index="7"]').first
                await sort_h.click(force=True); await page.wait_for_timeout(4000)
                await sort_h.click(force=True); await page.wait_for_timeout(5000)
                await page.locator("#searchReq, .list-search-icon").first.click(); await page.wait_for_timeout(4000)
                st_input = page.locator('div[data-search-field-name="status"] input').first
                await st_input.fill("Open")
                await page.locator(".sdp-table-search-go button, .sdp-table-search-go .btn").first.click(); await page.wait_for_timeout(8000)
            except: pass

            # 抓取逻辑
            headers = await page.locator(".requestlistview_header td, th").all_inner_texts()
            tickets = await page.evaluate("""() => {
                const results = [];
                const seen = new Set();
                const links = Array.from(document.querySelectorAll('a'))
                                   .filter(a => /\\/app\\/itdesk\\/ui\\/requests\\/\\d+\\/details/.test(a.href));
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

            log.info(f"📈 扫描结束: 发现 {len(tickets)} 个工单")

            for t in tickets:
                if feishu.check_exists(t['no']): continue
                log.info(f"🛠️ 处理: {t['no']}")
                await page.goto(t['url'])
                await asyncio.sleep(6)
                
                try:
                    # 1. 点击 Reply All 并等待加载
                    await page.get_by_text("Reply All").click(); await asyncio.sleep(4)
                    
                    # 2. [核心优化] 检查收件人地址是否为空
                    try:
                        to_input = page.locator("input#to").first
                        current_to = await to_input.input_value()
                        if not current_to.strip():
                            default_mail = "smm.its.pos@smmarkets.com.ph"
                            log.warning(f"⚠️ [MailCheck] 工单 {t['no']} 收件人为空，正在自动填充默认地址: {default_mail}")
                            await to_input.fill(default_mail)
                        else:
                            log.info(f"✅ [MailCheck] 工单 {t['no']} 已有收件人: {current_to}")
                    except Exception as mail_e:
                        log.error(f"❌ [MailCheck] 检查收件人框时出错: {mail_e}")

                    # 3. 选择模板
                    await page.locator("span:has-text('Default Reply Template'), #template_selector_link").first.click(); await asyncio.sleep(2)
                    await page.get_by_text("Dmall Helpdesk Response", exact=True).click()
                    try: await page.locator("button:has-text('Yes')").first.click(timeout=2000)
                    except: pass
                    
                    # 4. 发送
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
                    log.error(f"❌ 内部流程错误: {e}")

        finally:
            await browser.close()
            log.info("🏁 流程结束")

if __name__ == "__main__":
    asyncio.run(run_automation())
