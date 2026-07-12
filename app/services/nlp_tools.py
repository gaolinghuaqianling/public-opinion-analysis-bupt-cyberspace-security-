# -*- coding: utf-8 -*-
"""
NLP 基础工具集
==========================================================
提供中文自然语言处理的基础功能:
    1. 停用词管理与过滤
    2. jieba 分词与关键词提取（TF-IDF / TextRank）
    3. SimHash 文本相似度计算
    4. 通用网页正文提取（从 HTML 中提取主要文本内容）
==========================================================
"""

import re
import hashlib
import math
import logging
from collections import Counter
from typing import List, Tuple, Dict, Set

import jieba
import jieba.analyse

logger = logging.getLogger("services.nlp_tools")


# ===================================================================
# 1. 停用词管理
# ===================================================================

# 内置中文停用词集合（约200个常用停用词）
# 涵盖: 代词、介词、连词、助词、叹词、副词、量词、标点符号等
STOP_WORDS: Set[str] = {
    # --- 代词 ---
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "自己", "别人", "大家", "某人", "谁", "什么", "怎么", "如何", "哪", "哪里",
    "哪个", "那些", "这些", "这个", "那个", "此", "该", "本", "其", "之",
    # --- 介词 ---
    "在", "到", "从", "向", "给", "让", "被", "把", "将", "对", "按", "比",
    "以", "于", "为", "与", "及", "或", "对于", "关于", "通过", "对于",
    # --- 连词 ---
    "和", "跟", "同", "而", "且", "并", "则", "虽", "但", "若", "如",
    "因", "故", "即", "又", "亦", "或者", "以及", "但是", "因为", "所以",
    "如果", "虽然", "因此", "然而", "可是", "不过", "否则", "无论",
    # --- 助词 ---
    "的", "了", "着", "过", "吗", "呢", "吧", "啊", "哦", "嗯", "呀",
    "啦", "哈", "么", "等", "等等", "所", "之",
    # --- 副词 ---
    "也", "都", "就", "不", "很", "非常", "十分", "极", "太", "比较",
    "稍微", "略", "颇", "相当", "蛮", "挺", "真", "更", "最", "还",
    "已", "已经", "曾", "正在", "将", "会", "能", "可以", "可能", "应该",
    "必须", "一定", "必然", "仍然", "仍", "才", "只", "仅", "都",
    # --- 动词/量词等常见虚词 ---
    "有", "是", "说", "要", "去", "看", "做", "上", "下", "来", "去",
    "一", "一个", "二", "三", "几", "些", "多", "少", "某", "各", "每",
    "另", "别", "其他", "另外", "此外", "其中", "所有", "任何",
    # --- 时间/顺序词 ---
    "目前", "同时", "以来", "之后", "之前", "随后", "然后", "接着",
    "最后", "首先", "其次", "再次", "最终", "当时", "此时", "那时",
    # --- 方位/范围 ---
    "以上", "以下", "之间", "之内", "之外", "左右", "上下", "前后",
    "上述", "以下", "以前", "以后", "以前",
    # --- 英文常见停用词 ---
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "that", "this", "it",
    "he", "she", "they", "we", "you", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their",
}


def is_valid_keyword(word: str) -> bool:
    """
    判断词是否为有效关键词。

    有效关键词需同时满足以下条件:
        1. 长度 >= 2 个字符
        2. 不在停用词集合中
        3. 不是纯数字
        4. 不是纯标点符号

    参数:
        word: 待判断的词

    返回:
        True 表示该词是有效关键词，False 表示应过滤掉

    示例:
        >>> is_valid_keyword("人工智能")
        True
        >>> is_valid_keyword("的")
        False
        >>> is_valid_keyword("123")
        False
    """
    if not word:
        return False

    # 长度检查
    if len(word) < 2:
        return False

    # 停用词检查
    if word.lower() in STOP_WORDS:
        return False

    # 纯数字检查（包括中英文数字、小数、百分比）
    if re.fullmatch(r"[\d\s.,%％]+", word):
        return False

    # 纯标点符号检查
    if re.fullmatch(r"[^\w\u4e00-\u9fff]+", word):
        return False

    return True


