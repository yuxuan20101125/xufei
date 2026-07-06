import os
import sys
import asyncio
import requests
import random
import json
import logging
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- 环境变量配置 ---
DP_EMAIL = os.getenv("DP_EMAIL", "").strip()
DP_PASSWORD = os.getenv("DP_PASSWORD", "").strip()
SOCKS5_PROXY = os.getenv("SOCKS5_PROXY", "").strip()

# 通知配置 (Bark & Telegram)
BARK_KEY = os.getenv("BARK_KEY", "").strip()
BARK_SERVER = os.getenv("BARK_SERVER", "https://api.day.app").rstrip("/")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

# --- 常量定义 ---
LOGIN_URL = "https://dash.domain.digitalplat.org/auth/login"
DOMAINS_URL = "https://dash.domain.digitalplat.org/panel/main?page=%2Fpanel%2Fdomains"
TIMEOUTS = {
    "page_load": 60000,
    "element_wait": 30000,
    "navigation": 60000,
    "login_wait": 180000,
    "notify_req": 10
}
SCREENSHOT_DIR = "./screenshot_log"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def validate_config():
    """检查必要的登录凭据"""
    if not DP_EMAIL or not DP_PASSWORD:
        err_msg = "配置错误: 缺少 DP_EMAIL 或 DP_PASSWORD 环境变量"
        logger.error(err_msg)
        send_notification("DigitalPlat 配置错误", "缺少必要登录环境变量，脚本终止")
        sys.exit(1)

def send_notification(title, body, level="active"):
    """同步通知，仅使用requests，无httpx依赖"""
    logger.info(f"发送通知 | {title}")
    # Bark推送
    if BARK_KEY:
        try:
            bark_payload = {
                "title": title,
                "body": body,
                "group": "DigitalPlat Renew",
                "level": level
            }
            requests.post(f"{BARK_SERVER}/{BARK_KEY}", json=bark_payload, timeout=TIMEOUTS["notify_req"])
        except Exception as e:
            logger.error(f"Bark通知失败: {str(e)}")
    # Telegram推送
    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            tg_text = f"*{title}*\n\n{body}"
            tg_payload = {
                "chat_id": TG_CHAT_ID,
                "text": tg_text,
                "parse_mode": "Markdown"
            }
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json=tg_payload,
                timeout=TIMEOUTS["notify_req"]
            )
        except Exception as e:
            logger.error(f"TG通知失败: {str(e)}")

