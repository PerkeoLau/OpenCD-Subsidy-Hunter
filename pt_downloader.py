import os
import time
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup
import re
import schedule

# ================= 配置区域 =================
BASE_URL = 'https://www.open.cd/torrents.php?seeders=6'
DOWNLOAD_DIR = './torrents'
DB_FILE = 'downloaded_torrents.db'
LOG_FILE = 'pt_downloader.log'

# 填入你刚才转换好的 Cookie 字典
COOKIE_STRING = "your cookie"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15',
    'Cookie': COOKIE_STRING
}
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS downloaded 
                      (torrent_id TEXT PRIMARY KEY, title TEXT, size TEXT, download_time DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def convert_to_mb(size_str):
    match = re.search(r'([\d.]+)\s*(MB|GB|KB)', size_str, re.IGNORECASE)
    if not match: return 0.0
    val, unit = float(match.group(1)), match.group(2).upper()
    return val * 1024 if unit == 'GB' else val if unit == 'MB' else val / 1024

def get_max_page(html):
    """从页面底部的分页链接中提取最大页码"""
    soup = BeautifulSoup(html, 'html.parser')
    # 查找包含 page= 的链接
    page_links = soup.find_all('a', href=re.compile(r'page=\d+'))
    max_p = 0
    for link in page_links:
        match = re.search(r'page=(\d+)', link['href'])
        if match:
            max_p = max(max_p, int(match.group(1)))
    return max_p

def process_page(url, conn):
    """处理单个页面的种子抓取"""
    cursor = conn.cursor()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='torrents')
        if not table: return
        
        rows = table.find_all('tr')[1:] # 跳过表头
        for row in rows:
            # 1. 识别 Free 标签
            if not (row.find('img', class_='pro_free') or row.find('img', alt='Free')):
                continue

            # 2. 获取 ID 和下载链接
            dl_tag = row.find('a', href=re.compile(r'download\.php\?id=\d+'))
            if not dl_tag: continue
            t_id = re.search(r'id=(\d+)', dl_tag['href']).group(1)
            dl_url = 'https://www.open.cd/' + dl_tag['href']

            # 3. 获取标题
            title_tag = row.find('a', href=re.compile(r'details\.php\?id='))
            title = title_tag.get('title') or title_tag.text

            # 4. 获取大小并过滤 (300MB - 400MB)
            size_text = ""
            for td in row.find_all('td'):
                if 'MB' in td.text or 'GB' in td.text:
                    size_text = td.text.strip()
                    break
            
            if 300 <= convert_to_mb(size_text) <= 400:
                # 5. 查重
                cursor.execute("SELECT 1 FROM downloaded WHERE torrent_id=?", (t_id,))
                if cursor.fetchone(): continue

                # 6. 下载
                logging.info(f"下载中: {title[:30]} ({size_text})")
                t_resp = requests.get(dl_url, headers=HEADERS)
                with open(os.path.join(DOWNLOAD_DIR, f"{t_id}.torrent"), 'wb') as f:
                    f.write(t_resp.content)
                
                cursor.execute("INSERT INTO downloaded (torrent_id, title, size) VALUES (?, ?, ?)", (t_id, title, size_text))
                conn.commit()
                time.sleep(20) # 下载间隔

    except Exception as e:
        logging.error(f"处理页面 {url} 失败: {e}")

def main_job():
    logging.info("任务启动...")
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)
    conn = init_db()

    try:
        # 先抓取第 0 页获取总页数
        first_resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
        max_page = get_max_page(first_resp.text)
        logging.info(f"检测到最大页数: {max_page}")

        # 遍历所有页面 (从 0 到 max_page)
        for p in range(max_page + 1):
            page_url = f"{BASE_URL}&page={p}"
            logging.info(f"正在扫描第 {p} 页...")
            process_page(page_url, conn)
            time.sleep(20) # 页面跳转间隔，防止被 Ban

    finally:
        conn.close()
        logging.info("本次全量扫描结束。")

if __name__ == "__main__":
    main_job()