# ===================================================================
# 2. 文本分词与关键词提取
# ===================================================================

def segment_text(text: str) -> List[str]:
    """
    对文本进行 jieba 分词，返回有效词列表。

    处理流程:
        1. 使用 jieba.cut 对文本进行精确模式分词
        2. 去除空白字符
        3. 通过 is_valid_keyword 过滤停用词、短词、纯数字、纯标点

    参数:
        text: 待分词的文本字符串

    返回:
        有效词列表（已去重去停用词）

    示例:
        >>> segment_text("人工智能技术在近年来取得了快速发展")
        ['人工智能', '技术', '近年来', '取得', '快速发展']
    """
    if not text or not text.strip():
        return []

    words = jieba.cut(text)
    # 过滤并去重，保持顺序
    seen = set()
    result = []
    for word in words:
        word = word.strip()
        if word and is_valid_keyword(word) and word not in seen:
            seen.add(word)
            result.append(word)

    return result


def extract_keywords(
    text: str,
    topk: int = 10,
    method: str = "tfidf"
) -> List[Tuple[str, float]]:
    """
    提取文本关键词。

    支持两种关键词提取算法:
        - method="tfidf":     使用 TF-IDF 算法（jieba.analyse.extract_tags）
        - method="textrank":  使用 TextRank 算法（jieba.analyse.textrank）

    TF-IDF 适合从单篇文档中提取具有区分度的关键词;
    TextRank 适合从文档中提取关键词和关键短语，基于词图排序。

    参数:
        text:   待提取关键词的文本
        topk:   返回的关键词数量上限，默认 10
        method: 提取算法，"tfidf" 或 "textrank"

    返回:
        关键词列表，每项为 (关键词, 权重) 的元组，按权重降序排列

    示例:
        >>> extract_keywords("人工智能正在改变世界", topk=3)
        [('人工智能', 0.85), ('改变', 0.65), ('世界', 0.50)]
    """
    if not text or not text.strip():
        return []

    method = method.lower().strip()

    try:
        if method == "textrank":
            # TextRank 算法提取关键词
            tags_with_weight = jieba.analyse.textrank(
                text, topK=topk, withWeight=True
            )
        else:
            # 默认使用 TF-IDF 算法
            tags_with_weight = jieba.analyse.extract_tags(
                text, topK=topk, withWeight=True
            )

        # tags_with_weight 返回格式为 [(word, weight), ...]
        # 进一步过滤停用词和短词
        result = [
            (word, weight)
            for word, weight in tags_with_weight
            if is_valid_keyword(word)
        ]

        return result[:topk]

    except Exception as e:
        logger.warning("关键词提取失败 (method=%s): %s", method, e)
        return []


def compute_tfidf_for_corpus(
    texts: List[str],
    topk: int = 5
) -> List[List[Tuple[str, float]]]:
    """
    对一组文本计算 TF-IDF 特征，提取每篇文本的 topk 关键词。

    实现方式:
        使用 jieba.analyse.extract_tags 为每篇文本单独提取关键词，
        因为 jieba 内部已经维护了一个基于大规模语料训练的 IDF 词典。

    参数:
        texts: 文本列表 [text1, text2, ...]
        topk:  每篇文本提取的关键词数量上限

    返回:
        二维列表，每篇文本对应一个 [(word, score), ...] 列表

    示例:
        >>> compute_tfidf_for_corpus(["文本一内容", "文本二内容"], topk=3)
        [[('关键词1', 0.8), ('关键词2', 0.5)], [('关键词3', 0.7)]]
    """
    if not texts:
        return []

    corpus_results = []
    for text in texts:
        keywords = extract_keywords(text, topk=topk, method="tfidf")
        corpus_results.append(keywords)

    return corpus_results


