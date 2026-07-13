# -*- coding: utf-8 -*-
"""
DeepSeek LLM 驱动的逼真虚拟用户生成器
=====================================
从新闻标题/内容生成逼真的社交媒体用户数据，包括：
- 用户名、简介、IP 属地
- 评论内容（带情绪标签）
- 粉丝数、关注数、发帖数
- 注册时间

用法:
    from app.services.llm_user_generator import generate_users_for_event
    users = generate_users_for_event("山西政协提案", "新闻摘要...", "微博", count=5)
"""

import os
import json
import random
import hashlib
import requests
from typing import List, Dict

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# 中国省份列表（用于 IP 属地）
PROVINCES = [
    "北京", "上海", "广东", "浙江", "江苏", "四川", "湖北",
    "山东", "河南", "湖南", "福建", "安徽", "陕西", "辽宁",
    "重庆", "天津", "河北", "江西", "广西", "云南", "贵州",
    "山西", "黑龙江", "吉林", "甘肃", "青海", "海南", "内蒙古",
    "新疆", "西藏", "宁夏", "台湾", "香港", "澳门",
]

# 用户名前缀词库（姓氏 + 身份）
SURNAMES = [
    "张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
    "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕",
    "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎",
]
IDENTITIES = [
    "市民", "打工人", "学生", "老师", "医生", "律师", "程序员",
    "设计师", "摄影师", "美食家", "旅行者", "宝妈", "宝爸",
    "退休职工", "自由职业", "创业者", "公务员", "工程师",
    "研究员", "记者", "编辑", "博主", "UP主", "主播", "带货达人",
]
NICKNAME_SUFFIXES = [
    "", "2024", "2023", "的日常", "在路上", "的生活",
    "看世界", "说真话", "爱生活", "不将就", "小透明",
    "", "_", "", "",  # 大部分不加后缀更真实
]


def _generate_fallback_username(platform: str) -> str:
    """当 LLM 失败时，生成一个看起来像真的用户名"""
    surname = random.choice(SURNAMES)
    identity = random.choice(IDENTITIES)
    suffix = random.choice(NICKNAME_SUFFIXES)
    
    styles = [
        f"{surname}{identity}{suffix}",
        f"{surname}家{identity}{suffix}",
        f"{identity}{surname}哥",
        f"{identity}{surname}姐",
        f"{surname}小{random.choice(['明', '红', '芳', '强', '伟', '静'])}{suffix}",
        f"吃瓜{surname}哥",
        f"{surname}叔{suffix}",
        f"{surname}姨{suffix}",
    ]
    username = random.choice(styles)
    if platform == "B站":
        username = random.choice([f"{username}Official", f"{username}_", f"{username}酱"])
    elif platform == "抖音":
        username = f"{username}"
    return username[:20]


def _random_register_date() -> str:
    """生成合理的注册时间（1-10 年前，月份分散）"""
    years_ago = random.randint(1, 10)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    hour = random.randint(0, 23)
    return f"{2026 - years_ago}-{month:02d}-{day:02d} {hour:02d}:00:00"


