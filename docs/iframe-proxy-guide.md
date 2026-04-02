# Iframe 跨域代理使用指南

## 概述

本项目已添加了一个代理服务，用于突破 iframe 的跨域限制。该代理服务可以安全地转发外部 URL 的请求，解决浏览器同源策略带来的限制。

## 功能特性

- ✅ **GET/POST 请求代理**：支持代理 GET 和 POST 请求
- ✅ **相对路径自动重写**：自动将 HTML/CSS 中的相对路径转换为代理 URL
- ✅ **资源代理**：自动代理 CSS、JS、图片等资源文件
- ✅ **CORS 处理**：自动添加 CORS 相关响应头
- ✅ **请求头转发**：智能转发客户端请求头
- ✅ **重定向跟随**：自动跟随 HTTP 重定向
- ✅ **超时控制**：30 秒超时保护
- ✅ **域名白名单**：可选的域名白名单功能（默认允许所有域名）
- ✅ **安全响应头**：添加 `X-Frame-Options` 和 `Content-Security-Policy` 允许在 iframe 中显示

## 使用方法

### 1. 在 iframe 中使用（文章详情页）

在 `article_detail.html` 模板中，iframe 的 src 已修改为使用代理：

```html
<iframe src="/proxy/proxy?url={{article.url}}" 
        style="width: 100%; height: 100%; border: none;" 
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups"></iframe>
```

### 2. 直接访问代理 API

#### GET 请求

```
GET /proxy/proxy?url=https://example.com
```

#### POST 请求

```
POST /proxy/proxy?url=https://example.com/api
Content-Type: application/json

{
  "key": "value"
}
```

### 3. 在 JavaScript 中使用

```javascript
// 获取代理 URL
const originalUrl = 'https://mp.weixin.qq.com/s/xxx';
const proxyUrl = `/proxy/proxy?url=${encodeURIComponent(originalUrl)}`;

// 在 iframe 中使用
const iframe = document.createElement('iframe');
iframe.src = proxyUrl;
document.body.appendChild(iframe);

// 或者使用 fetch
fetch(proxyUrl)
  .then(response => response.text())
  .then(data => console.log(data));
```

## 相对路径处理

代理服务会自动处理 HTML 和 CSS 内容中的相对路径，将其转换为代理 URL，确保资源可以正常加载。

### 支持的资源类型

代理会自动处理以下资源类型的相对路径：

- **HTML 标签**：
  - `<a href="...">` - 链接
  - `<img src="..." data-src="...">` - 图片
  - `<script src="...">` - JavaScript 文件
  - `<link href="...">` - CSS 和其他资源
  - `<iframe src="...">` - 内嵌框架
  - `<video src="..." poster="...">` - 视频
  - `<audio src="...">` - 音频
  - `<source src="...">` - 媒体源
  - `<form action="...">` - 表单提交
  - 其他包含 URL 属性的标签

- **CSS 内容**：
  - `url(...)` - CSS 中的资源引用
  - `@import url(...)` - CSS 导入

- **特殊属性**：
  - `srcset` - 响应式图片源集
  - `style` - 内联样式

### 处理原理

1. **HTML 处理**：
   - 使用 BeautifulSoup 解析 HTML
   - 遍历所有包含 URL 属性的标签
   - 将相对路径转换为绝对路径
   - 将绝对路径转换为代理 URL
   - 自动添加 `<base>` 标签

2. **CSS 处理**：
   - 使用正则表达式匹配 `url()` 中的路径
   - 将相对路径转换为绝对路径
   - 将绝对路径转换为代理 URL

3. **Base URL**：
   - 自动在 HTML head 中添加 `<base>` 标签
   - 确保所有相对路径都有正确的基准

### 示例

**原始 HTML：**
```html
<img src="/images/logo.png">
<link rel="stylesheet" href="/styles/main.css">
<script src="/js/app.js"></script>
```

**代理处理后：**
```html
<base href="https://example.com/">
<img src="/proxy/proxy?url=https://example.com/images/logo.png">
<link rel="stylesheet" href="/proxy/proxy?url=https://example.com/styles/main.css">
<script src="/proxy/proxy?url=https://example.com/js/app.js"></script>
```

**原始 CSS：**
```css
background: url(/images/bg.png);
@import url(/styles/common.css);
```

**代理处理后：**
```css
background: url("/proxy/proxy?url=https://example.com/images/bg.png");
@import url("/proxy/proxy?url=https://example.com/styles/common.css");
```

### 注意事项

1. **性能影响**：HTML 和 CSS 的处理会增加一些延迟，但通常可以接受
2. **编码问题**：代理会自动处理字符编码，但某些特殊编码可能会有问题
3. **JavaScript 动态加载**：JavaScript 动态生成的 URL 不会被自动处理
4. **Data URL**：：data: 协议的 URL 不会被代理
5. **绝对 URL**：已有绝对路径的 URL 会被代理，确保所有资源都通过代理加载

## API 端点

### GET /proxy/{path:path}

代理 GET 请求到指定的 URL。

