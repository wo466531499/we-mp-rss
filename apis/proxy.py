"""
代理服务模块 - 用于突破 iframe 跨域限制
"""
from fastapi import APIRouter, Request, Response
import httpx
from urllib.parse import urlparse, urljoin
import logging
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["代理服务"])

# 允许代理的域名白名单（可选，为了安全可以限制）
ALLOWED_DOMAINS = None  # None 表示允许所有域名，或者设置列表如 ['mp.weixin.qq.com', 'weixin.qq.com']

# 资源处理的标签和属性映射
RESOURCE_TAGS = {
    'a': ['href'],
    'img': ['src', 'srcset', 'data-src'],
    'script': ['src'],
    'link': ['href'],
    'iframe': ['src'],
    'video': ['src', 'poster'],
    'audio': ['src'],
    'source': ['src'],
    'track': ['src'],
    'embed': ['src'],
    'object': ['data'],
    'form': ['action'],
    'input': ['src'],
    'frame': ['src'],
}


def rewrite_relative_urls(content: str, base_url: str) -> str:
    """
    重写 HTML 内容中的相对 URL 为绝对 URL
    
    Args:
        content: HTML 内容
        base_url: 基础 URL
        
    Returns:
        str: 重写后的 HTML 内容
    """
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
        # 处理各种标签中的 URL
        for tag_name, attrs in RESOURCE_TAGS.items():
            for tag in soup.find_all(tag_name):
                for attr in attrs:
                    if tag.has_attr(attr):
                        original_url = tag[attr]
                        if original_url and not original_url.startswith(('http://', 'https://', 'data:', 'mailto:', 'tel:', '#')):
                            # 转换为绝对 URL
                            absolute_url = urljoin(base_url, original_url)
                            # 代理化 URL
                            proxy_url = f"/proxy/proxy?url={absolute_url}"
                            tag[attr] = proxy_url
        
        # 处理 srcset 属性（特殊格式）
        for tag in soup.find_all(['img', 'source']):
            if tag.has_attr('srcset'):
                srcset = tag['srcset']
                urls = []
                for part in srcset.split(','):
                    part = part.strip()
                    if part:
                        # 提取 URL 和描述符
                        url_part = part.split()[0]
                        descriptor = ' '.join(part.split()[1:]) if len(part.split()) > 1 else ''
                        
                        if url_part and not url_part.startswith(('http://', 'https://', 'data:')):
                            absolute_url = urljoin(base_url, url_part)
                            proxy_url = f"/proxy/proxy?url={absolute_url}"
                            if descriptor:
                                urls.append(f"{proxy_url} {descriptor}")
                            else:
                                urls.append(proxy_url)
                        else:
                            urls.append(part)
                
                tag['srcset'] = ', '.join(urls)
        
        # 处理 style 属性中的 url()
        for tag in soup.find_all(attrs={'style': True}):
            style = tag['style']
            tag['style'] = rewrite_css_urls(style, base_url)
        
        # 处理内联 CSS
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                style_tag.string = rewrite_css_urls(style_tag.string, base_url)
        
        # 添加或更新 base 标签
        base_tag = soup.find('base')
        if not base_tag:
            head = soup.find('head')
            if head:
                new_base = soup.new_tag('base', href=base_url)
                head.insert(0, new_base)
        else:
            base_tag['href'] = base_url
        
        return str(soup)
    except Exception as e:
        logger.error(f"重写 URL 失败: {str(e)}")
        return content


def rewrite_css_urls(css_content: str, base_url: str) -> str:
    """
    重写 CSS 内容中的 url() 引用
    
    Args:
        css_content: CSS 内容
        base_url: 基础 URL
        
    Returns:
        str: 重写后的 CSS 内容
    """
    try:
        # 匹配 url() 中的 URL
        pattern = r'url\(["\']?([^)"\']+)["\']?\)'
        
        def replace_url(match):
            url = match.group(1)
            if url and not url.startswith(('http://', 'https://', 'data:', 'about:')):
                absolute_url = urljoin(base_url, url)
                proxy_url = f"/proxy/proxy?url={absolute_url}"
                return f'url("{proxy_url}")'
            return match.group(0)
        
        return re.sub(pattern, replace_url, css_content)
    except Exception as e:
        logger.error(f"重写 CSS URL 失败: {str(e)}")
        return css_content

def is_domain_allowed(url: str) -> bool:
    """
    检查域名是否在允许列表中
    
    Args:
        url: 目标URL
        
    Returns:
        bool: 是否允许代理
    """
    if ALLOWED_DOMAINS is None:
        return True
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        # 移除端口号
        domain = domain.split(':')[0]
        return domain in ALLOWED_DOMAINS
    except Exception:
        return False


