# 智舆—— 智能舆情监测分析平台

## 项目简介

智舆是一个基于 Python + Vue 3 + FastAPI 构建的全栈舆情监测与分析系统，覆盖数据采集、NLP 内容分析、机器学习热点聚类、情感分析、虚假文本检测、传播链路可视化、用户画像洞察、智能问答及报表自动生成等完整功能链路，旨在为用户提供从多平台数据抓取到舆情洞察与决策支持的一站式解决方案。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / SQLite / jieba / sentence-transformers / scikit-learn |
| 前端 | Vue 3 / Element Plus / ECharts / Axios |
| 爬虫 | Playwright / urllib（多平台适配器架构） |
| LLM | DeepSeek API（事件概述、情感分析、平台分布推算） |

## 功能特性

### 数据采集

- 支持 6 大平台：微博、抖音、知乎、B站、人民网、小红书
- 三层架构：API 层 → 轻量层 → Playwright 浏览器层
- 数据清洗：三重去重（URL/标题/标题+时间）+ 去噪过滤 + 格式标准化
- 关键词自动扩展：基于语义向量相似度自动扩展采集关键词
- 前端数据采集页面：平台多选 + 关键词输入 + 一键采集

### 内容分析

- 正文内容提取（HTML 清洗）
- jieba 中文分词
- TF-IDF 关键词提取
- Sentence-BERT 语义向量特征表示（text2vec-base-chinese，768 维）
- KMeans 聚类 + 轮廓系数评估

### 热点发现

- TF-IDF + KMeans 聚类对新闻进行主题分组
- Sentence-BERT 语义向量编码
- 基于时间窗口和报道数量的热点识别
- 事件自动聚合（多条报道归为单一事件）

### 舆情分析

- 情感分析：情感词典 + TF-IDF 加权 + DeepSeek LLM 补充判断（正面/负面/中性）
- 平台分布推算：DeepSeek LLM 多平台报道占比估算
- 虚假文本检测（多维度特征加权，输出置信度）
- 传播链路分析（首发来源/核心放大/官方回应/次级传播 四类节点）
- 生命周期预测（潜伏/成长/高潮/衰退）
- 热度走势预判（24h/72h 趋势预测）
- 情绪量化分析 + 情绪波动激化节点识别
- 处置建议生成（辟谣话术/公众建议/运营建议/风险贴士/监测节点）
- 事件概述自动生成（DeepSeek LLM 纯文字总结）
- 交互数据指标展示（热度/情感标签/来源渠道/视频数量）
- 概述支持人工编辑保存

### 传播路径可视化

- ECharts 力导向图展示传播网络
- 节点按角色分类着色（首发来源/核心放大/官方回应/次级传播）
- 支持拖拽缩放、悬浮高亮相邻节点
- 传播深度、转发量、阅读量统计

### 用户画像洞察

- 传播参与用户四分类：水军 / 营销号 / 普通网民 / 行业利益方
- 多维度画像分析：地域分布、兴趣圈层、年龄段、品牌人群分层
- 传播图谱可视化（ECharts 力导向图）
- 模糊账号复核面板（支持隐藏水军节点）
- 画像结果一键导出图片

### 报表自动生成

- 舆情日报：当日新增热点、热度排行、情感分布、风险预警
- 舆情周报：热度趋势、情感变化、负面话题、虚假信息、传播统计
- 事件专报：单事件完整复盘（热度/传播/情感/可信度/关联新闻）
- 支持 Word（.docx）和 PDF 导出
- 一键下载，自动填充数据

### 智能问答

- 基于语义搜索的智能问答
- 支持关键词匹配 + 语义相似度双路检索

### 前端展示

- 舆情看板（Dashboard）：总体统计和趋势图
- 事件看板（Event Board）：事件列表、排序、筛选
- 事件详情：概述、交互数据指标、报道量趋势、情感分布、平台分布、高频关键词、可信度评分、传播链路力导向图、情绪分析、热度预判、处置建议、关联新闻
- 用户画像：传播参与者四分类、地域/兴趣/年龄画像、传播图谱、模糊账号复核
- 报表导出：日报/周报/事件专报，Word + PDF
- 数据采集页：一键采集、任务管理、采集统计
- 个人中心：关注平台/关键词配置

## 项目结构

