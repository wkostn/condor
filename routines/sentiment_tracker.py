"""Sentiment Tracker Global Routine - Compute sentiment from social and news data.

This routine analyzes sentiment using VADER (Valence Aware Dictionary and sEntiment Reasoner)
and computes divergence between price action and social sentiment.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4

Metrics:
- Aggregate sentiment score (-1 to +1)
- Divergence index (price vs sentiment misalignment)
- Social volume anomaly detection

Output: Sentiment metrics per asset for market psychology assessment
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from pydantic import BaseModel, Field, field_validator
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult
from routines.news_reader import _fetch_cointelegraph_news, _fetch_coindesk_news, _fetch_coinmarketcap_news

logger = logging.getLogger(__name__)

# Simple sentiment word lists (VADER-inspired, simplified)
POSITIVE_WORDS = {
    'bullish', 'pump', 'moon', 'rocket', 'breakout', 'surge', 'rally', 'gain',
    'profit', 'win', 'high', 'up', 'rise', 'grow', 'strong', 'boom', 'success',
    'positive', 'buy', 'long', 'partnership', 'adoption', 'innovation', 'upgrade',
}

NEGATIVE_WORDS = {
    'bearish', 'dump', 'crash', 'collapse', 'drop', 'fall', 'loss', 'down',
    'decline', 'weak', 'sell', 'short', 'scam', 'hack', 'breach', 'ban',
    'regulation', 'lawsuit', 'fraud', 'risk', 'fear', 'panic', 'dip', 'correction',
}

INTENSIFIERS = {'very', 'extremely', 'highly', 'super', 'massive', 'huge', 'major'}
NEGATIONS = {'not', 'no', 'never', 'neither', 'nobody', 'nothing', 'nowhere'}


class Config(BaseModel):
    """Configuration for sentiment_tracker routine."""

    assets: list[str] = Field(
        default_factory=lambda: [
            "BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "MATIC", "LINK", "UNI", "ATOM"
        ],
        description="List of asset symbols to analyze (top 10 Hyperliquid volume)",
    )
    lookback_hours: int = Field(
        default=24,
        description="Hours to lookback for sentiment analysis",
    )
    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Connector for price data",
    )

    @field_validator("assets", mode="before")
    @classmethod
    def normalize_assets(cls, v):
        """Convert None to empty list for web UI compatibility."""
        return v if v is not None else []
    social_volume_threshold: float = Field(
        default=2.0,
        description="Z-score threshold for social volume anomaly (2.0 = 2 std devs)",
    )


def _compute_sentiment_score(text: str) -> float:
    """Compute simple VADER-inspired sentiment score from text.
    
    Returns float between -1.0 (very negative) and +1.0 (very positive).
    """
    if not text:
        return 0.0
    
    words = text.lower().split()
    
    positive_count = 0
    negative_count = 0
    
    for i, word in enumerate(words):
        # Check for negation in previous words
        negated = False
        if i > 0 and words[i-1] in NEGATIONS:
            negated = True
        
        # Check for intensifier in previous words
        intensified = False
        if i > 0 and words[i-1] in INTENSIFIERS:
            intensified = True
        
        # Score the word
        if word in POSITIVE_WORDS:
            score = 2.0 if intensified else 1.0
            if negated:
                negative_count += score
            else:
                positive_count += score
        
        elif word in NEGATIVE_WORDS:
            score = 2.0 if intensified else 1.0
            if negated:
                positive_count += score
            else:
                negative_count += score
    
    total = positive_count + negative_count
    
    if total == 0:
        return 0.0
    
    # Normalize to -1 to +1
    sentiment = (positive_count - negative_count) / total
    return max(-1.0, min(1.0, sentiment))


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Analyze sentiment for specified assets from news and compute divergence."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch news for sentiment analysis
    news_tasks = [
        _fetch_cointelegraph_news(config.assets, config.lookback_hours, 20),
        _fetch_coindesk_news(config.assets, config.lookback_hours, 20),
        _fetch_coinmarketcap_news(config.assets, config.lookback_hours, 20),
    ]
    
    news_results = await asyncio.gather(*news_tasks, return_exceptions=True)
    
    all_news = []
    for result in news_results:
        if isinstance(result, list):
            all_news.extend(result)
    
    if not all_news:
        return "No news data available for sentiment analysis"
    
    # Group news by asset
    asset_news = {asset: [] for asset in config.assets}
    
    for news_item in all_news:
        text_content = f"{news_item.headline} {news_item.full_text}".upper()
        for asset in config.assets:
            if asset.upper() in text_content:
                asset_news[asset].append(news_item)
    
    # Analyze sentiment per asset
    summary_lines = ["Sentiment Analysis:"]
    table_data = []
    
    for asset in config.assets:
        news_list = asset_news.get(asset, [])
        
        if not news_list:
            logger.info(f"No news found for {asset}, skipping")
            continue
        
        # Compute aggregate sentiment
        sentiments = []
        for news in news_list:
            text = f"{news.headline} {news.full_text}"
            sentiment = _compute_sentiment_score(text)
            sentiments.append(sentiment)
        
        avg_sentiment = statistics.mean(sentiments) if sentiments else 0.0
        sentiment_std = statistics.pstdev(sentiments) if len(sentiments) > 1 else 0.0
        
        # Fetch price data to compute divergence
        try:
            pair = f"{asset}-USDT"
            candles_result = await client.market_data.get_candles(
                connector_name=config.connector,
                trading_pair=pair,
                interval="1h",
                max_records=24,
            )
            
            if isinstance(candles_result, dict):
                candles = candles_result.get("data", [])
            elif isinstance(candles_result, list):
                candles = candles_result
            else:
                candles = []
            
            if candles and len(candles) >= 2:
                first_close = float(candles[0]["close"])
                last_close = float(candles[-1]["close"])
                price_change_pct = ((last_close - first_close) / first_close) * 100
                
                # Compute divergence: when sentiment and price move in opposite directions
                # Positive divergence: price down but sentiment up (buying opportunity?)
                # Negative divergence: price up but sentiment down (distribution?)
                
                if avg_sentiment > 0.2 and price_change_pct < -2.0:
                    divergence_type = "POSITIVE"  # Bullish sentiment, price down
                    divergence_strength = abs(avg_sentiment * price_change_pct) / 10
                elif avg_sentiment < -0.2 and price_change_pct > 2.0:
                    divergence_type = "NEGATIVE"  # Bearish sentiment, price up
                    divergence_strength = abs(avg_sentiment * price_change_pct) / 10
                else:
                    divergence_type = "ALIGNED"
                    divergence_strength = 0.0
                
                divergence_index = min(divergence_strength, 1.0)
            else:
                price_change_pct = 0.0
                divergence_type = "UNKNOWN"
                divergence_index = 0.0
        
        except Exception as e:
            logger.warning(f"Failed to fetch price data for {asset}: {e}")
            price_change_pct = 0.0
            divergence_type = "UNKNOWN"
            divergence_index = 0.0
        
        # Social volume anomaly (simple: count of mentions vs average)
        mention_count = len(news_list)
        social_volume_anomaly = mention_count > (statistics.mean([len(asset_news[a]) for a in config.assets]) + config.social_volume_threshold * 5)
        
        # Format sentiment label
        if avg_sentiment > 0.5:
            sentiment_label = "VERY BULLISH"
        elif avg_sentiment > 0.2:
            sentiment_label = "BULLISH"
        elif avg_sentiment > -0.2:
            sentiment_label = "NEUTRAL"
        elif avg_sentiment > -0.5:
            sentiment_label = "BEARISH"
        else:
            sentiment_label = "VERY BEARISH"
        
        summary_lines.append(
            f"  {asset}:\n"
            f"    Sentiment: {sentiment_label} ({avg_sentiment:+.3f})\n"
            f"    Price Change: {price_change_pct:+.2f}%\n"
            f"    Divergence: {divergence_type} (index: {divergence_index:.2f})\n"
            f"    News Count: {mention_count} articles\n"
            f"    Social Volume Anomaly: {'YES ⚠️' if social_volume_anomaly else 'NO'}"
        )
        
        table_data.append({
            "asset": asset,
            "sentiment_score": round(avg_sentiment, 3),
            "sentiment_label": sentiment_label,
            "sentiment_std": round(sentiment_std, 3),
            "price_change_24h_pct": round(price_change_pct, 2),
            "divergence_type": divergence_type,
            "divergence_index": round(divergence_index, 2),
            "news_count": mention_count,
            "social_volume_anomaly": social_volume_anomaly,
        })
    
    summary = "\n".join(summary_lines)
    
    logger.info(f"sentiment_tracker: Analyzed sentiment for {len(table_data)} assets from {len(all_news)} news articles")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=[
            "asset", "sentiment_score", "sentiment_label", "sentiment_std",
            "price_change_24h_pct", "divergence_type", "divergence_index",
            "news_count", "social_volume_anomaly"
        ],
        sections=[
            {
                "title": "Sentiment Analysis",
                "content": summary,
            }
        ],
    )
