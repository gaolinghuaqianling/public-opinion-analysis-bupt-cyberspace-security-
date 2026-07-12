# -*- coding: utf-8 -*-
"""
服务层模块
==========================================================
提供 NLP 工具、情感分析、事件处理等核心服务功能。

子模块:
    - nlp_tools:          NLP 基础工具集（分词、关键词提取、SimHash、正文提取）
    - sentiment_analyzer: 情感倾向分析（SnowNLP 中文情感分析）
    - event_processor:    事件处理核心（串联采集→分析→聚合→入库）
==========================================================
"""

from app.services.nlp_tools import (
    STOP_WORDS,
    is_valid_keyword,
    segment_text,
    extract_keywords,
    compute_tfidf_for_corpus,
    simhash,
    simhash_distance,
    is_similar_text,
    find_similar_in_list,
    extract_main_content,
    get_text_embedding,
    get_batch_embeddings,
    compute_semantic_similarity,
    find_similar_texts,
    expand_keywords_semantic,
)

from app.services.sentiment_analyzer import (
    analyze_sentiment,
    analyze_batch,
    classify_sentiment,
    compute_event_sentiment,
)

from app.services.event_processor import (
    process_new_news,
    create_event_analysis,
    get_related_news_for_event,
    compute_platform_coverage,
)

__all__ = [
    # NLP 工具
    "STOP_WORDS",
    "is_valid_keyword",
    "segment_text",
    "extract_keywords",
    "compute_tfidf_for_corpus",
    "simhash",
    "simhash_distance",
    "is_similar_text",
    "find_similar_in_list",
    "extract_main_content",
    "get_text_embedding",
    "get_batch_embeddings",
    "compute_semantic_similarity",
    "find_similar_texts",
    "expand_keywords_semantic",
    # 情感分析
    "analyze_sentiment",
    "analyze_batch",
    "classify_sentiment",
    "compute_event_sentiment",
    # 事件处理
    "process_new_news",
    "create_event_analysis",
    "get_related_news_for_event",
    "compute_platform_coverage",
]
