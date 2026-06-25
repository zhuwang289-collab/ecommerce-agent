\# 🛒 AI 电商自动化运营 Agent

基于大模型的智能电商运营系统，实现\*\*商品数据获取 → AI 文案/定价优化 → 批量上架 → 智能客服\*\*全流程自动化。

> 数据源：FakeStore API（电商场景模拟）  
> AI 引擎：DeepSeek API（deepseek-chat）  
> 目标平台：抖店开放平台（测试/正式双模式）

\---

## 📸 效果预览

Phase 1: 商品获取 (FakeStore API) → 20 个商品，4 个品类  
Phase 2: DeepSeek 优化 (并发) → 智能定价 + 标题优化  
Phase 3: 抖店上架 → 模拟批量上传  
Phase 4: 结果展示 → rich 终端表格  
Phase 5: Excel 导出 → optimized\_products.xlsx  
Phase 6: 智能客服 → 基于知识库的多轮对话助手

!\[运行截图](./screenshots/demo.png)

\---

## 🚀 核心功能

| 模块 | 能力 |
|------|------|
| \*\*数据获取\*\* | 通过 FakeStore API 获取商品数据，支持扩展其他数据源 |
| \*\*AI 定价引擎\*\* | DeepSeek 根据商品类别、市场行情、利润率生成建议售价，安全兜底 |
| \*\*标题优化\*\* | 生成 ≤60 字 SEO 友好标题，突出卖点与关键词 |
| \*\*并发加速\*\* | 线程池并发调用 API，1000 商品优化时间压缩 80% |
| \*\*抖店上架\*\* | 测试模式（模拟日志）/ 正式模式（HMAC-SHA256 签名 + API 调用） |
| \*\*报表导出\*\* | 自动生成带格式的 Excel 文件，中文列名，冻结首行 |
| \*\*智能客服\*\* | DeepSeek 驱动的电商客服，基于商品知识库回答用户咨询，支持多轮对话 |

\---

## 🛠️ 技术栈

Python 3.10+  ·  Playwright  ·  BeautifulSoup4  ·  DeepSeek API  ·  OpenAI SDK  
python-dotenv  ·  Rich  ·  openpyxl  ·  多线程并发  ·  抖店开放平台

\---

## 📂 项目结构

ecommerce-agent/
├── src/
│   ├── scraper.py             # 数据获取模块（FakeStore API）
│   ├── optimizer.py           # AI 优化模块（DeepSeek）
│   ├── douyin\_uploader.py     # 抖店上架模块
│   ├── customer\_service.py    # 智能客服模块（DeepSeek 多轮对话）
│   └── main.py                # 一键主流程
├── data/                      # 输出目录
│   ├── products.json
│   ├── optimized\_products.json
│   ├── chat\_history.json      # 客服对话历史
│   └── optimized\_products.xlsx
├── screenshots/               # 运行截图
│   └── demo.png
├── .env.example               # 环境变量模板
├── requirements.txt
└── README.md

\---

## ⚡ 快速开始

### 1. 克隆项目

git clone https://github.com/zhuwang289-collab/ecommerce-agent.git
cd ecommerce-agent

### 2. 创建虚拟环境并安装依赖

python -m venv venv

Windows:
.\\venv\\Scripts\\Activate.ps1

Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium

### 3. 配置环境变量

在项目根目录创建 .env 文件，填入你的密钥：

OPENAI\_API\_KEY=sk-your-deepseek-api-key
DOUYIN\_APP\_KEY=your\_douyin\_app\_key\_placeholder
DOUYIN\_APP\_SECRET=your\_douyin\_app\_secret\_placeholder
DOUYIN\_TEST\_MODE=True

测试模式无需真实抖店 Key，可立即体验全流程。

### 4. 运行主流程

python src/main.py

终端将展示数据获取、AI 优化过程、模拟上架日志，最终生成 data/optimized\_products.xlsx。

\---

## 🤖 智能客服

基于 DeepSeek API 的智能客服助手"小智"，支持多轮对话。

### 启动客服

\# 交互模式（命令行直接对话）
python src/customer_service.py

\# Demo 模式（模拟 3 轮咨询，展示效果）
python src/customer_service.py --demo

\### 功能特点

- \*\*知识库驱动\*\*：自动从 data/products.json 构建商品知识库（标题、价格、品类、描述）
- \*\*多轮对话\*\*：支持上下文记忆，对话历史持久化到 data/chat\_history.json
- \*\*80 字精炼回复\*\*：每条回答不超过 80 字，简洁友好
- \*\*安全兜底\*\*：无法回答时自动转接人工客服
- \*\*CLI 交互\*\*：命令行界面，输入 exit 退出，clear 清空历史

### 交互命令

| 命令 | 作用 |
|------|------|
| 任意文本 | 向客服提问 |
| exit | 退出对话 |
| clear | 清空对话历史 |

\---

## 🔄 切换正式模式（真实上架）

1. 前往 抖店开放平台 创建应用，获取 App Key 和 App Secret
2. 修改 .env：
   DOUYIN\_APP\_KEY=你的真实Key
   DOUYIN\_APP\_SECRET=你的真实Secret
   DOUYIN\_TEST\_MODE=False
3. 重新运行 python src/main.py，商品将真实上架到你的抖店店铺。

\---

## 📊 数据源切换

系统设计为数据源无关，你可以将数据获取模块替换为：
- FakeStore API（当前使用，公开电商测试数据）
- Books to Scrape（爬虫练习站）
- Kaggle 电商数据集
- 自有商品表格 (CSV/Excel)

只需修改 scraper.py 或新增一个适配器，保持输出 products.json 格式一致即可。

\---

## 💡 关键设计决策

| 决策 | 原因 |
|------|------|
| DeepSeek 而非 GPT-4 | 成本更低、中文能力强、延迟低 |
| 并发调用 API | 大幅压缩处理时间 |
| 安全兜底（不低于原价） | 防止 AI 幻觉导致异常低价 |
| 测试/正式双模式 | 开发安全、上线无忧 |
| 抖店开放平台 API | 合规，避免封店风险 |
| 客服知识库自动构建 | 无需手动维护 FAQ，商品数据即知识库 |

\---

## 📈 性能数据

- 20 商品全流程（获取 + AI 优化 + 模拟上架 + Excel 导出）：约 30 秒
- AI 优化阶段（并发 5 线程）：约 10 秒
- 模拟上架阶段：约 20 秒
- 可扩展至 1000+ 商品，优化时间压缩 80%
- 智能客服响应：每轮约 1-3 秒（取决于 DeepSeek API 延迟）

\---

## 📝 后续规划

- 定时任务调度（每日自动运行）
- Web 可视化面板
- 支持多平台（Shopify / 微信小店）
- 数据库持久化替代 JSON 文件
- 客服支持多语言

\---

## 📄 许可证

本项目仅供学习与个人开发使用。使用真实电商平台时请遵守其服务条款。

\---

⭐️ 如果这个项目对你有帮助，欢迎 Star！
