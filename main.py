import feedparser
import requests
from datetime import datetime, timedelta
import pytz
import time
import os
from openai import OpenAI

# ================= 配置区 =================
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com") 
MODEL_NAME = "deepseek-chat"

RSS_URLS = [
    "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://rsshub.app/jiqizhixin/dailynews"
]

# --- 新增的限制参数 ---
MAX_NEWS_FOR_AI = 40     # 最多喂给大模型多少条新闻（控制Token成本）
MAX_LINKS_TO_SHOW = 15   # 微信底部最多附带多少个原始链接（防止超字数）
# =========================================

def get_recent_ai_news():
    """抓取过去24小时的新闻，并按时间倒序排列"""
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    one_day_ago = now - timedelta(days=1)
    
    news_list = []
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
                    pub_time = pub_time.astimezone(tz)
                    
                    if pub_time >= one_day_ago:
                        news_list.append({
                            'title': entry.title,
                            'link': entry.link,
                            'time': pub_time.strftime("%Y-%m-%d %H:%M")
                        })
        except Exception as e:
            print(f"抓取 {url} 失败: {e}")
            
    # 按时间倒序排序（最新的排前面），并截取前 MAX_NEWS_FOR_AI 条
    news_list.sort(key=lambda x: x['time'], reverse=True)
    return news_list[:MAX_NEWS_FOR_AI]

def summarize_news_with_ai(news_list):
    """调用大模型进行总结"""
    if not AI_API_KEY:
        print("未配置 AI_API_KEY，跳过 AI 总结")
        return None

    news_titles = "\n".join([f"- {news['title']}" for news in news_list])
    
    prompt = f"""
    你是一个资深的 AI 科技媒体主编。请根据以下过去 24 小时内抓取的 AI 领域新闻标题，帮我写一份「每日 AI 晨报」。
    
    要求：
    1. 剔除重复的、无聊的、价值不大的新闻，只挑选 3-5 件最重要的大事。
    2. 用通俗、凝练的语言总结，最好带有一定的洞察。
    3. 严格按照以下 Markdown 格式输出：
       🌟 **今日行业观察**
       （用一句话总结今天 AI 圈的整体趋势或大新闻）
       
       🔥 **重要资讯速览**
       1. **[关键词]** 新闻事件总结...
       2. **[关键词]** 新闻事件总结...
       3. **[关键词]** 新闻事件总结...
       
       💡 **编辑点评**
       （一句话简短的感受或吐槽）

    以下是今天抓取到的新闻素材：
    {news_titles}
    """

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个专业的AI科技编辑。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 总结失败: {e}")
        return None

def send_wechat_notification(news_list, ai_summary):
    """推送微信消息"""
    if not PUSHPLUS_TOKEN:
        print("未设置 PUSHPLUS_TOKEN，跳过推送")
        return

    if not news_list:
        content = "今日暂无新的AI资讯。"
    else:
        content = "### 🤖 你的每日 AI 晨报\n\n"
        
        if ai_summary:
            content += f"{ai_summary}\n\n---\n\n"
            content += "<details><summary>👉 点击查看最新原始新闻链接</summary>\n\n"
        else:
            content += "*(AI 总结生成失败，以下为今日原始新闻)*\n\n"
            
        # 限制底部的原始链接数量，避免超字数
        for i, news in enumerate(news_list[:MAX_LINKS_TO_SHOW], 1):
            content += f"{i}. [{news['title']}]({news['link']})\n"
            
        if len(news_list) > MAX_LINKS_TO_SHOW:
            content += f"\n*(为了阅读体验，已省略其余 {len(news_list) - MAX_LINKS_TO_SHOW} 条相似新闻)*\n"
        
        if ai_summary:
            content += "</details>\n"
            
    # 【终极保险】强制检查字符串长度，PushPlus 限制为 2万字
    # 这里保守截取前 18000 个字符
    if len(content) > 18000:
        content = content[:18000] + "\n\n...（内容超长，已被系统截断）..."

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"AI每日早报 {datetime.now().strftime('%Y-%m-%d')}",
        "content": content,
        "template": "markdown"
    }
    
    response = requests.post("http://www.pushplus.plus/send", json=payload)
    print("推送结果:", response.text)

if __name__ == "__main__":
    print("1. 开始抓取AI新闻...")
    recent_news = get_recent_ai_news()
    print(f"成功筛选出最新的 {len(recent_news)} 条新闻用于分析。")
    
    ai_summary = None
    if recent_news:
        print("2. 开始调用 AI 进行总结...")
        ai_summary = summarize_news_with_ai(recent_news)
        print("AI 总结完成！" if ai_summary else "AI 总结失败。")
        
    print("3. 开始推送到微信...")
    send_wechat_notification(recent_news, ai_summary)
    print("任务全部完成！")