**查询参数：**
- `url` (必需): 目标 URL

**示例：**
```bash
curl "http://localhost:8001/proxy/proxy?url=https://mp.weixin.qq.com/s/xxx"
```

### POST /proxy/{path:path}

代理 POST 请求到指定的 URL。

**查询参数：**
- `url` (必需): 目标 URL

**请求体：**
- 任意类型的请求体数据

**示例：**
```bash
curl -X POST "http://localhost:8001/proxy/proxy?url=https://api.example.com/data" \
  -H "Content-Type: application/json" \
  -d '{"key": "value"}'
```

### OPTIONS /proxy/{path:path}

处理 CORS 预检请求。

## 安全配置

### 域名白名单

为了提高安全性，可以在 `apis/proxy.py` 中配置允许代理的域名白名单：

```python
# 允许代理的域名白名单
ALLOWED_DOMAINS = [
    'mp.weixin.qq.com',
    'weixin.qq.com',
    # 添加更多允许的域名
]
```

设置为 `None` 允许代理所有域名（默认行为）。

### 安全响应头

代理自动添加以下安全响应头：

```http
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: *
X-Frame-Options: ALLOWALL
Content-Security-Policy: frame-ancestors *
```

## 配置建议

### 1. 生产环境

在生产环境中，建议：

1. **启用域名白名单**：限制只允许代理可信的域名
2. **添加认证**：在代理端点添加访问控制
3. **监控日志**：监控代理请求日志，发现异常访问
4. **限流**：添加请求限流防止滥用

### 2. 开发环境

在开发环境中，可以保持默认配置（允许所有域名）以方便测试。

## 常见问题

### Q: 代理请求超时怎么办？

A: 默认超时时间为 30 秒。可以在 `apis/proxy.py` 中修改 `timeout=httpx.Timeout(30.0)` 来调整。

### Q: 如何处理 SSL 证书错误？

A: 代理默认忽略 SSL 证书验证（`verify=False`）。在生产环境中，建议启用证书验证。

### Q: iframe 中的内容无法正常显示？

A: 可能原因：
1. 目标网站有反爬虫机制
2. 需要特定的请求头或 Cookie
3. 目标网站使用了 JavaScript 跳转

可以通过查看浏览器控制台和服务器日志来诊断问题。

### Q: 如何调试代理请求？

A: 检查服务器日志，代理请求会记录以下信息：
- 代理的目标 URL
- 请求状态
- 错误信息（如果有）

### Q: 相对路径资源无法加载？

A: 代理服务已经自动处理相对路径，但如果仍有问题：
1. 检查浏览器控制台是否有 404 错误
2. 查看服务器日志中的"重写 URL 失败"错误
3. 确认目标网站的 HTML 结构是否正确
4. 某些使用 JavaScript 动态加载的资源可能无法被代理

### Q: 为什么有些资源仍然无法加载？

A: 可能原因：
1. **JavaScript 动态生成 URL**：代理无法处理 JS 运行时生成的 URL
2. **跨域限制**：某些资源有严格的 CORS 策略
3. **特殊协议**：某些使用了特殊协议的资源（如 blob:, about:）无法代理
4. **编码问题**：某些非 UTF-8 编码的资源可能处理失败

### Q: 代理后页面样式错乱？

A: 可能原因：
1. CSS 文件中的相对路径没有被正确处理
2. CSS 文件加载失败（查看控制台错误）
3. 目标网站使用了 CSS 变量或特殊选择器
4. 字体文件无法加载

可以通过浏览器开发者工具检查：
- Network 标签：查看哪些资源加载失败
- Console 标签：查看是否有 JavaScript 错误
- Elements 标签：检查 HTML 结构是否正确

## 依赖项

代理服务需要以下依赖项（已包含在 `requirements.txt` 中）：

```
httpx==0.28.1
beautifulsoup4==4.13.4
```

注意：`beautifulsoup4` 已经在项目依赖中，无需额外安装。

## 文件结构

```
we-mp-rss/
├── apis/
│   └── proxy.py          # 代理服务 API 模块
├── public/
│   └── templates/
│       └── article_detail.html  # 使用代理的文章详情页
├── web.py               # 主应用文件（已注册代理路由）
└── docs/
    └── iframe-proxy-guide.md    # 本文档
```

## 更新日志

- **v1.1.0** (2026-04-02)
  - 添加相对路径自动重写功能
  - 支持 HTML 中各种资源标签的 URL 转换
  - 支持 CSS 中 url() 的转换
  - 自动添加 base 标签
  - 处理 srcset 属性
  - 处理内联样式中的 URL

- **v1.0.0** (2026-04-02)
  - 添加代理服务 API
  - 支持 GET/POST 请求代理
  - 配置 CORS 和安全响应头
  - 更新文章详情页面使用代理
  - 添加域名白名单功能

## 技术支持

如有问题，请查看：
1. 服务器日志
2. 浏览器控制台错误
3. 本项目的 GitHub Issues
2. 浏览器控制台错误
3. 本项目的 GitHub Issues
