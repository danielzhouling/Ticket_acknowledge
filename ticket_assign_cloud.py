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
# 版本号: v6.3.3_Final_Template_Fix_Cloud
# 变更点确认：
# 1. [CLOUD] 云端部署版本：headless=True，适配无GUI服务器环境
# 2. [CLOUD] 添加反检测参数：--disable-blink-features=AutomationControlled
# 3. [CLOUD] 添加安全参数：--no-sandbox, --disable-dev-shm-usage
# 4. 保留原版所有功能：模板选择、收件人兜底、飞书同步
# 5. 增加详细日志，便于排查问题
# =========================================================

def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d]: %(message)s')
    logger = logging.getLogger("DmallFinalFix")
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    info_handler = TimedRotatingFileHandler(os.path.join(log_dir, "operation_detail.log"), when="midnight", interval=1, backupCount=30, encoding="utf-8")
    info_handler.setLevel(logging.DEBUG)
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
        log.info(f"📡 [DEBUG] 获取飞书 token, url={url}")
        try:
            res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}).json()
            if res.get("code") == 0:
                log.info("📡 [DEBUG] 飞书 token 获取成功")
                return res.get("tenant_access_token")
            else:
                log.error(f"📡 [ERROR] 飞书 token 获取失败: {res}")
                return None
        except Exception as e:
            log.error(f"📡 [ERROR] 获取飞书 token 异常: {e}")
            return None

    def get_record_id(self, ticket_no):
        log.info(f"📡 [DEBUG] 查询飞书记录ID: {ticket_no}")
        if not self.token: return None
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/search"
        try:
            res = requests.post(url, headers={"Authorization": f"Bearer {self.token}"},
                                json={"filter": {"conjunction": "and", "conditions": [{"field_name": "Ticket No", "operator": "contains", "value": [str(ticket_no)]}]}}).json()
            items = res.get("data", {}).get("items", [])
            record_id = items[0].get("record_id") if items else None
            log.info(f"📡 [DEBUG] 飞书记录ID: {ticket_no} -> {record_id}")
            return record_id
        except Exception as e:
            log.error(f"📡 [ERROR] 查询飞书记录ID异常: {e}")
            return None

    def upsert_record(self, fields, record_id=None):
        log.info(f"📡 [DEBUG] 准备同步到飞书: {fields['Ticket No']['text']}, record_id={record_id}")
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
    log.info("="*50)
    log.info("🚀 [V6.3.3 Cloud] 启动修复后的全自动流程...")
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
        log.info(f"✅ [DEBUG] 浏览器上下文创建成功")

        page = await context.new_page()
        page.set_default_timeout(60000)
        log.info("✅ [DEBUG] 新页面创建成功")

        try:
            log.info(f"🌐 [DEBUG] 访问 SDP: {base_url}/app/itdesk/ui/requests")
            await page.goto(base_url + "/app/itdesk/ui/requests", wait_until="domcontentloaded")
            log.info("✅ [DEBUG] 页面加载完成")

            # 检查登录
            try:
                log.info("🔍 [DEBUG] 检查登录状态...")
                target = await page.wait_for_selector("#searchReq, .requestlistview_header, #userNameInput", timeout=20000)
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

            # 筛选逻辑
            try:
                log.info("🔄 [DEBUG] 点击 FRG ITS - Dmall 按钮...")
                await page.get_by_role("button", name="FRG ITS - Dmall").first.click(); await page.wait_for_timeout(6000)

                log.info("🔄 [DEBUG] 点击排序按钮...")
                sort_h = page.locator('th[data-column-index="7"]').first
                await sort_h.click(force=True); await page.wait_for_timeout(4000)
                await sort_h.click(force=True); await page.wait_for_timeout(5000)

                log.info("🔄 [DEBUG] 打开搜索面板...")
                await page.locator('span[data-sdp-table-id="search-btn"]').first.click(); await page.wait_for_timeout(3000)

                log.info("🔄 [DEBUG] 输入搜索条件: status=Assigned")
                await page.locator('div[data-search-field-name="status"] input').first.fill("Assigned")
                await page.locator(".sdp-table-search-go button").first.click(); await page.wait_for_timeout(10000)
                log.info("✅ [DEBUG] 搜索完成")
            except Exception as e:
                log.warning(f"⚠️ [WARNING] 筛选逻辑异常: {e}")

            # 抓取逻辑
            log.info("🔍 [DEBUG] 开始抓取工单数据...")
            tickets = await page.evaluate(r"""() => {
                const results = [];
                const seenNo = new Set();
                const links = Array.from(document.querySelectorAll('a'))
                                   .filter(a => /\/app\/itdesk\/ui\/requests\/\d+\/details/.test(a.href));
                console.log('Found links:', links.length);
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

            log.info(f"📊 [DEBUG] 扫描完毕: 发现 {len(tickets)} 个唯一待处理工单")
            if len(tickets) > 0:
                log.info(f"📋 [DEBUG] 工单列表: {tickets}")

            if len(tickets) == 0:
                log.warning("⚠️ [WARNING] 未发现任何 Assigned 状态的待处理工单")

            for t in tickets:
                log.info(f"--- 🛠️ 处理工单: {t['no']} ---")
                record_id = feishu.get_record_id(t['no'])
                log.info(f"📡 [DEBUG] 飞书记录ID: {record_id}")

                try:
                    log.info(f"🔗 [DEBUG] 跳转详情页: {t['url']}")
                    await page.goto(t['url'], wait_until="domcontentloaded", timeout=60000)
                    log.info("✅ [DEBUG] 详情页加载完成")

                    log.info("🖱️ [DEBUG] 点击 'Reply All'...")
                    reply_btn = page.get_by_text("Reply All")
                    await reply_btn.wait_for(state="visible", timeout=30000)
                    await reply_btn.click()
                    await asyncio.sleep(5)
                    log.info("✅ [DEBUG] Reply All 点击完成")

                    log.info("🖱️ [DEBUG] 激活模板选择下拉框...")
                    template_trigger = page.locator("span:has-text('Default Reply Template'), #template_selector_link").first
                    await template_trigger.click()
                    await asyncio.sleep(3)

                    log.info("🖱️ [DEBUG] 精准点击可见的模板选项 (.select2-result-label)...")
                    target_template = page.locator(".select2-result-label").filter(has_text="Default Reply Template").first
                    await target_template.wait_for(state="visible", timeout=5000)
                    await target_template.click()
                    log.info("✅ [DEBUG] 模板选择完成")

                    try:
                        yes_btn = page.locator("button:has-text('Yes')")
                        if await yes_btn.is_visible(timeout=3000):
                            await yes_btn.click()
                            log.info("✅ [DEBUG] 点击 Yes 确认")
                    except: pass
                    await asyncio.sleep(3)

                    # 收件人补全
                    log.info("📧 [DEBUG] 检查收件人地址...")
                    to_input = page.locator("input#to")
                    current_to = await to_input.input_value()
                    log.info(f"📧 [DEBUG] 当前收件人: '{current_to}'")
                    if not current_to:
                        log.info("⚠️ [DEBUG] 收件人为空，填充默认地址...")
                        await to_input.fill("smm.its.pos@smmarkets.com.ph")
                    else:
                        log.info("✅ [DEBUG] 收件人已存在")

                    log.info("🚀 [DEBUG] 点击 Send 按钮...")
                    await page.locator("button:has-text('Send')").first.click()
                    log.info(f"✅ 邮件处理成功: {t['no']}")
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
