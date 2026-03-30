import asyncio
import os
import logging
import requests
import json
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# =========================================================
# 版本号: v6.3.3_Final_Template_Fix
# 变更点确认：
# 1. [FIX] 解决截图中的冲突：改用 CSS 路径 ".select2-result-label" 定位模板。
# 2. [FIX] 彻底避开 select2-hidden-accessible 的干扰。
# 3. [STABILITY] 增强了 Select2 下拉框的点击稳定性。
# 4. [LOGIC] 保持收件人兜底逻辑及飞书 Batch-POST 同步。
# =========================================================

def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d]: %(message)s')
    logger = logging.getLogger("DmallFinalFix")
    logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    info_handler = TimedRotatingFileHandler(os.path.join(log_dir, "operation_detail.log"), when="midnight", interval=1, backupCount=30, encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(info_handler)
    return logger

log = setup_logger()
load_dotenv("_env")

class FeishuClient:
    def __init__(self):
        self.app_token = os.getenv("BITABLE_APP_TOKEN")
        self.table_id = os.getenv("BITABLE_TABLE_ID")
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.token = self._get_token()

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}).json()
            return res.get("tenant_access_token") if res.get("code") == 0 else None
        except: return None

    def get_record_id(self, ticket_no):
        if not self.token: return None
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/search"
        try:
            res = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, 
                                json={"filter": {"conjunction": "and", "conditions": [{"field_name": "Ticket No", "operator": "contains", "value": [str(ticket_no)]}]}}).json()
            items = res.get("data", {}).get("items", [])
            return items[0].get("record_id") if items else None
        except: return None

    def upsert_record(self, fields, record_id=None):
        if not self.token: return
        if record_id:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/batch_update"
            payload = {"records": [{"record_id": record_id, "fields": fields}]}
            action = "UPDATE"
        else:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"
            payload = {"fields": fields}
            action = "INSERT"

        try:
            response = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json=payload, timeout=15)
            res_data = response.json()
            if res_data.get("code") == 0:
                log.info(f"✅ 飞书同步成功 ({action}): {fields['Ticket No']['text']}")
            else:
                log.error(f"❌ 飞书同步报错: {res_data.get('msg')}")
        except Exception as e:
            log.error(f"❌ 飞书通讯异常: {e}")

PRIORITY_MAP = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}

def parse_sdp_date(date_str):
    try:
        dt = datetime.strptime(" ".join(date_str.split()), "%b %d, %Y %I:%M %p")
        return int(dt.timestamp() * 1000)
    except: return int(datetime.now().timestamp() * 1000)

