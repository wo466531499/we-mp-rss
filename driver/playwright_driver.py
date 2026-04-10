from asyncio import futures
import os
import platform
import subprocess
import sys
import json
import random
import uuid
import asyncio
import threading
import warnings
import gc
from socket import timeout
from urllib.parse import urlparse, unquote

from core.print import print_error
from driver.user_agent import UserAgentGenerator
from driver.anti_crawler_config import AntiCrawlerConfig

# 过滤 Playwright 已知的 memoryview 缓冲区警告
# 这是 Playwright 在 Windows 上关闭浏览器时的已知问题
try:
    warnings.filterwarnings("ignore", category=ResourceWarning)
except Exception:
    pass

# 设置环境变量
browsers_name = os.getenv("BROWSER_TYPE", "firefox")
browsers_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "")
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browsers_path

# 导入Playwright相关模块
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright

class PlaywrightController:
    # 使用线程本地存储，每个线程拥有独立的 playwright 实例
    # 解决 greenlet "Cannot switch to a different thread" 错误
    _thread_local = threading.local()
    _global_lock = threading.Lock()
    
    # 每个线程的引用计数，用于正确清理资源
    _thread_ref_counts = {}

    def __init__(self):
        self.system = platform.system().lower()
        self.driver = None  # 指向线程本地的 playwright driver
        self.browser = None
        self.context = None
        self.page = None
        self.isClose = True
        self._anti_crawler = AntiCrawlerConfig()  # 反爬虫配置

    def _mask_proxy_url(self, proxy_url: str) -> str:
        if not proxy_url:
            return ""
        parsed = urlparse(proxy_url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return f"{parsed.scheme}://***:***@{netloc}"
        return proxy_url

    def _build_proxy_options(self, proxy_url: str):
        if not proxy_url:
            return None

        parsed = urlparse(proxy_url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError(f"代理地址格式无效: {proxy_url}")

        server = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            server = f"{server}:{parsed.port}"

        proxy_options = {"server": server}
        if parsed.username:
            proxy_options["username"] = unquote(parsed.username)
        if parsed.password:
            proxy_options["password"] = unquote(parsed.password)
        return proxy_options

    def _is_browser_installed(self, browser_name):
        """检查指定浏览器是否已安装"""
        try:
            
            # 遍历目录，查找包含浏览器名称的目录
            for item in os.listdir(browsers_path):
                item_path = os.path.join(browsers_path, item)
                if os.path.isdir(item_path) and browser_name.lower() in item.lower():
                    return True
            
            return False
        except (OSError, PermissionError):
            return False
    def is_async(self):
        try:
            # 尝试获取事件循环
                # 设置合适的事件循环策略
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return True
        except RuntimeError:
            # 如果没有正在运行的事件循环，则说明不是异步环境
            return False
    
    def is_browser_started(self):
        """检测浏览器是否已启动"""
        return (not self.isClose and 
                self.driver is not None and 
                self.browser is not None and 
                self.context is not None and 
                self.page is not None)
    def start_browser(self, headless=True, mobile_mode=True, dis_image=True, browser_name=browsers_name, language="zh-CN", anti_crawler=True, proxy_url=""):
        try:
            if  str(os.getenv("NOT_HEADLESS",False))=="True":
                headless = False
            else:
                headless = True

            if self.system != "windows":
                headless = True
            
            # 使用线程本地存储，确保每个线程有独立的 playwright driver
            thread_id = threading.current_thread().ident
            
            with PlaywrightController._global_lock:
                # 检查当前线程是否已有 driver
                if not hasattr(PlaywrightController._thread_local, 'driver') or \
                   PlaywrightController._thread_local.driver is None:
                    if sys.platform == "win32":
                        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                    PlaywrightController._thread_local.driver = sync_playwright().start()
                    PlaywrightController._thread_ref_counts[thread_id] = 0
                    print(f"Playwright driver 已为线程 {thread_id} 初始化")
                
                PlaywrightController._thread_ref_counts[thread_id] = \
                    PlaywrightController._thread_ref_counts.get(thread_id, 0) + 1
            
            self.driver = PlaywrightController._thread_local.driver
        
            # 根据浏览器名称选择浏览器类型
            if browser_name.lower() == "firefox":
                browser_type = self.driver.firefox
            elif browser_name.lower() == "webkit":
                browser_type = self.driver.webkit
            else:
                browser_type = self.driver.chromium  # 默认使用chromium
            print(f"启动浏览器: {browser_name}, 无头模式: {headless}, 移动模式: {mobile_mode}, 反爬虫: {anti_crawler}")
            # 设置启动选项

            # 根据浏览器类型使用不同的参数
            launch_options = {
                "headless": headless
            }

            if browser_name.lower() == "chromium":
                # Chromium 浏览器参数（支持最丰富）
                launch_options["args"] = [
                    # "--disable-blink-features=AutomationControlled",  # 禁用自动化检测
                    # "--disable-web-security",  # 禁用同源策略（可选）
                    "--disable-features=IsolateOrigins,site-per-process",  # 禁用站点隔离
                    "--disable-webrtc",  # 禁用 WebRTC（防止真实 IP 泄露）
                    "--disable-extensions",  # 禁用扩展
                    "--disable-plugins",  # 禁用插件
                    "--disable-images",  # 禁用图片加载（可选，加速）
                    "--disable-background-networking",  # 禁用后台网络
                    "--disable-sync",  # 禁用同步
                    "--metrics-recording-only",  # 禁用指标记录
                    "--no-first-run",  # 跳过首次运行
                    "--disable-default-apps",  # 禁用默认应用
                    "--no-default-browser-check",  # 跳过默认浏览器检查
                    "--disable-dev-shm-usage",
                    "--disable-gpu",  # 可选：禁用GPU以统一渲染特征
                ]

            elif browser_name.lower() == "firefox":
                # Firefox 使用 firefox_user_prefs 配置，不是 args
                launch_options["firefox_user_prefs"] = {
                    # 禁用 WebDriver 检测
                    "dom.webdriver.enabled": False,
                    # 禁用 WebRTC（防止 IP 泄露）
                    "media.peerconnection.enabled": False,
                    "media.navigator.enabled": False,
                    # 禁用扩展
                    "extensions.autoDisableScopes": 15,
                    "xpinstall.signatures.required": False,
                    # 隐私保护
                    "privacy.trackingprotection.enabled": True,
                    "privacy.trackingprotection.pbmode.enabled": True,
                    # 禁用遥测
                    "toolkit.telemetry.enabled": False,
                    "datareporting.healthreport.uploadEnabled": False,
                    # 性能优化
                    "browser.cache.disk.enable": True,
                    "browser.sessionstore.enabled": True,
                }
                # Firefox 不使用 args 参数，但可以添加少量通用参数
                launch_options["args"] = []

            elif browser_name.lower() == "webkit":
                # WebKit 浏览器参数（支持很少，保持最小化）
                launch_options["args"] = []
                # WebKit 的反爬虫功能主要通过 JavaScript 注入实现
            else:
                # 默认使用 Chromium 配配置
                launch_options["args"] = [
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-webrtc",
                    "--disable-extensions",
                    "--disable-plugins",
                    "--disable-images",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--no-default-browser-check",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]

            proxy_options = self._build_proxy_options(proxy_url)
            if proxy_options:
                print(f"浏览器代理已启用: {self._mask_proxy_url(proxy_url)}")
                launch_options["proxy"] = proxy_options
            
            # 在Windows上添加额外的启动选项
            if self.system == "windows":
                launch_options["handle_sigint"] = False
                launch_options["handle_sigterm"] = False
                launch_options["handle_sighup"] = False
            
            self.browser = browser_type.launch(**launch_options)
            
            # 设置浏览器语言为中文
            context_options = {
                "locale": language
            }
            
            # 反爬虫配置
            if anti_crawler:
                context_options.update(self._anti_crawler.get_anti_crawler_config(mobile_mode))
            
            self.context = self.browser.new_context(**context_options) #type: ignore
            self.page = self.context.new_page()
            

            if dis_image:
                self.context.route("**/*.{png,jpg,jpeg}", lambda route: route.abort())

            # 应用反爬虫脚本
            if anti_crawler:
                self.page.add_init_script(self._anti_crawler.get_init_script())
                self.page.evaluate(self._anti_crawler.get_behavior_script())

            self.isClose = False
            return self.page
        except Exception as e:
            tips=f"{str(e)}\nDocker环境;您可以设置环境变量INSTALL=True并重启Docker自动安装浏览器环境;如需要切换浏览器可以设置环境变量BROWSER_TYPE=firefox 支持(firefox,webkit,chromium),开发环境请手工安装"
            print_error(tips)
            self.cleanup()
            raise Exception(tips)
        
    def string_to_json(self, json_string):
        try:
            json_obj = json.loads(json_string)
            return json_obj
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {e}")
            return ""

    def parse_string_to_dict(self, kv_str: str):
        result = {}
        items = kv_str.strip().split(';')
        for item in items:
            try:
                key, value = item.strip().split('=')
                result[key.strip()] = value.strip()
            except Exception as e:
                pass
        return result

    def add_cookies(self, cookies):
        if self.context is None:
            raise Exception("浏览器未启动，请先调用 start_browser()")
        self.context.add_cookies(cookies)
        
    def get_cookies(self):
        if self.context is None:
            raise Exception("浏览器未启动，请先调用 start_browser()")
        return self.context.cookies()
    
    def add_cookie(self, cookie):
        self.add_cookies([cookie])

    def __del__(self):
        # 析构时确保资源被释放
        try:
            self.Close()
        except Exception:
            # 析构函数中避免抛出异常
            pass

    def open_url(self, url, wait_until="domcontentloaded"):
        try:
            self.page.goto(url, wait_until=wait_until)
        except Exception as e:
            raise Exception(f"打开URL失败: {str(e)}")

    def Close(self):
        self.cleanup()

    def cleanup(self):
        """清理所有资源 - 每个步骤独立捕获异常"""
        import gc
        errors = []
        
        # 先清理实例级别的资源
        for name, obj in [('page', self.page), ('context', self.context), 
                           ('browser', self.browser)]:
            if obj:
                try:
                    # 添加小延迟，避免 memoryview 缓冲区问题
                    import time
                    time.sleep(0.1)
                    obj.close()
                except Exception as e:
                    errors.append(f"{name}: {e}")
        
        self.page = None
        self.context = None
        self.browser = None
        self.isClose = True
        
        # 强制垃圾回收，释放可能的内存缓冲区
        gc.collect()
        
        # 使用全局锁管理线程本地 driver 的生命周期
        thread_id = threading.current_thread().ident
        
        with PlaywrightController._global_lock:
            if thread_id in PlaywrightController._thread_ref_counts:
                PlaywrightController._thread_ref_counts[thread_id] -= 1
                
                # 只有当该线程的引用计数归零时才真正停止 driver
                if PlaywrightController._thread_ref_counts[thread_id] == 0:
                    if hasattr(PlaywrightController._thread_local, 'driver') and \
                       PlaywrightController._thread_local.driver is not None:
                        try:
                            import time
                            time.sleep(0.2)  # 延迟停止 driver
                            PlaywrightController._thread_local.driver.stop()
                            print(f"Playwright driver 已为线程 {thread_id} 停止")
                        except Exception as e:
                            errors.append(f"driver: {e}")
                        finally:
                            PlaywrightController._thread_local.driver = None
                    del PlaywrightController._thread_ref_counts[thread_id]
        
        self.driver = None
        # 再次强制垃圾回收
        gc.collect()
        
        if errors:
            print(f"资源清理部分失败: {errors}")

    def dict_to_json(self, data_dict):
        try:
            return json.dumps(data_dict, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            print(f"字典转JSON失败: {e}")
            return ""

# 示例用法
if __name__ == "__main__":
    controller = PlaywrightController()
    try:
        controller.start_browser()
        controller.open_url("https://mp.weixin.qq.com/")
    finally:
        # controller.Close()
        pass
