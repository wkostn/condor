"""News Reader Global Routine - Fetch raw news from multiple sources.

This routine fetches news for specific assets from CoinTelegraph, CoinMarketCap,
CoinDesk, and X/Twitter. It outputs RAW text — interpretation is the LLM's job.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.2

Sources:
- CoinTelegraph: RSS feed polling (partnerships, regulations, developments)
- CoinMarketCap: REST API (project news, price alerts, market cap data)
- CoinDesk: RSS feed polling (professional analysis, macro context)
- X/Twitter: API (real-time psychology, influencer posts, trending)

Output: List[NewsDigest] with raw text for LLM interpretation
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from dataclasses import dataclass
import xml.etree.ElementTree as ET

import aiohttp
from pydantic import BaseModel, Field, field_validator
from telegram.ext import ContextTypes

from routines.base import RoutineResult

logger = logging.getLogger(__name__)

COINTELEGRAPH_RSS = "https://cointelegraph.com/rss"
COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"
COINMARKETCAP_API = "https://api.coinmarketcap.com/data-api/v3/news/list"


@dataclass
class NewsDigest:
    """Single news item for an asset."""
    headline: str
    source: str  # "cointelegraph", "coinmarketcap", "coindesk", "x_twitter"
    full_text: str  # Raw article/post text for LLM interpretation
    timestamp: datetime
    url: str


class Config(BaseModel):
    """Configuration for news_reader routine."""

    assets: list[str] = Field(
        default_factory=lambda: [
            "BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "MATIC", "LINK", "UNI", "ATOM"
        ],
        description="List of asset symbols to fetch news for (top 10 Hyperliquid volume)",
    )
    lookback_hours: int = Field(
        default=24,
        description="How many hours back to fetch news",
    )
    max_articles_per_source: int = Field(
        default=10,
        description="Maximum articles to fetch per source per asset",
    )
    sources: list[str] = Field(
        default_factory=lambda: ["cointelegraph", "coindesk", "coinmarketcap"],
        description="Which sources to query (exclude 'x_twitter' if no API key)",
    )

    @field_validator("assets", "sources", mode="before")
    @classmethod
    def normalize_lists(cls, v):
        """Convert None to empty list or default for web UI compatibility."""
        if v is None:
            return []
        return v


async def _fetch_cointelegraph_news(assets: list[str], lookback_hours: int, max_articles: int) -> list[NewsDigest]:
    """Fetch news from CoinTelegraph RSS feed."""
    news_items = []
    cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(COINTELEGRAPH_RSS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinTelegraph RSS returned status {resp.status}")
                    return news_items
                text = await resp.text()
        
        # Parse RSS manually using xml.etree
        try:
            root = ET.fromstring(text)
            items = root.findall('.//item')
            
            for item in items[:max_articles * len(assets)]:
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')
                pub_elem = item.find('pubDate')
                
                if title_elem is None or link_elem is None:
                    continue
                
                title = title_elem.text or ""
                link = link_elem.text or ""
                summary = desc_elem.text if desc_elem is not None else ""
                
                # Parse pubDate (RFC 822 format)
                if pub_elem is not None and pub_elem.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_datetime = parsedate_to_datetime(pub_elem.text)
                        pub_datetime = pub_datetime.replace(tzinfo=None)
                    except:
                        continue
                else:
                    continue
                
                if pub_datetime < cutoff_time:
                    continue
                
                # Check if any asset is mentioned in title or summary
                text_content = f"{title} {summary}".upper()
                for asset in assets:
                    if asset.upper() in text_content or f"{asset}USDT" in text_content:
                        news_items.append(NewsDigest(
                            headline=title,
                            source="cointelegraph",
                            full_text=summary,
                            timestamp=pub_datetime,
                            url=link,
                        ))
                        break
        
        except ET.ParseError as e:
            logger.error(f"Failed to parse CoinTelegraph RSS XML: {e}")
            return news_items
        
        logger.info(f"Fetched {len(news_items)} articles from CoinTelegraph")
    
    except Exception as exc:
        logger.error(f"Failed to fetch CoinTelegraph news: {exc}")
    
    return news_items


async def _fetch_coindesk_news(assets: list[str], lookback_hours: int, max_articles: int) -> list[NewsDigest]:
    """Fetch news from CoinDesk RSS feed."""
    news_items = []
    cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(COINDESK_RSS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinDesk RSS returned status {resp.status}")
                    return news_items
                text = await resp.text()
        
        # Parse RSS manually
        try:
            root = ET.fromstring(text)
            items = root.findall('.//item')
            
            for item in items[:max_articles * len(assets)]:
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')
                pub_elem = item.find('pubDate')
                
                if title_elem is None or link_elem is None:
                    continue
                
                title = title_elem.text or ""
                link = link_elem.text or ""
                summary = desc_elem.text if desc_elem is not None else ""
                
                # Parse pubDate
                if pub_elem is not None and pub_elem.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_datetime = parsedate_to_datetime(pub_elem.text)
                        pub_datetime = pub_datetime.replace(tzinfo=None)
                    except:
                        continue
                else:
                    continue
                
                if pub_datetime < cutoff_time:
                    continue
                
                # Check if any asset is mentioned
                text_content = f"{title} {summary}".upper()
                for asset in assets:
                    if asset.upper() in text_content or f"{asset}USDT" in text_content:
                        news_items.append(NewsDigest(
                            headline=title,
                            source="coindesk",
                            full_text=summary,
                            timestamp=pub_datetime,
                            url=link,
                        ))
                        break
        
        except ET.ParseError as e:
            logger.error(f"Failed to parse CoinDesk RSS XML: {e}")
            return news_items
        
        logger.info(f"Fetched {len(news_items)} articles from CoinDesk")
    
    except Exception as exc:
        logger.error(f"Failed to fetch CoinDesk news: {exc}")
    
    return news_items


async def _fetch_coinmarketcap_news(assets: list[str], lookback_hours: int, max_articles: int) -> list[NewsDigest]:
    """Fetch news from CoinMarketCap API."""
    news_items = []
    
    try:
        # Note: CMC API may require authentication in production
        # For now, using public endpoint
        async with aiohttp.ClientSession() as session:
            params = {
                "category": "all",
                "size": max_articles,
            }
            async with session.get(COINMARKETCAP_API, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    articles = data.get("data", {}).get("items", [])
                    
                    cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
                    
                    for article in articles:
                        title = article.get("title", "")
                        subtitle = article.get("subtitle", "")
                        url = article.get("url", "")
                        released_at = article.get("releasedAt")
                        
                        if not released_at:
                            continue
                        
                        pub_datetime = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
                        
                        if pub_datetime < cutoff_time:
                            continue
                        
                        # Check if any asset is mentioned
                        text_content = f"{title} {subtitle}".upper()
                        for asset in assets:
                            if asset.upper() in text_content:
                                news_items.append(NewsDigest(
                                    headline=title,
                                    source="coinmarketcap",
                                    full_text=f"{title}. {subtitle}",
                                    timestamp=pub_datetime.replace(tzinfo=None),
                                    url=url,
                                ))
                                break
        
        logger.info(f"Fetched {len(news_items)} articles from CoinMarketCap")
    
    except Exception as exc:
        logger.error(f"Failed to fetch CoinMarketCap news: {exc}")
    
    return news_items


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Fetch raw news for specified assets from multiple sources."""
    
    all_news = []
    
    # Fetch from all enabled sources in parallel
    tasks = []
    
    if "cointelegraph" in config.sources:
        tasks.append(_fetch_cointelegraph_news(config.assets, config.lookback_hours, config.max_articles_per_source))
    
    if "coindesk" in config.sources:
        tasks.append(_fetch_coindesk_news(config.assets, config.lookback_hours, config.max_articles_per_source))
    
    if "coinmarketcap" in config.sources:
        tasks.append(_fetch_coinmarketcap_news(config.assets, config.lookback_hours, config.max_articles_per_source))
    
    # Note: X/Twitter requires API keys - implement when available
    if "x_twitter" in config.sources:
        logger.warning("X/Twitter news fetching not yet implemented (requires API keys)")
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Flatten results
    for result in results:
        if isinstance(result, list):
            all_news.extend(result)
        elif isinstance(result, Exception):
            logger.error(f"News fetch task failed: {result}")
    
    if not all_news:
        return "No news found for specified assets"
    
    # Sort by timestamp (newest first)
    all_news.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Format output
    summary_lines = [f"Found {len(all_news)} news articles for {', '.join(config.assets)}:"]
    
    for news in all_news[:10]:  # Show first 10 in summary
        time_ago = (datetime.now() - news.timestamp).total_seconds() / 3600
        summary_lines.append(
            f"  • [{news.source}] {news.headline} ({time_ago:.1f}h ago)"
        )
    
    if len(all_news) > 10:
        summary_lines.append(f"  ... and {len(all_news) - 10} more")
    
    summary = "\n".join(summary_lines)
    
    # Prepare table data
    table_data = []
    for news in all_news:
        table_data.append({
            "timestamp": news.timestamp.isoformat(),
            "source": news.source,
            "headline": news.headline,
            "url": news.url,
            "full_text_preview": news.full_text[:200] + "..." if len(news.full_text) > 200 else news.full_text,
        })
    
    logger.info(f"news_reader: Fetched {len(all_news)} articles across {len(config.sources)} sources")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=["timestamp", "source", "headline", "url", "full_text_preview"],
        sections=[
            {
                "title": "News Summary",
                "content": summary,
            }
        ],
    )