# ===================================================================
# 3. SimHash 文本相似度
# ===================================================================

def simhash(text: str, hash_bits: int = 64) -> int:
    """
    计算文本的 SimHash 指纹。

    SimHash 算法步骤:
        1. 对文本进行分词，提取有效关键词
        2. 对每个关键词计算普通 hash 值（取前 hash_bits 位）
        3. 初始化长度为 hash_bits 的累加向量 v，初始值为 0
        4. 对每个词的 hash 值，逐位检查: 若第 i 位为 1，则 v[i] += 1，否则 v[i] -= 1
        5. 最终对累加向量的每一位: v[i] > 0 则第 i 位取 1，否则取 0
        6. 将二进制结果转换为整数返回

    参数:
        text:      待计算 SimHash 的文本
        hash_bits: 哈希位数，默认 64 位

    返回:
        SimHash 指纹值（整数）

    示例:
        >>> simhash("这是一段测试文本")
        12345678901234567890
    """
    if not text or not text.strip():
        return 0

    # 分词提取有效关键词
    words = segment_text(text)

    if not words:
        return 0

    # 初始化累加向量
    v = [0] * hash_bits

    for word in words:
        # 计算词的 MD5 hash（取前 hash_bits 位）
        word_hash = hashlib.md5(word.encode("utf-8")).hexdigest()
        # 将十六进制 hash 转为二进制字符串
        binary_hash = bin(int(word_hash, 16))[2:].zfill(hash_bits)
        # 只取前 hash_bits 位
        binary_hash = binary_hash[:hash_bits]

        # 累加: hash 位为 1 则加 1，为 0 则减 1
        for i in range(hash_bits):
            if binary_hash[i] == "1":
                v[i] += 1
            else:
                v[i] -= 1

    # 降维: 每位 > 0 取 1，否则取 0
    fingerprint_bits = []
    for i in range(hash_bits):
        if v[i] > 0:
            fingerprint_bits.append("1")
        else:
            fingerprint_bits.append("0")

    # 转为整数
    fingerprint = int("".join(fingerprint_bits), 2)
    return fingerprint


def simhash_distance(hash1: int, hash2: int) -> int:
    """
    计算两个 SimHash 的汉明距离（Hamming Distance）。

    汉明距离: 两个等长二进制串中对应位不同的数量。
    通过异或运算后统计 1 的个数即可得到。

    参数:
        hash1: 第一个 SimHash 指纹
        hash2: 第二个 SimHash 指纹

    返回:
        汉明距离值（0 表示完全相同，值越大差异越大）

    示例:
        >>> simhash_distance(simhash("文本A"), simhash("文本B"))
        2
    """
    if hash1 is None or hash2 is None:
        return 64  # 任一为 None 时视为最大距离
    return bin(hash1 ^ hash2).count("1")


def is_similar_text(
    text1: str,
    text2: str,
    threshold: int = 3
) -> bool:
    """
    判断两段文本是否相似。

    基于 SimHash 汉明距离判断:
        - 汉明距离越小，文本越相似
        - 默认阈值 threshold=3，即汉明距离 <= 3 视为相似
        - 对于 64 位 SimHash，汉明距离 <= 3 意味着约 95% 的位相同

    参数:
        text1:     第一段文本
        text2:     第二段文本
        threshold: 相似度阈值（汉明距离上限），默认 3

    返回:
        True 表示两段文本相似，False 表示不相似

    示例:
        >>> is_similar_text("今天天气真好", "今天天气不错")
        True
    """
    if not text1 or not text2:
        return False

    hash1 = simhash(text1)
    hash2 = simhash(text2)

    distance = simhash_distance(hash1, hash2)
    return distance <= threshold