def save_results(renewed_domains, failed_domains):
    results = {
        "timestamp": datetime.now().isoformat(),
        "renewed_count": len(renewed_domains),
        "failed_count": len(failed_domains),
        "renewed_domains": renewed_domains,
        "failed_domains": failed_domains
    }
    try:
        with open("renewal_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info("续期结果已保存至 renewal_results.json")
    except Exception as e:
        logger.error(f"保存结果文件失败: {e}")

async def random_sleep(min_s=1, max_s=4):
    await asyncio.sleep(random.uniform(min_s, max_s))

async def simulate_human_behavior(page):
    await page.mouse.move(random.randint(50, 1200), random.randint(50, 800))
    await random_sleep(0.2, 1)
    if random.random() > 0.6:
        await page.evaluate("window.scrollBy(0, Math.random() * 300)")
        await random_sleep(0.3, 1)

async def take_error_screenshot(page, label: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOT_DIR, f"{label}_{ts}.png")
    await page.screenshot(path=path, full_page=True)
    logger.warning(f"错误截图已保存: {path}")
    return path

async def setup_browser(playwright):
    # Chromium启动参数
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--headless=new',
            '--disable-software-rasterizer',
            '--single-process',
            '--disable-plugins',
            '--disable-extensions',
            '--window-size=1920,1080',
            '--mute-audio',
            '--exclude-switches=enable-automation',
            '--disable-features=IsolateOrigins,site-per-process'
        ]
    )
    # 代理配置：读取VLESS转出来的本地socks5
    context_args = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1"
        }
    }
    # 存在VLESS代理则启用socks5
    if SOCKS5_PROXY:
        context_args["proxy"] = {"server": SOCKS5_PROXY}
        logger.info(f"浏览器已启用VLESS转换代理: {SOCKS5_PROXY}

    context = await browser.new_context(**context_args)
    # 反爬脚本规避CF检测
    anti_detect_script = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    window.chrome = { runtime: {} };
    """
    await context.add_init_script(anti_detect_script)
    return browser, context

async def login(page):
    logger.info("=== 启动登录流程 ===")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=TIMEOUTS["page_load"])
    await simulate_human_behavior(page)

    # 循环等待CF验证自动放行
    wait_total = 0
    wait_step = 5000
    max_wait = TIMEOUTS["login_wait"]
    email_input = None
    while wait_total < max_wait:
        try:
            email_input = page.locator("input[name='email']")
            await email_input.wait_for(timeout=wait_step)
            break
        except PlaywrightTimeoutError:
            wait_total += wait_step
            logger.info(f"检测到Cloudflare验证，持续等待...已等待{wait_total / 1000}秒")
            await page.wait_for_timeout(wait_step)
            continue
    else:
        await take_error_screenshot(page, "login_cf_timeout")
        err_msg = f"登录超时：{max_wait / 1000}秒未自动通过Cloudflare人机验证"
        logger.error(err_msg)
        send_notification("DigitalPlat 登录失败", err_msg)
        raise Exception(err_msg)

    # 模拟人工输入账号密码
    await email_input.type(DP_EMAIL, delay=random.randint(40, 160))
    await random_sleep()
    pass_input = page.locator("input[name='password']")
    await pass_input.type(DP_PASSWORD, delay=random.randint(40, 160))
    await random_sleep(0.5, 1.2)

    # 提交登录表单
    submit_btn = page.locator("button[type='submit']")
    async with page.expect_navigation(wait_until="networkidle", timeout=TIMEOUTS["navigation"]):
        await submit_btn.click()

    await random_sleep(1, 2)
    if "/panel/main" not in page.url:
        await take_error_screenshot(page, "login_failed_redirect")
        err_msg = "登录提交后未跳转仪表盘，账号密码错误或被验证拦截"
        logger.error(err_msg)
        send_notification("DigitalPlat 登录失败", err_msg)
        raise Exception(err_msg)

    await page.wait_for_selector("#sidebar", timeout=TIMEOUTS["element_wait"])
    logger.info("✅ 账号登录成功")

async def process_single_domain(page, domain_name, domain_path, base_url):
    domain_label = f"[{domain_name}]"
    try:
        full_url = base_url + domain_path
        logger.info(f"{domain_label} 进入域名详情页: {full_url}")
        await page.goto(full_url, wait_until="networkidle", timeout=TIMEOUTS["navigation"])
        await simulate_human_behavior(page)

        renew_link = page.locator("a[href*='renewdomain']")
        if await renew_link.count() == 0:
            logger.info(f"{domain_label} 无续期入口，跳过")
            return (None, None)

        logger.info(f"{domain_label} 检测到续期链接，执行续期流程")
        async with page.expect_navigation(timeout=TIMEOUTS["navigation"]):
            await renew_link.click()
        await random_sleep()

        order_btn = page.locator("button:has-text('Order Now'), button:has-text('Continue'), button:has-text('Proceed')").first
        if await order_btn.count() == 0:
            return (False, f"{domain_name}: 页面无下单/继续按钮")
        async with page.expect_navigation(timeout=TIMEOUTS["navigation"]):
            await order_btn.click()
        await random_sleep()

        tos_check = page.locator("input[name='accepttos']")
        if await tos_check.count() > 0 and not await tos_check.is_checked():
            await tos_check.check()
            await random_sleep(0.3, 0.8)

        checkout_btn = page.locator("button#checkout, button:has-text('Checkout')")
        if await checkout_btn.count() == 0:
            return (False, f"{domain_name}: 找不到结账按钮")
        async with page.expect_navigation(timeout=TIMEOUTS["navigation"]):
            await checkout_btn.click()
        await random_sleep(1, 2)

        page_text = (await page.inner_text("body")).lower()
        success_keywords = ["order confirmation", "successfully", "renew complete", "paid"]
        fail_keywords = ["insufficient balance", "error", "failed", "invalid payment"]
        has_success = any(k in page_text for k in success_keywords)
        has_fail = any(k in page_text for k in fail_keywords)

        if has_success:
            logger.info(f"{domain_label} ✅ 续期订单确认成功")
            return (True, None)
        elif has_fail:
            err = f"{domain_name}: 订单失败，页面提示余额/支付异常"
            logger.error(f"{domain_label} {err}")
            await take_error_screenshot(page, f"renew_fail_{domain_name}")
            return (False, err)
        else:
            err = f"{domain_name}: 页面无成功标识，无法确认续期结果"
            await take_error_screenshot(page, f"renew_unknown_{domain_name}")
            return (False, err)

    except Exception as e:
        err_msg = f"{domain_name}: 处理异常 {str(e)}"
        logger.error(f"{domain_label} {err_msg}", exc_info=True)
        await take_error_screenshot(page, f"domain_err_{domain_name}")
        return (False, err_msg)

async def fetch_all_domains(page) -> list:
    domain_list = []
    await page.goto(DOMAINS_URL, wait_until="networkidle", timeout=TIMEOUTS["page_load"])
    await page.wait_for_selector("table.table-domains tbody tr", timeout=TIMEOUTS["element_wait"])
    await simulate_human_behavior(page)

    all_rows = await page.locator("table.table-domains tbody tr").all()
    logger.info(f"当前域名列表页面共检测到 {len(all_rows)} 行")

    for row in all_rows:
        try:
            onclick_attr = await row.get_attribute("onclick")
            if not onclick_attr or "'" not in onclick_attr:
                continue
            path = onclick_attr.split("'")[1]
            if not path.startswith("/panel"):
                continue
            domain_name = (await row.locator("td:nth-child(1)").inner_text()).strip()
            if not domain_name:
                continue
            domain_list.append((domain_name, path))
        except Exception as e:
            logger.warning(f"解析表格单行失败，跳过该行: {str(e)}")
            continue
    logger.info(f"过滤有效域名总数: {len(domain_list)}")
    return domain_list

async def main():
    validate_config()
    renewed_domains = []
    failed_domains = []
    browser = None

    async with async_playwright() as p:
        try:
            # 浏览器启动重试2次，规避偶发闪退
            retry_count = 0
            while retry_count < 2:
                try:
                    browser, context = await setup_browser(p)
                    break
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"浏览器启动失败，第{retry_count}次重试: {e}")
                    await asyncio.sleep(3)
            else:
                raise Exception("浏览器连续2次启动失败，终止运行")

            page = await context.new_page()
            base_domain_url = "https://dash.domain.digitalplat.org/"

            await login(page)
            domain_items = await fetch_all_domains(page)

            for domain_name, domain_path in domain_items:
                success, err_info = await process_single_domain(page, domain_name, domain_path, base_domain_url)
                if success is True:
                    renewed_domains.append(domain_name)
                elif err_info is not None:
                    failed_domains.append(err_info)

                await random_sleep(1, 3)
                await page.goto(DOMAINS_URL, wait_until="networkidle", timeout=TIMEOUTS["page_load"])

            if renewed_domains or failed_domains:
                msg_parts = []
                if renewed_domains:
                    msg_parts.append(f"✅ 续期成功({len(renewed_domains)}):\n" + "\n".join(renewed_domains))
                if failed_domains:
                    msg_parts.append(f"❌ 处理失败({len(failed_domains)}):\n" + "\n".join(failed_domains))
                full_msg = "\n\n".join(msg_parts)
                send_notification("DigitalPlat 域名续期汇总报告", full_msg)
            else:
                send_notification("DigitalPlat 域名检查完成", "所有域名无需续期，状态正常", level="passive")

            save_results(renewed_domains, failed_domains)
            logger.info("脚本全部流程执行完毕")

        except Exception as global_err:
            logger.critical(f"脚本全局致命错误: {str(global_err)}", exc_info=True)
            send_notification("DigitalPlat 脚本运行崩溃", f"全局异常：{str(global_err)}")
        finally:
            if browser is not None:
                logger.info("关闭浏览器进程")
                await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
