import os
import time
import json
import urllib.parse
import requests
# 引入 SeleniumBase 高级过盾包
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

        # 5. 先在服务器详情页找 6 小时续期按钮（状态A）
        # （当前已在 SERVER_URL 页面；过期时本页只显示 "Serwer zawieszony" 无按钮；
        #  只有面板主页才有 PRZEDLUZ SERWER 二次确认流程）
        # 6. 判定波兰语与英语红框限制
        page_source = sb.get_page_source()
        # 增加了英文的报错关键词，防止英文面板误判
        keywords = ["Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny", "cannot extend", "recently", "next 6 hours"]
        is_limited = any(kw in page_source for kw in keywords)

        if is_limited:
            print("检测到红框限制提示：说明未到可续期时间。结束本次运行（不发送 Telegram 提醒）。")
            return

        # 7. 两种状态的续期按钮
        # 面板"按钮"是 div/span 模拟的（非 <button>），文本为波兰语。
        # 用 JS 按自身直接文本查找最深层可见元素并点击。
        # norm(): 小写 + NFD + 只保留 a-z/0-9/空格/逗号（Ł 等无分解形式的字母直接丢弃，
        # nbsp 转空格），彻底避开 NFC/NFD 编码差异，且 JS 内不使用任何 \u 转义。
        # 要查找的文本直接内嵌进 JS 源码（__WANT__/__EXCL__），execute_script 零参数调用。
        JS_FIND_TMPL = """
        (function() {
            function norm(s) {
                var t = s.toLowerCase().normalize('NFD');
                var out = '';
                for (var i = 0; i < t.length; i++) {
                    var c = t.charCodeAt(i);
                    if (c === 160) { out += ' '; continue; }
                    if ((c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c === 32 || c === 44) { out += t.charAt(i); }
                }
                return out.replace(/ +/g, ' ').trim();
            }
            function shown(elm) {
                var e = elm;
                while (e && e !== document.body) {
                    var cs = window.getComputedStyle(e);
                    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
                    e = e.parentElement;
                }
                return true;
            }
            var want = norm('__WANT__');
            var excl = '__EXCL__' ? norm('__EXCL__') : '';
            var els = document.querySelectorAll('body *');
            var best = null, bestKids = 1e9;
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                // 用 innerText（含子孙的渲染文本），防按钮文字被拆分到多个子元素
                var own = norm(el.innerText || '');
                if (!own) continue;
                if (own.indexOf(want) === -1) continue;
                if (excl && own.indexOf(excl) !== -1) continue;
                if (!shown(el)) continue;
                var kids = el.getElementsByTagName('*').length;
                if (kids < bestKids) { bestKids = kids; best = el; }
            }
            __ACTION__
        })()
        """

        def _click_btn(want, exclude='', timeout=20):
            """轮询查找并点击文本匹配的最深层可见元素。成功返回 True。"""
            js = (JS_FIND_TMPL
                  .replace('__WANT__', want)
                  .replace('__EXCL__', exclude)
                  .replace('__ACTION__',
                            "if (best) { best.click(); return 'CLICKED:' + best.tagName + '|' + "
                            "((best.innerText || best.textContent || '').trim().slice(0, 40)); } "
                            "return 'NOTFOUND';"))
            end = time.time() + timeout
            while time.time() < end:
                try:
                    res = sb.execute_script(js)
                except Exception as e:
                    print(f"JS 执行异常: {str(e)[:150]}")
                    res = 'JSERROR'
                if isinstance(res, str) and res.startswith('CLICKED:'):
                    print(f"已点击 -> {res}")
                    return True
                sb.sleep(2)
            print(f"超时未找到按钮: {want}")
            return False

        def _dump_buttons():
            """调试：打印含关键词的元素（标签 | 计算样式 | 自身文本），用于定位问题。"""
            try:
                info = sb.execute_script("""
                    var els = document.querySelectorAll('body *');
                    var out = ['frames=' + document.querySelectorAll('iframe').length];
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        var own = el.innerText || '';
                        if (/przed|dodaj/i.test(own)) {
                            var cs = window.getComputedStyle(el);
                            out.push(el.tagName + ' | display=' + cs.display +
                                ' | visibility=' + cs.visibility +
                                ' | text=' + JSON.stringify(own.trim().slice(0, 50)));
                        }
                    }
                    return out.join('\\n');
                """)
                print("---- 相关元素快照 ----")
                print(info or "(无匹配)")
                print("---- 快照结束 ----")
            except Exception as e:
                print(f"元素快照失败: {e}")

        try:
            state = None
            # 步骤1：服务器详情页 → 只找 6 小时按钮（状态A）
            print(f"当前页面 URL: {sb.get_current_url()}")
            print(f"页面标题: {sb.get_title()}")
            pl_server = sb.get_page_source().lower()
            if "zawieszony" in pl_server or "suspended" in pl_server:
                print("步骤1：服务器详情页显示已暂停，跳过本页检测，直接前往主页...")
            else:
                print("步骤1：在服务器详情页寻找 6 小时续期按钮...")
                if _click_btn('dodaj 6', timeout=20):
                    state = 'A'
                else:
                    print("步骤1 未找到按钮，打印详情页实际按钮快照：")
                    _dump_buttons()

            # 步骤2：面板主页 → 只找二次确认按钮（状态B）
            # （6 小时按钮只在服务详情页，主页没有）
            if state is None:
                print("步骤2：前往面板主页寻找二次确认续期按钮...")
                sb.open("https://dash.icehost.pl/")
                sb.sleep(5)
                if _click_btn('przedłuż serwer', exclude='potwierdź', timeout=25):
                    state = 'B'

            if state == 'A':
                # ---- 状态A：未过期，直接续 6 小时 ----
                # 点击后等待可能弹出的红框提示充分渲染
                sb.sleep(5)
                sb.save_screenshot("icehost_debug_screenshot.png")
                if any(kw in sb.get_page_source() for kw in keywords):
                    print("点击后页面弹出了限制提示：说明未到可续期时间。结束本次运行。")
                    return
                print("点击后未检测到报错红条，刷新页面确认续期结果...")
                sb.refresh()
                sb.sleep(5)
                sb.save_screenshot("icehost_debug_screenshot.png")
                if any(kw in sb.get_page_source() for kw in keywords):
                    msg = "⚡ <b>IceHost 服务器续期成功！</b>\n服务器已延长 6 小时有效期。"
                else:
                    msg = "ℹ️ <b>IceHost 续期指令已发送</b>\n按钮已点击，请检查截图确认是否成功。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")

            elif state == 'B':
                # ---- 状态B：已过期/暂停，需二次确认 ----
                sb.sleep(3)
                sb.save_screenshot("icehost_debug_screenshot.png")
                print("等待并点击确认弹窗 (TAK, ...)...")
                if not _click_btn('tak,', timeout=15):
                    _dump_buttons()
                    raise Exception("已点击续期按钮，但确认弹窗未出现")
                sb.sleep(5)
                sb.save_screenshot("icehost_debug_screenshot.png")
                print("刷新页面确认续期结果...")
                sb.refresh()
                sb.sleep(5)
                sb.save_screenshot("icehost_debug_screenshot.png")
                after = sb.get_page_source()
                recovered = "zawieszony" not in after.lower() and "suspended" not in after.lower()
                if recovered or any(kw in after for kw in keywords):
                    msg = "⚡ <b>IceHost 服务器续期成功！</b>\n过期服务器已确认延长，暂停状态解除。"
                else:
                    msg = "ℹ️ <b>IceHost 过期续期指令已发送</b>\n确认按钮已点击，请检查截图确认状态。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
            else:
                # 两种按钮都没找到：区分"无需续期"和"真正的异常"
                pl = sb.get_page_source().lower()
                if "zawieszony" in pl or "suspended" in pl:
                    _dump_buttons()
                    raise Exception("服务器已暂停但未找到续期按钮")
                elif "serwery" in pl:
                    print("✅ 服务器运行正常，暂无需续期。结束本次运行（不发送 TG 提醒）。")
                    return
                else:
                    _dump_buttons()
                    raise Exception("未找到任何续期按钮（页面可能未正常加载）")
        except Exception as e:
            sb.save_screenshot("icehost_debug_screenshot.png")
            print(f"续期流程异常: {e}")
            send_tg_notification("❌ <b>IceHost 续期异常！</b>\n未找到续期按钮或点击失败，请查看截图。",
                                 "icehost_debug_screenshot.png")

if __name__ == "__main__":
    run()