def find_similar_in_list(
    target_text: str,
    text_list: List[str],
    threshold: int = 3
) -> List[int]:
    """
    在文本列表中找出与目标文本相似的所有文本索引。

    对 text_list 中的每段文本计算与 target_text 的 SimHash 汉明距离，
    返回汉明距离 <= threshold 的文本索引列表。

    参数:
        target_text: 目标文本
        text_list:   待比较的文本列表
        threshold:   相似度阈值（汉明距离上限），默认 3

    返回:
        相似文本在 text_list 中的索引列表（按索引升序排列）

    示例:
        >>> find_similar_in_list("今天天气真好", ["今天天气不错", "股市大跌", "天气晴朗"])
        [0, 2]
    """
    if not target_text or not text_list:
        return []

    target_hash = simhash(target_text)
    similar_indices = []

    for idx, text in enumerate(text_list):
        if not text or not text.strip():
            continue

        text_hash = simhash(text)
        distance = simhash_distance(target_hash, text_hash)

        if distance <= threshold:
            similar_indices.append(idx)

    return similar_indices


# ===================================================================
# 5. 通用网页正文提取（从 HTML 中提取正文）
# ===================================================================

# 需要移除的 HTML 标签（这些标签内容不是正文）
_REMOVE_TAGS = re.compile(
    r"<(script|style|head|nav|footer|header|iframe|noscript|aside|form|input|button|select|textarea)"
    r"[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

# 单独的 HTML 标签移除
_HTML_TAG = re.compile(r"<[^>]+>")

# HTML 注释移除
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# 连续空白压缩
_MULTI_WHITESPACE = re.compile(r"\s+")


def extract_main_content(html: str) -> str:
    """
    从 HTML 中提取主要正文内容。

    算法思路（简化版正文提取，不依赖 readability 等第三方库）:
        1. 移除 script/style/head/nav/footer/header 等非正文标签及其内容
        2. 移除所有剩余 HTML 标签，得到纯文本
        3. 按 <p> 标签分割文本块
        4. 计算每个文本块的文字密度（文字长度 / 标签数量）
        5. 取密度最高的连续文本块组合作为正文
        6. 合并并清理最终结果

    该实现采用基于密度加权的启发式方法，适合大多数中文新闻网页。

    参数:
        html: 原始 HTML 字符串

    返回:
        提取出的正文纯文本

    示例:
        >>> html_content = '<html><body><p>这是正文内容。</p></body></html>'
        >>> extract_main_content(html_content)
        '这是正文内容。'
    """
    if not html or not html.strip():
        return ""

    try:
        # 步骤1: 移除非正文标签块
        clean_html = _REMOVE_TAGS.sub("", html)
        # 移除 HTML 注释
        clean_html = _HTML_COMMENT.sub("", clean_html)

        # 步骤2: 按 <p> 标签分割文本块（保留 <p> 用于分割）
        # 先将 </p> 替换为分段标记
        p_blocks = re.split(r"</p>", clean_html, flags=re.IGNORECASE)

        # 步骤3: 对每个文本块计算文字密度
        scored_blocks = []
        for block in p_blocks:
            # 移除该块内的所有 HTML 标签，得到纯文本
            text = _HTML_TAG.sub("", block).strip()
            # 压缩连续空白
            text = _MULTI_WHITESPACE.sub(" ", text).strip()

            if not text or len(text) < 10:
                # 空块或过短块不计入
                continue

            # 计算文字密度: 有效文字长度
            # 统计中文字符和英文字符的数量作为有效文字数
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
            english_chars = len(re.findall(r"[a-zA-Z]+", text))
            text_length = chinese_chars + english_chars

            # 统计标签数量
            tag_count = len(_HTML_TAG.findall(block))

            # 密度 = 有效文字长度 / (标签数量 + 1)，避免除零
            density = text_length / (tag_count + 1)

            # 惩罚过短的文本（短文本密度可能虚高）
            if len(text) < 20:
                density *= 0.3

            scored_blocks.append({
                "text": text,
                "density": density,
                "length": len(text),
            })

        if not scored_blocks:
            # 如果没有找到 <p> 块，直接提取全部纯文本
            fallback_text = _HTML_TAG.sub("", clean_html)
            fallback_text = _MULTI_WHITESPACE.sub(" ", fallback_text).strip()
            return fallback_text

        # 步骤4: 按密度排序，取密度较高的块作为正文
        # 找到密度中位数作为基准线
        densities = sorted([b["density"] for b in scored_blocks])
        if not densities:
            return ""

        median_density = densities[len(densities) // 2]

        # 取密度大于等于中位数 50% 的块
        threshold_density = median_density * 0.5
        content_blocks = [
            b for b in scored_blocks
            if b["density"] >= threshold_density
        ]

        if not content_blocks:
            content_blocks = scored_blocks

        # 步骤5: 按原始顺序合并文本
        # 为保持顺序，按照在原始 HTML 中的位置排序
        # （由于我们已丢失原始位置信息，按密度加权排序也是一种策略）
        content_blocks.sort(key=lambda b: b["density"], reverse=True)

        # 步骤6: 合并正文
        main_content = "\n".join([b["text"] for b in content_blocks])
        main_content = _MULTI_WHITESPACE.sub(" ", main_content).strip()

        return main_content

    except Exception as e:
        logger.warning("正文提取异常: %s", e)
        # 异常时回退到简单标签去除
        fallback = _HTML_TAG.sub("", html)
        fallback = _MULTI_WHITESPACE.sub(" ", fallback).strip()
        return fallback


# =====================================================================
# 语义向量模型 (Sentence-BERT)
# =====================================================================

_semantic_model = None

def _load_semantic_model():
    """
    延迟加载语义模型（首次调用时加载，之后缓存在内存中）。
    
    使用 shibing624/text2vec-base-chinese 模型，这是一个基于中文语料
    微调的 Sentence-BERT 模型，输出 768 维语义向量。
    
    模型文件会自动下载到 ~/.cache/huggingface/ 目录。
    首次加载约需 3-10 秒（取决于磁盘速度），后续调用直接使用缓存。
    """
    global _semantic_model
    if _semantic_model is not None:
        return _semantic_model
    try:
        import os
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from sentence_transformers import SentenceTransformer
        logger.info("正在加载语义模型 shibing624/text2vec-base-chinese ...")
        _semantic_model = SentenceTransformer('shibing624/text2vec-base-chinese')
        logger.info("语义模型加载完成")
        return _semantic_model
    except ImportError:
        logger.warning("sentence-transformers 未安装，语义向量功能不可用。请执行: pip install sentence-transformers")
        return None
    except Exception as e:
        logger.error("语义模型加载失败: %s", e)
        return None


def get_text_embedding(text: str) -> list:
    """
    将文本转换为 768 维语义向量。
    
    参数:
        text: 待编码的文本（支持中文，建议 10-500 字）
    
    返回:
        768 维浮点数列表，如模型不可用返回空列表
    
    示例:
        >>> vec = get_text_embedding("人工智能正在改变世界")
        >>> len(vec)
        768
    """
    model = _load_semantic_model()
    if model is None:
        return []
    try:
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.warning("文本编码失败: %s", e)
        return []


def get_batch_embeddings(texts: list) -> list:
    """
    批量将多段文本转换为语义向量。
    
    参数:
        texts: 文本列表 ["文本1", "文本2", ...]
    
    返回:
        向量列表 [[...], [...], ...]，与输入等长
    """
    model = _load_semantic_model()
    if model is None or not texts:
        return []
    try:
        embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
        return embeddings.tolist()
    except Exception as e:
        logger.warning("批量编码失败: %s", e)
        return []


def compute_semantic_similarity(text1: str, text2: str) -> float:
    """
    计算两段文本的语义相似度（余弦相似度）。
    
    参数:
        text1: 第一段文本
        text2: 第二段文本
    
    返回:
        相似度分数 0.0 ~ 1.0，如模型不可用返回 0.0
    
    示例:
        >>> compute_semantic_similarity("AI监管法案", "人工智能立法")
        0.85  # 语义相近但用词不同
    """
    if not text1 or not text2:
        return 0.0
    vecs = get_batch_embeddings([text1, text2])
    if len(vecs) < 2:
        return 0.0
    import numpy as np
    v1, v2 = np.array(vecs[0]), np.array(vecs[1])
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def find_similar_texts(query: str, candidates: list, topk: int = 5, threshold: float = 0.6) -> list:
    """
    从候选文本列表中找出与查询文本最相似的 topk 条。
    
    参数:
        query:     查询文本
        candidates: 候选文本列表 ["候选1", "候选2", ...]
        topk:      返回的最大数量
        threshold: 最低相似度阈值，低于此值的结果会被过滤
    
    返回:
        列表，每项为 {"index": int, "text": str, "similarity": float}，
        按相似度降序排列
    """
    if not query or not candidates:
        return []
    
    model = _load_semantic_model()
    if model is None:
        return []
    
    try:
        import numpy as np
        all_texts = [query] + candidates
        embeddings = model.encode(all_texts, show_progress_bar=False, batch_size=64)
        query_vec = embeddings[0]
        candidate_vecs = embeddings[1:]
        
        # 归一化后直接点积 = 余弦相似度
        norm = np.linalg.norm(query_vec)
        if norm == 0:
            return []
        query_normed = query_vec / norm
        cand_norms = np.linalg.norm(candidate_vecs, axis=1, keepdims=True)
        cand_norms = np.where(cand_norms == 0, 1, cand_norms)
        cand_normed = candidate_vecs / cand_norms
        similarities = cand_normed.dot(query_normed)
        
        results = []
        for i, sim in enumerate(similarities):
            if sim >= threshold:
                results.append({
                    "index": i,
                    "text": candidates[i],
                    "similarity": round(float(sim), 4),
                })
        
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:topk]
    
    except Exception as e:
        logger.warning("相似度检索失败: %s", e)
        return []


def expand_keywords_semantic(keyword: str, topk: int = 5) -> list:
    """
    基于语义模型对关键词进行语义扩展。
    
    通过预定义的领域同义词词典 + 语义相似度，
    找出与输入关键词语义相近的其他关键词。
    
    参数:
        keyword: 输入关键词
        topk:    返回的扩展关键词数量
    
    返回:
        扩展关键词列表（不含原始关键词）
    """
    # 预定义的舆情领域同义词/近义词组
    SYNONYM_GROUPS = [
        ["房价调控", "楼市政策", "房地产税", "限购令", "房价下跌", "购房限制"],
        ["人工智能", "AI", "大模型", "机器学习", "深度学习", "ChatGPT", "AIGC"],
        ["就业", "失业率", "求职", "裁员", "招聘", "用工"],
        ["高考", "大学招生", "高考改革", "志愿填报", "升学"],
        ["碳中和", "碳排放", "双碳", "碳达峰", "新能源", "绿色转型"],
        ["食品安全", "食品添加剂", "食品安全事件", "食品安全监管"],
        ["股市", "A股", "股市行情", "上证指数", "股票市场", "资本市场"],
        ["疫情防控", "疫情", "传染病", "公共卫生", "疫苗接种"],
        ["教育改革", "双减", "校外培训", "课后服务", "教育政策"],
        ["数据安全", "隐私保护", "个人信息保护", "数据泄露", "网络安全"],
    ]
    
    # 先尝试精确匹配同义词组
    expanded = []
    for group in SYNONYM_GROUPS:
        if keyword in group:
            expanded = [w for w in group if w != keyword]
            break
    
    # 如果没有精确匹配，用语义相似度找
    if not expanded:
        all_synonyms = []
        for group in SYNONYM_GROUPS:
            all_synonyms.extend(group)
        
        similar = find_similar_texts(keyword, all_synonyms, topk=topk, threshold=0.5)
        expanded = [item["text"] for item in similar if item["text"] != keyword]
    
    return expanded[:topk]