def generate_users_for_event(title: str, content: str, platform: str, count: int = 5) -> List[Dict]:
    """
    用 DeepSeek LLM 生成逼真的虚拟用户数据。

    参数:
        title:   新闻标题
        content: 新闻正文（前 200 字即可）
        platform: 平台名称（微博/知乎/B站/抖音等）
        count:   需要生成的用户数（建议 5-10，太多 API 慢）

    返回:
        用户字典列表，每个用户包含 username, bio, ip_location,
        content, followers, emotion, platform, register_date 等字段。
        如果 API 失败，返回空列表（调用方应使用 fallback）。
    """
    if not DEEPSEEK_API_KEY:
        print("[LLM] DEEPSEEK_API_KEY 未配置，跳过 LLM 生成")
        return []

    # 精简内容，减少 token 消耗
    content_snippet = (content or title)[:250]

    prompt = f"""你是一个社交媒体用户数据生成专家。

新闻标题：{title}
新闻内容摘要：{content_snippet}
平台：{platform}

请生成 {count} 个该平台上的真实中文用户，他们正在参与讨论这个新闻事件。

【用户名风格要求 - 必须多样化，每个用户用不同风格】
真实社交媒体昵称风格包括（随机混合使用，不要只用一种）：
- 纯数字ID：如 789456123、20240615、95279527
- 英文+数字：如 Kevin_2024、Alice_88、Tom_666
- 中文+数字：如 张三123、李四888、王五2024
- emoji+文字：如 🌟小星星🌟、🔥热血青年、😎酷盖
- 情绪表达：如 不想上班、想退休、今天也要加油鸭
- 纯英文：如 SunnyDay、MoonLight、HappyLife
- 食物相关：如 奶茶爱好者、火锅小王子、螺蛳粉信徒
- 动物相关：如 喵星人、狗狗铲屎官、兔叽本叽
- 地域+身份：如 北京小张、上海阿花、广东靓仔
- 自嘲搞笑：如 秃头少女、搬砖小工、社恐本恐
- 文艺风：如 樱花树下、旧时光、诗和远方
- 游戏/动漫：如 王者荣耀玩家、海贼王迷、二次元宅
- 简单名字：如 小明、小红、阿强
- 带符号：如 ······、____、~~
- 纯字母缩写：如 abc123、xyz789

要求：
1. 用户名必须按上述风格多样化生成，不要全部用"XX老李"、"XX市民"这种假名格式
2. 简介要符合用户身份，5-15字，真实感强
3. IP 属地从以下省份中选择：{', '.join(random.sample(PROVINCES, 15))}
4. 评论内容要围绕新闻主题，30-80字，口语化，像真人发的
5. 情绪标签只能是：愤怒、支持、质疑、围观、分析
6. 粉丝数要合理：普通用户 50-5000，大V 1万-50万
7. 每个用户要有不同的性格、观点和说话风格
8. 不要出现"示例"、"测试"等字眼

输出严格的 JSON 数组，不要任何 markdown 代码块标记，不要任何其他文字：
[
  {{"username": "...", "bio": "...", "ip_location": "...", "content": "...", "followers": 1200, "emotion": "愤怒"}},
  ...
]
"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个社交媒体用户数据生成专家，只输出纯 JSON 格式数据，不要任何 markdown 标记。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2000,
        "temperature": 0.9,
    }

    try:
        resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            print(f"[LLM] API error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        raw = data["choices"][0]["message"]["content"]

        # 提取 JSON（兼容代码块包裹的情况）
        json_text = raw.strip()
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        users = json.loads(json_text)
        if not isinstance(users, list):
            print("[LLM] 返回的不是数组")
            return []

        # 补充平台信息和随机字段
        result = []
        for u in users:
            username = u.get("username", "")
            if not username:
                continue
            followers = max(50, min(500000, int(u.get("followers", random.randint(100, 5000)))))
            result.append({
                "username": username,
                "bio": u.get("bio", "")[:30],
                "ip_location": u.get("ip_location", random.choice(PROVINCES)),
                "content": u.get("content", "")[:200],
                "followers": followers,
                "emotion": u.get("emotion", "围观"),
                "platform": platform,
                "register_date": _random_register_date(),
                "following_count": max(10, int(followers * random.uniform(0.05, 0.4))),
                "posts_count": random.randint(10, 5000),
                "avatar_hash": hashlib.md5(username.encode()).hexdigest()[:16],
                "nickname_hash": hashlib.md5((username + "nick").encode()).hexdigest()[:16],
            })

        print(f"[LLM] 成功生成 {len(result)} 个逼真用户")
        return result

    except json.JSONDecodeError as e:
        print(f"[LLM] JSON 解析失败: {e}, raw={raw[:200]}")
        return []
    except Exception as e:
        print(f"[LLM] 生成异常: {e}")
        return []
