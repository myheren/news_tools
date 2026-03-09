import feedparser
import requests
from datetime import datetime, timedelta
import pytz
import time
import os

# 配置区
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") # 从环境变量获取Token
RSS_URLS = [
    "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://rsshub.app/jiqizhixin/dailynews"
]

def get_recent_ai_news():
    # 设置时区（北京时间）
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    one_day_ago = now - timedelta(days=1)
    
    news_list = []
    
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                # 解析发布时间
                if hasattr(entry, 'published_parsed'):
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
                    pub_time = pub_time.astimezone(tz)
                    
                    # 过滤过去24小时内的新闻
                    if pub_time >= one_day_ago:
                        news_list.append({
                            'title': entry.title,
                            'link': entry.link,
                            'time': pub_time.strftime("%Y-%m-%d %H:%M")
                        })
        except Exception as e:
            print(f"抓取 {url} 失败: {e}")
            
    return news_list

def send_wechat_notification(news_list):
    if not PUSHPLUS_TOKEN:
        print("未设置 PUSHPLUS_TOKEN，跳过推送")
        return

    if not news_list:
        content = "今日暂无新的AI资讯。"
    else:
        # 构建Markdown格式的内容
        content = "### 🤖 你的每日AI新闻速递\n\n"
        for i, news in enumerate(news_list, 1):
            content += f"**{i}. [{news['title']}]({news['link']})**\n"
            content += f"🕒 发布时间: {news['time']}\n\n"
            
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"AI每日早报 {datetime.now().strftime('%Y-%m-%d')}",
        "content": content,
        "template": "markdown"
    }
    
    response = requests.post("http://www.pushplus.plus/send", json=payload)
    print("推送结果:", response.text)

if __name__ == "__main__":
    print("开始抓取AI新闻...")
    recent_news = get_recent_ai_news()
    print(f"共抓取到 {len(recent_news)} 条新闻，开始推送...")
    send_wechat_notification(recent_news)
    print("任务完成！")