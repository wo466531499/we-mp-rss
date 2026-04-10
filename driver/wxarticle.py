"""
Async WX Article Fetcher - 完全异步版本
"""
import random
import time
import base64
import re
import os
from datetime import datetime
from typing import Dict
from bs4 import BeautifulSoup

from .playwright_driver import PlaywrightController
from core.print import print_error, print_info, print_success, print_warning
from core.config import cfg


class WXArticleFetcher:
    """
    异步微信公众号文章获取器
    
    完全基于 async/await,与 FastAPI 完美兼容
    """
    
    def __init__(self, wait_timeout: int = 10000):
        """初始化文章获取器"""
        self.wait_timeout = wait_timeout
        self.controller = PlaywrightController()
        self.browser_proxy_url = ""
        
        if cfg.get("proxy.enabled", False):
            self.browser_proxy_url = cfg.get("proxy.http_url", "")
            
    async def get_article_content(self, url: str) -> Dict:
        """
        获取文章内容(异步)
        
        Args:
            url: 文章URL
            
        Returns:
            文章信息字典
        """
        try:
            # 使用异步上下文管理器
            async with PlaywrightController(
                proxy_url=self.browser_proxy_url,
                mobile_mode=True
            ) as controller:
                
                # 打开URL
                success = await controller.open_url(url, timeout=self.wait_timeout)
                if not success:
                    raise Exception("页面加载失败")
                    
                page = controller.page
                
                # 等待页面加载
                await asyncio.sleep(2)
                
                # 获取页面内容
                body = await page.content()
                
                # 检查是否被删除
                if "该内容已被发布者删除" in body:
                    raise Exception("违规无法查看")
                    
                # 处理"轻触阅读原文"按钮
                if "轻触阅读原文" in body:
                    try:
                        button = page.locator('text=轻触阅读原文')
                        button_count = await button.count()
                        if button_count > 0:
                            await button.first.wait_for(state="visible", timeout=1000)
                            await button.first.click()
                            await asyncio.sleep(2)
                    except Exception as e:
                        print_warning(f"阅读原文按钮处理失败: {str(e)}")
                        
                # 获取文章信息
                title = await page.locator('meta[property="og:title"]').get_attribute("content")
                author = await page.locator('meta[property="og:article:author"]').get_attribute("content")
                description = await page.locator('meta[property="og:description"]').get_attribute("content")
                topic_image = await page.locator('meta[property="twitter:image"]').get_attribute("content")
                
                if not title:
                    title = await page.evaluate('() => document.title')
                    
                # 获取发布时间
                publish_time = await self._extract_publish_time(page)
                
                # 获取内容
                content = await page.content()
                
                # 提取 biz
                biz = self._extract_biz(url, content)
                
                # 构建结果
                info = {
                    "title": title or "",
                    "author": author or "",
                    "description": description or "",
                    "topic_image": topic_image or "",
                    "publish_time": publish_time,
                    "content": content,
                    "biz": biz,
                    "url": url
                }
                
                return info
                
        except Exception as e:
            print_error(f"获取文章内容失败: {str(e)}")
            raise
            
    async def _extract_publish_time(self, page) -> int:
        """
        提取发布时间(异步)
        """
        try:
            # 尝试从 meta 标签获取
            publish_time_str = await page.locator('meta[property="article:published_time"]').get_attribute("content")
            
            if publish_time_str:
                return self._convert_publish_time_to_timestamp(publish_time_str)
                
            # 尝试从页面内容获取
            content = await page.content()
            
            # 常见的时间格式
            patterns = [
                r'publish_time\s*=\s*["\']([^"\']+)["\']',
                r'var\s+publish_time\s*=\s*["\']([^"\']+)["\']',
                r'create_time\s*=\s*["\']([^"\']+)["\']',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return self._convert_publish_time_to_timestamp(match.group(1))
                    
            # 返回当前时间
            return int(datetime.now().timestamp())
            
        except Exception as e:
            print_warning(f"提取发布时间失败: {str(e)}")
            return int(datetime.now().timestamp())
            
    def _convert_publish_time_to_timestamp(self, publish_time_str: str) -> int:
        """
        将发布时间字符串转换为时间戳
        """
        try:
            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y年%m月%d日 %H:%M",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y年%m月%d日",
                "%m月%d日",
            ]
            
            for fmt in formats:
                try:
                    if fmt == "%m月%d日":
                        current_date = datetime.now()
                        current_year = current_date.year
                        full_time_str = f"{current_year}年{publish_time_str}"
                        dt = datetime.strptime(full_time_str, "%Y年%m月%d日")
                        
                        if dt > current_date:
                            dt = dt.replace(year=current_year - 1)
                    else:
                        dt = datetime.strptime(publish_time_str, fmt)
                    return int(dt.timestamp())
                except ValueError:
                    continue
                    
            return int(datetime.now().timestamp())
            
        except Exception as e:
            print_error(f"时间转换失败: {e}")
            return int(datetime.now().timestamp())
            
    def _extract_biz(self, url: str, content: str) -> str:
        """
        提取 biz 参数
        """
        # 从 URL 提取
        match = re.search(r'[?&]__biz=([^&]+)', url)
        if match:
            return match.group(1)
            
        # 从内容提取
        match = re.search(r'var\s+biz\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
            
        return ""


# Web 工具类(兼容旧代码)
class Web:
    """Web 工具类,提供文章内容清理等功能"""

    @staticmethod
    def clean_article_content(html_content: str) -> str:
        """
        清理文章内容

        Args:
            html_content: HTML 内容

        Returns:
            清理后的内容
        """
        if not html_content:
            return ""

        try:
            # 使用 BeautifulSoup 清理 HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # 移除脚本和样式
            for script in soup(["script", "style"]):
                script.decompose()

            # 获取文本
            text = soup.get_text()

            # 清理多余空白
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)

            return text

        except Exception as e:
            print_error(f"清理文章内容失败: {e}")
            return html_content

    @staticmethod
    def get_article_content(url: str) -> Dict:
        """
        获取文章内容(同步包装器,兼容旧代码)

        注意: 这是一个同步包装器,会阻塞调用线程
        建议使用 WXArticleFetcher().get_article_content() 的 async 版本

        Args:
            url: 文章URL

        Returns:
            文章信息字典
        """
        import asyncio

        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                # 创建 fetcher 实例
                fetcher = WXArticleFetcher()

                # 运行异步方法
                result = loop.run_until_complete(fetcher.get_article_content(url))

                return result
            finally:
                # 清理事件循环
                loop.close()

        except Exception as e:
            print_error(f"获取文章内容失败: {e}")
            return {}

    @staticmethod
    def get_description(content: str, max_length: int = 200) -> str:
        """
        从内容中提取描述

        Args:
            content: HTML 内容
            max_length: 最大长度

        Returns:
            描述文本
        """
        if not content:
            return ""

        try:
            # 清理内容
            cleaned = Web.clean_article_content(content)

            # 截取前 max_length 个字符
            if len(cleaned) > max_length:
                return cleaned[:max_length] + "..."
            else:
                return cleaned

        except Exception as e:
            print_error(f"提取描述失败: {e}")
            return ""

    @staticmethod
    def get_image_url(content: str) -> str:
        """
        从内容中提取图片URL

        Args:
            content: HTML 内容

        Returns:
            图片URL
        """
        if not content:
            return ""

        try:
            # 使用 BeautifulSoup 解析
            soup = BeautifulSoup(content, 'html.parser')

            # 查找第一个图片标签
            img = soup.find('img')

            if img:
                # 获取 src 属性
                src = img.get('src') or img.get('data-src')
                if src:
                    return src

            return ""

        except Exception as e:
            print_error(f"提取图片URL失败: {e}")
            return ""


# 导入 asyncio(用于文件顶部)
import asyncio
