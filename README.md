# 智舆（ZhiYu）—— 智能舆情监测分析平台

## 项目简介

智舆（ZhiYu）是一个基于 Python + Vue 3 + FastAPI 构建的全栈舆情监测与分析系统，覆盖数据采集、NLP 内容分析、机器学习热点聚类、情感分析、虚假文本检测、传播链路分析及可视化展示等完整功能链路，旨在为用户提供从多平台数据抓取到舆情洞察的一站式解决方案。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / SQLite / jieba / sentence-transformers / scikit-learn |
| 前端 | Vue 3 / Element Plus / ECharts / Axios |
| 爬虫 | Playwright / urllib（多平台适配器架构） |

## 功能特性

### 数据采集

- 支持 6 大平台：微博、抖音、知乎、B站、人民网、小红书
- 三层架构：API 层 → 轻量层 → Playwright 浏览器层
- 数据清洗：三重去重（URL/标题/标题+时间）+ 去噪过滤 + 格式标准化
- 前端数据采集页面：平台多选 + 关键词输入 + 一键采集

### 内容分析

- 正文内容提取（HTML 清洗）
- jieba 中文分词
- TF-IDF 关键词提取
- Sentence-BERT 语义向量特征表示

### 热点发现

- DBSCAN 密度聚类（scikit-learn）对新闻进行主题分组
- Sentence-BERT 语义向量编码
- 基于时间窗口和报道数量的热点识别
- 事件自动聚合（多条报道归为单一事件）

### 舆情分析

- 情感分析（正面/负面/中性）
- 虚假文本检测（多维度特征加权，输出置信度）
- 事件溯源与关键传播路径分析
- 生命周期预测（萌芽/成长/爆发/衰退/消亡）
- 热度走势预判
- 处置建议生成

### 智能问答

- 基于语义搜索的智能问答
- 支持关键词匹配 + 语义相似度双路检索

### 前端展示

- 舆情看板（Dashboard）：总体统计和趋势图
- 事件看板（Event Board）：事件列表、排序、筛选
- 事件详情：关联新闻、可信度评分、传播链路、关键词标签
- 数据采集页：一键采集、任务管理、采集统计
- 个人中心：关注平台/关键词配置

## 项目结构

```
sentiment_analysis/
├── app/                    # 后端应用
│   ├── api/                # API 路由
│   │   ├── auth.py         # 认证鉴权
│   │   ├── routes.py       # 核心业务路由
│   │   └── crawler_api.py   # 爬虫管理路由
│   ├── core/               # 核心模块
│   │   ├── auth.py         # JWT 认证
│   │   └── database.py     # 数据库管理
│   ├── services/           # 业务服务
│   │   ├── nlp_tools.py           # NLP 工具（分词、关键词、语义向量）
│   │   ├── hotspot_detector.py    # 热点发现（DBSCAN 聚类）
│   │   ├── event_aggregator.py    # 事件聚合
│   │   ├── event_processor.py    # 事件处理
│   │   ├── sentiment_analyzer.py # 情感分析
│   │   ├── fake_detector.py      # 虚假文本检测
│   │   ├── spread_analyzer.py    # 传播路径分析
│   │   ├── lifecycle_predictor.py# 生命周期预测
│   │   ├── heat_predictor.py     # 热度预判
│   │   ├── emotion_analyzer.py   # 情绪量化
│   │   ├── action_advisor.py     # 处置建议
│   │   └── event_summarizer.py   # 事件摘要
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
│       ├── router/         # 路由配置
│       └── App.vue          # 根组件
├── main.py                 # 后端入口
└── requirements.txt        # Python 依赖
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 16+

### 后端安装

```bash
cd sentiment_analysis
pip install -r requirements.txt
```

### 前端安装

```bash
cd sentiment_analysis/frontend
npm install
```

### 配置

1. 抖音数据源使用 apihz.cn 免费 API，需注册获取 id 和 key，替换 `crawler/adapters/douyin.py` 中的默认值
2. 语义模型（sentence-transformers）首次运行会自动下载，国内网络建议设置镜像：
   ```python
   export HF_ENDPOINT=https://hf-mirror.com
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

### 访问

打开浏览器访问 http://localhost:5173，默认账号 admin，密码 admin123

## 使用指南

### 数据采集

1. 登录后进入「个人中心」，配置关注的平台和关键词
2. 进入「数据采集」页面，选择平台、输入关键词，点击「一键采集」
3. 采集完成后，前往「事件看板」和「舆情看板」查看分析结果

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

## 机器学习组件

| 组件 | 技术 | 用途 |
|------|------|------|
| Sentence-BERT | text2vec-base-chinese | 语义特征提取（768维向量） |
| DBSCAN | scikit-learn | 基于密度的新闻聚类 |
| TF-IDF | jieba.analyse | 关键词提取与特征表示 |
| 语义搜索 | 余弦相似度 | 智能问答、事件关联 |

## License

MIT