@router.get("/{path:path}")
async def proxy_get_request(path: str, request: Request):
    """
    代理 GET 请求
    
    代理外部 URL 的请求，解决 iframe 跨域限制
    
    Args:
        path: 代理的路径
        request: FastAPI 请求对象
        
    Returns:
        Response: 代理的响应内容
    """
    # 从查询参数中获取目标 URL
    target_url = request.query_params.get("url")
    
    if not target_url:
        return Response(
            content="Missing 'url' parameter",
            status_code=400,
            media_type="text/plain"
        )
    
    # 检查域名白名单
    if not is_domain_allowed(target_url):
        logger.warning(f"尝试代理不允许的域名: {target_url}")
        return Response(
            content="Domain not allowed",
            status_code=403,
            media_type="text/plain"
        )
    
    try:
        # 获取客户端请求头
        headers = dict(request.headers)
        
        # 移除不应该转发的头
        headers.pop('host', None)
        headers.pop('content-length', None)
        headers.pop('content-encoding', None)
        headers.pop('transfer-encoding', None)
        
        # 添加用户代理（避免被反爬虫拦截）
        headers['User-Agent'] = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # 获取查询参数（除了 url 参数）
        query_params = dict(request.query_params)
        query_params.pop('url', None)
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            verify=False  # 忽略 SSL 证书验证
        ) as client:
            # 发起代理请求
            response = await client.get(
                target_url,
                headers=headers,
                params=query_params if query_params else None
            )
            
            # 构建响应
            content = response.content
            content_type = response.headers.get('content-type', 'text/html')
            
            # 处理 HTML 内容 - 重写相对路径
            if 'html' in content_type.lower():
                try:
                    # 解码内容
                    encoding = response.encoding or 'utf-8'
                    html_content = content.decode(encoding, errors='ignore')
                    
                    # 重写相对 URL
                    html_content = rewrite_relative_urls(html_content, target_url)
                    
                    # 重新编码
                    content = html_content.encode(encoding)
                except Exception as e:
                    logger.error(f"处理 HTML 内容失败: {str(e)}")
            
            # 处理 CSS 内容
            elif 'css' in content_type.lower():
                try:
                    encoding = response.encoding or 'utf-8'
                    css_content = content.decode(encoding, errors='ignore')
                    
                    # 重写 CSS 中的 url()
                    css_content = rewrite_css_urls(css_content, target_url)
                    
                    content = css_content.encode(encoding)
                except Exception as e:
                    logger.error(f"处理 CSS 内容失败: {str(e)}")
            
            response_headers = dict(response.headers)
            
            # 移除不应该返回的头
            response_headers.pop('content-encoding', None)
            response_headers.pop('transfer-encoding', None)
            response_headers.pop('content-length', None)
            
            # 添加 CORS 相关头
            response_headers['Access-Control-Allow-Origin'] = '*'
            response_headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response_headers['Access-Control-Allow-Headers'] = '*'
            
            # 针对微信公众号文章的特殊处理
            # 添加一些安全相关的头，允许在 iframe 中显示
            response_headers['X-Frame-Options'] = 'ALLOWALL'
            response_headers['Content-Security-Policy'] = "frame-ancestors *"
            
            return Response(
                content=content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type
            )
            
    except httpx.TimeoutException:
        logger.error(f"代理请求超时: {target_url}")
        return Response(
            content="Request timeout",
            status_code=504,
            media_type="text/plain"
        )
    except Exception as e:
        logger.error(f"代理请求失败: {target_url}, 错误: {str(e)}")
        return Response(
            content=f"Proxy error: {str(e)}",
            status_code=500,
            media_type="text/plain"
        )


@router.options("/{path:path}")
async def proxy_options_request(path: str, request: Request):
    """
    处理 OPTIONS 请求（CORS 预检请求）
    """
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Max-Age': '86400',
    }
    return Response(headers=headers, status_code=200)


@router.post("/{path:path}")
async def proxy_post_request(path: str, request: Request):
    """
    代理 POST 请求
    
    Args:
        path: 代理的路径
        request: FastAPI 请求对象
        
    Returns:
        Response: 代理的响应内容
    """
    # 从查询参数中获取目标 URL
    target_url = request.query_params.get("url")
    
    if not target_url:
        return Response(
            content="Missing 'url' parameter",
            status_code=400,
            media_type="text/plain"
        )
    
    # 检查域名白名单
    if not is_domain_allowed(target_url):
        logger.warning(f"尝试代理不允许的域名: {target_url}")
        return Response(
            content="Domain not allowed",
            status_code=403,
            media_type="text/plain"
        )
    
    try:
        # 获取请求体
        body = await request.body()
        
        # 获取客户端请求头
        headers = dict(request.headers)
        
        # 移除不应该转发的头
        headers.pop('host', None)
        headers.pop('content-length', None)
        headers.pop('content-encoding', None)
        headers.pop('transfer-encoding', None)
        
        # 添加用户代理
        headers['User-Agent'] = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # 获取查询参数（除了 url 参数）
        query_params = dict(request.query_params)
        query_params.pop('url', None)
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            verify=False
        ) as client:
            # 发起代理请求
            response = await client.post(
                target_url,
                content=body,
                headers=headers,
                params=query_params if query_params else None
            )
            
            # 构建响应
            content = response.content
            response_headers = dict(response.headers)
            
            # 移除不应该返回的头
            response_headers.pop('content-encoding', None)
            response_headers.pop('transfer-encoding', None)
            response_headers.pop('content-length', None)
            
            # 添加 CORS 相关头
            response_headers['Access-Control-Allow-Origin'] = '*'
            response_headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response_headers['Access-Control-Allow-Headers'] = '*'
            
            return Response(
                content=content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get('content-type', 'text/html')
            )
            
    except httpx.TimeoutException:
        logger.error(f"代理请求超时: {target_url}")
        return Response(
            content="Request timeout",
            status_code=504,
            media_type="text/plain"
        )
    except Exception as e:
        logger.error(f"代理请求失败: {target_url}, 错误: {str(e)}")
        return Response(
            content=f"Proxy error: {str(e)}",
            status_code=500,
            media_type="text/plain"
        )
