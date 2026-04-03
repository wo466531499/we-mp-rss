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
    def start_browser(self, headless=True, mobile_mode=False, dis_image=True, browser_name=browsers_name, language="zh-CN", anti_crawler=True, proxy_url=""):
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
            if browser_name.lower() == "webkit":
                # Webkit 浏览器参数（更保守，只支持少数参数）
                base_args = [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            else:
                # Chromium/Firefox 浏览器参数（功能更丰富）
                base_args = [
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
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",  # 可选：禁用GPU以统一渲染特征
                ]

            launch_options = {
                "headless": headless,
                "args": base_args
            }

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
                context_options.update(self._get_anti_crawler_config(mobile_mode))
            
            self.context = self.browser.new_context(**context_options) #type: ignore
            self.page = self.context.new_page()
            
            if mobile_mode:
                self.page.set_viewport_size({"width": 375, "height": 812})
            # else:
            #     self.page.set_viewport_size({"width": 1920, "height": 1080})

            if dis_image:
                self.context.route("**/*.{png,jpg,jpeg}", lambda route: route.abort())

            # 应用反爬虫脚本
            if anti_crawler:
                self._apply_anti_crawler_scripts()

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


    def _get_anti_crawler_config(self, mobile_mode=False):
        """获取反爬虫配置"""
        
        # 生成随机指纹
        fingerprint = self._generate_uuid()
        
        # 基础配置
        config = {
            "user_agent": self._get_realistic_user_agent(mobile_mode),
            "viewport": {
                "width": random.randint(1200, 1920) if not mobile_mode else 375,
                "height": random.randint(800, 1080) if not mobile_mode else 812,
                "device_scale_factor": random.choice([1, 1.25, 1.5, 2])
            },
            # 禁用用户特征
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "bypass_csp": True,  # 绕过 CSP 限制
            "extra_http_headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Cache-Control": "no-cache",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                # 禁用 Client Hints（移除特征头）
                # "Sec-CH-UA": None,  # User-Agent Client Hints
                # "Sec-CH-UA-Mobile": None,
                # "Sec-CH-UA-Platform": None,
            },
            # 禁用 WebRTC（通过权限）
            "permissions": [],  # 不授予任何权限
        }
        
        # 移动端特殊配置
        if mobile_mode:
            config["extra_http_headers"].update({
                "User-Agent": config["user_agent"],
                "X-Requested-With": "com.tencent.mm"
            })
        
        return config

    def _get_realistic_user_agent(self, mobile_mode=False):
        """获取更真实的User-Agent"""
        print(f"浏览器特征设置完成: {'移动端' if mobile_mode else '桌面端'}")
        if mobile_mode:
            # 移动端User-Agent
            mobile_agents = [
                "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
                "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
                "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
                "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36 Edge/14.14393"
            ]
            return random.choice(mobile_agents)
        else:
            # 桌面端User-Agent（更新版本）
            desktop_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            return random.choice(desktop_agents)

    def _generate_uuid(self):
        """生成UUID指纹"""
        return str(uuid.uuid4()).replace("-", "")

    def _apply_anti_crawler_scripts(self):
        """应用反爬虫脚本 - 禁用用户特征"""
        # 隐藏自动化特征和禁用指纹
        self.page.add_init_script("""
        // ========== 禁用 WebDriver 检测 ==========
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        
        // ========== 禁用 Chrome 自动化标志 ==========
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' }
                ];
                plugins.item = (i) => plugins[i] || null;
                plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
                plugins.refresh = () => {};
                return plugins;
            }
        });
        
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en']
        });
        
        // ========== 禁用 WebRTC（防止 IP 泄露）==========
        if (window.RTCPeerConnection) {
            window.RTCPeerConnection = undefined;
        }
        if (window.webkitRTCPeerConnection) {
            window.webkitRTCPeerConnection = undefined;
        }
        
        // ========== 禁用 Canvas 指纹 ==========
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png' && this.width === 220 && this.height === 30) {
                // 检测到指纹采集，返回空白
                return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
            }
            // 添加随机噪声
            const context = this.getContext('2d');
            if (context) {
                const imageData = context.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    imageData.data[i] ^= (Math.random() * 2) | 0;
                }
                context.putImageData(imageData, 0, 0);
            }
            return originalToDataURL.apply(this, arguments);
        };
        
        // ========== 禁用 AudioContext 指纹 ==========
        const audioContext = window.AudioContext || window.webkitAudioContext;
        if (audioContext) {
            const originalCreateAnalyser = audioContext.prototype.createAnalyser;
            audioContext.prototype.createAnalyser = function() {
                const analyser = originalCreateAnalyser.apply(this, arguments);
                const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                analyser.getFloatFrequencyData = function(array) {
                    // 返回随机噪声而非真实音频指纹
                    for (let i = 0; i < array.length; i++) {
                        array[i] = -100 + Math.random() * 50;
                    }
                };
                return analyser;
            };
        }
        
        // ========== 禁用 WebGL 指纹 ==========
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';  // UNMASKED_VENDOR_WEBGL
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
            return getParameter.apply(this, arguments);
        };
        
        if (typeof WebGL2RenderingContext !== 'undefined') {
            const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter2.apply(this, arguments);
            };
        }
        
        // ========== 禁用字体指纹 ==========
        const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
        CanvasRenderingContext2D.prototype.measureText = function(text) {
            const result = originalMeasureText.apply(this, arguments);
            // 添加微小随机偏移
            result.width += Math.random() * 0.1 - 0.05;
            return result;
        };
        
        // ========== 修改 permissions API ==========
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // ========== 禁用 Battery API ==========
        if (navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1
            });
        }
        
        // ========== 禁用 Network Information API ==========
        if (navigator.connection) {
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    downlink: 10,
                    rtt: 50,
                    saveData: false
                })
            });
        }
        
        // ========== 隐藏自动化框架痕迹 ==========
        delete window.__playwright;
        delete window.__puppeteer;
        delete window.__selenium;
        delete window.__webdriver_evaluate;
        delete window.__selenium_evaluate;
        delete window.__fxdriver_evaluate;
        delete window.__driver_unwrapped;
        delete window.__webdriver_unwrapped;
        delete window.__selenium_unwrapped;
        delete window.__fxdriver_unwrapped;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        
        console.log('[反检测] 用户特征保护已启用');
        """)#type: ignore
      
        # 设置更真实的浏览器行为
        self.page.evaluate("""
        // 随机延迟点击事件
        const originalAddEventListener = EventTarget.prototype.addEventListener;
        EventTarget.prototype.addEventListener = function(type, listener, options) {
            if (type === 'click') {
                const wrappedListener = function(...args) {
                    setTimeout(() => listener.apply(this, args), Math.random() * 100 + 50);
                };
                return originalAddEventListener.call(this, type, wrappedListener, options);
            }
            return originalAddEventListener.call(this, type, listener, options);
        };
        
        // 随机化鼠标移动
        document.addEventListener('mousemove', (e) => {
            if (Math.random() > 0.7) {
                e.stopImmediatePropagation();
            }
        }, true);
        """) #type: ignore

       

   

    def __del__(self):
        # 析构时确保资源被释放
        try:
            self.Close()
        except Exception:
            # 析构函数中避免抛出异常
            pass

    def open_url(self, url,wait_until="domcontentloaded"):
        try:
            self.page.goto(url,wait_until=wait_until)
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
