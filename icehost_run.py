import os
import time
import json
import urllib.parse
import requests
# 引入 SeleniumBase 高级过盾包！
from seleniumbase import SB

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")

def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("未配置 TG 机器人变量，跳过发送 TG 推送。")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
        print("TG 状态通知发送成功。")
    except Exception as e:
        print(f"发送 TG 消息异常: {e}")

    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": "IceHost 实时画面"}
                requests.post(url, data=data, files=files)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")

def run():
    if not SERVER_URL:
        print("错误: 缺少 ICEHOST_SERVER_URL 环境变量")
        return

    # 1. 启动 SeleniumBase 并开启 UC 免密/防检测模式与 Xvfb 虚拟桌面 (xvfb=True)
    with SB(uc=True, xvfb=True) as sb:
        print(f"正在访问 IceHost 面板: {SERVER_URL}")
        # 使用 UC 专属重连模式访问，能极大缓解首屏 Cloudflare 阻断
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=8)
        sb.sleep(5)

        # 2. 注入 Cookies（已升级：智能兼容 JSON 或纯文本格式）
        if ICEHOST_COOKIES:
            try:
                cookies_to_add = []
                raw_cookies_str = ICEHOST_COOKIES.strip()

                # 尝试一：如果 Secret 填的是标准的 JSON 格式
                try:
                    raw_data = json.loads(raw_cookies_str)
                    if isinstance(raw_data, list):
                        cookies_to_add = raw_data
                    elif isinstance(raw_data, dict):
                        cookies_to_add = raw_data.get("cookies", [])
                    print("检测到 JSON 格式 Cookie，正在解析...")

                # 尝试二：如果解析失败，说明填的是纯文本
                except json.JSONDecodeError:
                    print("检测到纯文本 Cookie 格式，正在自动提取并生成标准字段...")

                    # 提取真正的 Token 字符串值
                    token_value = raw_cookies_str
                    if "icehostpl_session=" in token_value:
                        token_value = token_value.split("icehostpl_session=")[1].split(";")[0]
                    elif "XSRF-TOKEN=" in token_value:
                        token_value = token_value.split("XSRF-TOKEN=")[1].split(";")[0]

                    token_value = token_value.strip()

                    # 最稳妥策略：自动为 Selenium 生成两个核心的 Cookie 字典
                    cookies_to_add = [
                        {"name": "icehostpl_session", "value": token_value, "domain": "dash.icehost.pl"},
                        {"name": "XSRF-TOKEN", "value": token_value, "domain": "dash.icehost.pl"}
                    ]

                # 统一执行转换与注入
                for c in cookies_to_add:
                    raw_value = c["value"]
                    decoded_value = urllib.parse.unquote(raw_value)

                    cookie_dict = {
                        "name": c["name"],
                        "value": decoded_value,
                        "domain": c.get("domain", "dash.icehost.pl"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True)
                    }
                    if "sameSite" in c:
                        ss = str(c["sameSite"]).lower()
                        if ss in ["lax", "strict", "none"]:
                            cookie_dict["sameSite"] = ss.capitalize()

                    sb.add_cookie(cookie_dict)

                print("Cookie 成功注入！")

                # 重新刷新加载，应用 Cookie
                sb.refresh()
                sb.sleep(5)
            except Exception as e:
                print(f"注入 Cookie 过程中发生异常，跳过: {e}")

        # 3. 核心过盾：自动寻找并执行系统级物理点击过 Cloudflare Turnstile 验证盾
        sb.save_screenshot("icehost_debug_screenshot.png")
        try:
            print("正在检测并调用系统级 PyAutoGUI 驱动，物理点击 Cloudflare 人机验证码...")
            # 在虚拟桌面上定位验证框并模拟发送系统硬件级点击事件
            sb.uc_gui_click_captcha()
            sb.sleep(10) # 给予 10 秒跳转缓冲
            sb.save_screenshot("icehost_debug_screenshot.png")
        except Exception as e:
            print(f"验证盾已被跳过或点击执行完毕: {e}")

        # 4. 判断登录状态
        current_url = sb.get_current_url()
        # 判断是否停留在登录页
        if "login" in current_url or sb.is_element_visible("input[type='email']"):
            msg = "❌ <b>IceHost 登录失效！</b>\n请在浏览器重新提取并更新 ICEHOST_COOKIES。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            return

        # 5. 续期逻辑（极简版）
        # 详情页：6小时按钮（未过期则点）/ 显示已暂停（过期）→ 去主页
        # 主页：PRZEDLUZ SERWER 二次确认（仅过期时有）
        import unicodedata

        def _norm(s):
            t = unicodedata.normalize('NFD', (s or '').lower())
            return ''.join(c for c in t if c.isascii() and (c.isalnum() or c in ' ,'))

        def _body_text():
            try:
                raw = sb.execute_script("(function(){return document.body ? document.body.textContent : '';})()")
            except Exception:
                raw = ''
            return _norm(raw)

        def _has_limit():
            t = _body_text()
            kws = ['nie mozesz przedluzyc', 'niedawno to zrobiles', 'kolejne 6 godziny',
                   'cannot extend', 'recently', 'next 6 hours']
            return any(kw in t for kw in kws)

        def _click_btn(want, exclude='', timeout=20):
            js = """(function(){
                function norm(s){
                    var t=(s||'').toLowerCase().normalize('NFD'),o='';
                    for(var i=0;i<t.length;i++){var c=t.charCodeAt(i);
                        if(c===160){o+=' ';continue;}
                        if((c>=97&&c<=122)||(c>=48&&c<=57)||c===32||c===44)o+=t.charAt(i);}
                    return o.replace(/ +/g,' ').trim();
                }
                var want=norm('__WANT__'),excl='__EXCL__'?norm('__EXCL__'):'';
                var els=document.querySelectorAll('button,a,[role="button"]');
                for(var i=0;i<els.length;i++){
                    var el=els[i];
                    if(el.offsetParent===null&&getComputedStyle(el).position!=='fixed')continue;
                    var txt=norm(el.textContent||'');
                    if(txt.indexOf(want)===-1)continue;
                    if(excl&&txt.indexOf(excl)!==-1)continue;
                    el.click();
                    return 'CLICKED:'+el.tagName;
                }
                return 'NOTFOUND';
            })()""".replace('__WANT__', want).replace('__EXCL__', exclude)
            end = time.time() + timeout
            while time.time() < end:
                try:
                    res = sb.execute_script(js)
                except Exception as e:
                    print(f"JS 异常: {str(e)[:100]}")
                    res = ''
                if isinstance(res, str) and res.startswith('CLICKED:'):
                    print(f"已点击 -> {res}")
                    return True
                sb.sleep(2)
            print(f"超时未找到按钮: {want}")
            return False

        try:
            print(f"当前页面: {sb.get_current_url()}")
            # 先等服务器卡片数据渲染出来（DATA WAŻNOŚCI），最多 30 秒；
            # 若一直不出现则刷新重试一次，避免在空白页上空找按钮
            def _card_ready():
                t = _body_text()
                return ('waznosci' in t) or ('serwer' in t and 'running' in t) or ('zawieszony' in t)
            ready = False
            for _ in range(15):
                if _card_ready():
                    ready = True
                    break
                sb.sleep(2)
            if not ready:
                print("卡片数据未加载，刷新重试一次...")
                sb.refresh()
                sb.sleep(8)
                for _ in range(15):
                    if _card_ready():
                        ready = True
                        break
                    sb.sleep(2)
            print(f"卡片加载状态: {'OK' if ready else '仍未加载，继续尝试'}")
            if _has_limit():
                print("检测到限制提示：未到可续期时间，静默退出（不发 TG）。")
                return
            body = _body_text()
            if 'zawieszony' in body or 'suspended' in body:
                print("详情页显示已暂停，转去主页走二次确认流程...")
            else:
                print("在详情页找 6 小时按钮...")
                if _click_btn('dodaj 6', timeout=20):
                    sb.sleep(5)
                    sb.save_screenshot("icehost_debug_screenshot.png")
                    if _has_limit():
                        print("点击后出现限制提示：未到可续期时间，静默退出。")
                        return
                    print("刷新确认续期结果...")
                    sb.refresh()
                    sb.sleep(5)
                    sb.save_screenshot("icehost_debug_screenshot.png")
                    msg = "&#9889; <b>IceHost 服务器续期成功！</b>\n服务器已延长 6 小时有效期。"
                    print(msg)
                    send_tg_notification(msg, "icehost_debug_screenshot.png")
                    return
                print("详情页未找到 6 小时按钮，转去主页检查...")

            sb.open("https://dash.icehost.pl/")
            sb.sleep(5)
            if _click_btn('przedluz serwer', exclude='potwierdz', timeout=25):
                print("等待确认弹窗...")
                sb.sleep(3)
                sb.save_screenshot("icehost_debug_screenshot.png")
                if not _click_btn('tak,', timeout=15):
                    raise Exception("已点续期但确认弹窗未出现")
                sb.sleep(5)
                sb.refresh()
                sb.sleep(5)
                sb.save_screenshot("icehost_debug_screenshot.png")
                after = _body_text()
                if 'zawieszony' not in after and 'suspended' not in after:
                    msg = "&#9889; <b>IceHost 服务器续期成功！</b>\n过期服务器已确认延长，暂停状态解除。"
                else:
                    msg = "&#8505;&#65039; <b>IceHost 续期指令已发送</b>\n请检查截图确认状态。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
                return

            if 'zawieszony' in _body_text() or 'suspended' in _body_text():
                raise Exception("服务器已暂停但主页未找到续期按钮")
            print("&#9989; 服务器运行正常，暂无需续期。静默退出（不发 TG）。")
            return
        except Exception as e:
            sb.save_screenshot("icehost_debug_screenshot.png")
            print(f"续期流程异常: {e}")
            send_tg_notification("❌ <b>IceHost 续期异常！</b>\n未找到续期按钮或点击失败，请查看截图。",
                                 "icehost_debug_screenshot.png")

if __name__ == "__main__":
    run()