```
sentiment_analysis/
├── app/                    # 后端应用
│   ├── api/                # API 路由
│   │   ├── auth.py         # 认证鉴权
│   │   ├── routes.py       # 核心业务路由
│   │   ├── event.py        # 事件详情/编辑 API
│   │   ├── crawler_api.py  # 爬虫管理路由
│   │   ├── report_api.py   # 报表导出路由（日报/周报/事件专报）
│   │   └── user_profile_api.py  # 用户画像分析路由
│   ├── core/               # 核心模块
│   │   ├── auth.py         # JWT 认证
│   │   └── database.py     # 数据库管理
│   ├── services/           # 业务服务
│   │   ├── nlp_tools.py           # NLP 工具（分词、关键词、语义向量）
│   │   ├── hotspot_detector.py    # 热点发现
│   │   ├── event_aggregator.py    # 事件聚合
│   │   ├── event_processor.py    # 事件处理
│   │   ├── event_summarizer.py   # 事件概述生成（DeepSeek LLM）
│   │   ├── sentiment_analyzer.py # 情感分析（词典 + LLM）
│   │   ├── fake_detector.py      # 虚假文本检测
│   │   ├── spread_analyzer.py    # 传播路径分析（ECharts graph 数据）
│   │   ├── lifecycle_predictor.py # 生命周期预测
│   │   ├── heat_predictor.py     # 热度预判
│   │   ├── emotion_analyzer.py   # 情绪量化分析
│   │   ├── action_advisor.py     # 处置建议生成
│   │   ├── user_profile_analyzer.py  # 用户画像分析（四分类 + 多维度画像）
│   │   └── report_generator.py      # 报表数据聚合 + Word 文档生成
│   └── schemas/           # 数据模式
├── crawler/                # 爬虫模块
│   ├── adapters/           # 平台适配器
│   │   ├── weibo.py        # 微博
│   │   ├── douyin.py       # 抖音（apihz.cn API）
│   │   ├── zhihu.py        # 知乎
│   │   ├── bilibili.py      # B站
│   │   ├── people_rss.py   # 人民网 RSS
│   │   └── xiaohongshu.py  # 小红书（Playwright）
│   ├── engines/            # 引擎层
│   ├── models.py           # 数据模型
│   ├── scheduler.py        # 任务调度器
│   ├── storage.py          # 数据存储
│   ├── cleaners.py         # 数据清洗
│   └── cli.py              # 命令行入口
├── frontend/               # 前端项目
│   └── src/
│       ├── views/          # 页面组件
│       │   ├── DashboardView.vue      # 舆情看板
│       │   ├── EventBoardView.vue     # 事件看板
│       │   ├── EventDetailView.vue    # 事件详情（含传播链路力导向图）
│       │   ├── QAView.vue             # 智能问答
│       │   ├── CrawlerView.vue        # 数据采集
│       │   ├── UserProfileView.vue   # 用户画像
│       │   ├── ReportView.vue         # 报表导出
│       │   └── ProfileView.vue        # 个人中心
│       ├── router/         # 路由配置
│       └── App.vue          # 根组件
├── nlp_analysis.py          # NLP 舆情分析引擎（聚类 + 情感 + 概述）
├── spread_trace.py          # 传播溯源命令行工具
├── main.py                  # 后端入口
├── requirements.txt         # Python 依赖
└── sql/                     # SQL 初始化脚本
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 16+

### 后端安装

```bash
cd sentiment_analysis
pip install -r requirements.txt
pip install python-docx   # 报表导出（Word）
```

### 前端安装

```bash
cd sentiment_analysis/frontend
npm install
```

### 配置

1. 抖音数据源使用 apihz.cn 免费 API，需注册获取 id 和 key，替换 `crawler/adapters/douyin.py` 中的默认值
2. 语义模型（sentence-transformers）首次运行会自动下载，国内网络建议设置镜像：
   ```bash
   export HF_ENDPOINT=https://hf-mirror.com
   ```
3. DeepSeek LLM 配置（用于事件概述、情感分析、平台分布推算）：
   ```bash
   export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   不配置则使用本地 fallback 逻辑
4. PDF 导出需安装 LibreOffice：
   ```bash
   # Windows: 下载安装 LibreOffice，确保 soffice 在 PATH 中
   # macOS: brew install --cask libreoffice
   ```

### 启动

```bash
# 后端（默认端口 9000）
cd sentiment_analysis
python -m uvicorn main:app --port 9000

# 前端（默认端口 5173）
cd sentiment_analysis/frontend
npm run dev
```


## 使用指南

### 数据采集

1. 登录后进入「个人中心」，配置关注的平台和关键词
2. 进入「数据采集」页面，选择平台、输入关键词，点击「一键采集」
3. 采集完成后，前往「事件看板」和「舆情看板」查看分析结果

### NLP 分析

```bash
# 分析 pending 新闻（默认 100 条）
python nlp_analysis.py

# 指定数量
python nlp_analysis.py --limit 50
```

### 命令行采集

```bash
# 采集所有平台热榜
python -m crawler.cli --once

# 定时循环采集（每 15 分钟）
python -m crawler.cli --interval 15

# 采集指定平台
python -m crawler.cli --platform bilibili --once

# 关键词搜索
python -m crawler.cli --platform weibo --task-type keyword --keyword "AI"
```

### 报表导出

在「报表导出」页面，支持以下三种报表一键下载：

| 报表类型 | 内容 | 导出格式 |
|----------|------|----------|
| 舆情日报 | 当日新增热点、热度排行、情感分布、风险预警 | Word / PDF |
| 舆情周报 | 热度趋势、情感变化、负面话题、虚假信息、传播统计 | Word / PDF |
| 事件专报 | 单事件完整复盘（热度/传播/情感/可信度/关联新闻） | Word / PDF |

也可通过 API 调用：
```bash
GET /api/reports/daily?format=docx
GET /api/reports/weekly?format=pdf
GET /api/reports/event/{event_id}?format=docx
```

## 机器学习组件

| 组件 | 技术 | 用途 |
|------|------|------|
| Sentence-BERT | text2vec-base-chinese | 语义特征提取（768维向量） |
| KMeans | scikit-learn | 新闻聚类 + 轮廓系数评估 |
| TF-IDF | jieba.analyse | 关键词提取与特征表示 |
| 语义搜索 | 余弦相似度 | 智能问答、事件关联、关键词扩展 |
| DeepSeek LLM | deepseek-chat | 事件概述、情感分析、平台分布推算 |

## License

MIT