async def run_automation():
    async with async_playwright() as p:
        log.info("🚀 [V6.3.3] 启动修复后的全自动流程...")
        auth_file = "auth.json"
        feishu = FeishuClient()
        
        browser = await p.chromium.launch(headless=False) 
        context = await browser.new_context(storage_state=auth_file) if os.path.exists(auth_file) else await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(60000)
        base_url = os.getenv("SDP_BASE_URL")

        try:
            log.info("🌐 正在访问 SDP 列表...")
            await page.goto(base_url + "/app/itdesk/ui/requests", wait_until="domcontentloaded")
            
            try:
                target = await page.wait_for_selector("#searchReq, .requestlistview_header, #userNameInput", timeout=20000)
                if await target.get_attribute("id") == "userNameInput":
                    await page.locator("#userNameInput").fill(os.getenv("SDP_USERNAME"))
                    await page.locator("#passwordInput").fill(os.getenv("SDP_PASSWORD"))
                    await page.locator("#submitButton").click()
                    await page.wait_for_timeout(10000)
                    await context.storage_state(path=auth_file)
            except: pass

            # --- 筛选逻辑 ---
            try:
                await page.get_by_role("button", name="FRG ITS - Dmall").first.click(); await page.wait_for_timeout(6000)
                sort_h = page.locator('th[data-column-index="7"]').first
                await sort_h.click(force=True); await page.wait_for_timeout(4000)
                await sort_h.click(force=True); await page.wait_for_timeout(5000)
                await page.locator('span[data-sdp-table-id="search-btn"]').first.click(); await page.wait_for_timeout(3000)
                await page.locator('div[data-search-field-name="status"] input').first.fill("Assigned")
                await page.locator(".sdp-table-search-go button").first.click(); await page.wait_for_timeout(10000)
            except: pass

            # --- 抓取逻辑 ---
            tickets = await page.evaluate(r"""() => {
                const results = [];
                const seenNo = new Set();
                const links = Array.from(document.querySelectorAll('a'))
                                   .filter(a => /\/app\/itdesk\/ui\/requests\/\d+\/details/.test(a.href));
                links.forEach(link => {
                    const row = link.closest('tr');
                    if (row) {
                        const cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                        const tNo = cells[4] || "N/A";
                        if (seenNo.has(tNo)) return;
                        const status = (cells[10] || "").toLowerCase();
                        const resp = cells[14] || "";
                        if (status.includes("assigned") && (!/\d/.test(resp) || resp === "-" || resp === "")) {
                            seenNo.add(tNo);
                            results.push({ no: tNo, subject: link.innerText.trim() || cells[5], priority: cells[9], date: cells[7], url: link.href });
                        }
                    }
                });
                return results;
            }""")

            log.info(f"📊 扫描完毕: 发现 {len(tickets)} 个唯一待处理工单")

            for t in tickets:
                log.info(f"--- 🛠️ 处理工单: {t['no']} ---")
                record_id = feishu.get_record_id(t['no'])
                
                try:
                    log.info(f"🔗 跳转详情页...")
                    await page.goto(t['url'], wait_until="domcontentloaded", timeout=60000)
                    
                    log.info("🖱️ 点击 'Reply All'...")
                    reply_btn = page.get_by_text("Reply All")
                    await reply_btn.wait_for(state="visible", timeout=30000)
                    await reply_btn.click()
                    await asyncio.sleep(5)
                    
                    log.info("🖱️ 激活模板选择下拉框...")
                    template_trigger = page.locator("span:has-text('Default Reply Template'), #template_selector_link").first
                    await template_trigger.click()
                    await asyncio.sleep(3) 

                    # --- 根据截图 HTML 修复的核心定位 ---
                    log.info("🖱️ 精准点击可见的模板选项 (.select2-result-label)...")
                    # 我们只点击类名为 select2-result-label 且文本匹配的 div，这会完美避开隐藏的 span
                    target_template = page.locator(".select2-result-label").filter(has_text="Default Reply Template").first
                    await target_template.wait_for(state="visible", timeout=5000)
                    await target_template.click()
                    
                    try: 
                        yes_btn = page.locator("button:has-text('Yes')")
                        if await yes_btn.is_visible(timeout=3000): await yes_btn.click()
                    except: pass
                    await asyncio.sleep(3)

                    # 收件人补全
                    to_input = page.locator("input#to")
                    if not (await to_input.input_value()):
                        log.info("⚠️ 补全收件人地址...")
                        await to_input.fill("smm.its.pos@smmarkets.com.ph")
                    
                    log.info("🚀 发送 Acknowledge...")
                    await page.locator("button:has-text('Send')").first.click()
                    log.info(f"✅ 邮件处理成功")
                    await page.wait_for_timeout(4000)
                    
                except Exception as e:
                    log.error(f"❌ [SDP ERROR] 工单 {t['no']} 操作失败: {e}")
                
                # 飞书同步
                feishu_status = "Active Work In Progress" if record_id else "Following"
                fields = {
                    "Ticket No": {"text": t['no'], "link": t['url']}, 
                    "Subject": t['subject'], 
                    "Priority": PRIORITY_MAP.get(t['priority'], "P3"), 
                    "Create date": parse_sdp_date(t['date']), 
                    "Status": feishu_status
                }
                feishu.upsert_record(fields, record_id)

            log.info("🏁 任务流结束")

        finally:
            await browser.close()
            log.info("🔌 浏览器已关闭")

if __name__ == "__main__":
    asyncio.run(run_automation())
