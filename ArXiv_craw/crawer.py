import arxiv
import os
import re
import json
from datetime import datetime

# --- 配置区域 ---
KEYWORD = "Retrieval Augmented Generation" # 搜索关键词
CATEGORY = "cs.CL"                         # 领域：计算语言学
MAX_RESULTS = 100                           # 每次下载数量
SAVE_DIR = "./arxiv_papers_rag"            # 保存路径

# 确保目录存在
os.makedirs(SAVE_DIR, exist_ok=True)

def sanitize_filename(filename):
    """清洗文件名，去掉非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def run_downloader():
    # 1. 构建客户端
    client = arxiv.Client(
        page_size=100,
        delay_seconds=3.0, # 稍微慢点，防止被封 IP
        num_retries=3
    )

    # 2. 构造搜索对象 (按提交时间倒序)
    search = arxiv.Search(
        query = f'cat:{CATEGORY} AND all:"{KEYWORD}"',
        max_results = MAX_RESULTS,
        sort_by = arxiv.SortCriterion.SubmittedDate,
        sort_order = arxiv.SortOrder.Descending
    )

    print(f"开始搜索: {search.query} ...")

    # 3. 遍历结果
    results = list(client.results(search))
    print(f"找到 {len(results)} 篇论文，开始处理...")

    metadata_list = []

    for r in results:
        # --- 提取核心元数据 (为您后续的数据库做准备) ---
        paper_id = r.get_short_id()
        publish_date = r.published.strftime("%Y-%m-%d")
        safe_title = sanitize_filename(r.title)
        # 获取当前论文年份
        paper_year = r.published.year

        #if paper_year < 2024:
           #print(f"  -> 跳过 (年份 {paper_year} 太早)")
           #continue # 跳过这篇，继续下一篇
        # 构造保存的文件名： [2024-05-20] 论文标题.pdf
        pdf_filename = f"[{publish_date}] {safe_title}.pdf"
        pdf_path = os.path.join(SAVE_DIR, pdf_filename)
        
        print(f"正在处理: {r.title}...")

        # --- A. 检查是否已存在 ---
        if os.path.exists(pdf_path):
            print(f"  -> 跳过 (文件已存在)")
            continue

        # --- B. 下载 PDF ---
        else:
           try:
               r.download_pdf(dirpath=SAVE_DIR, filename=pdf_filename)
           except Exception as e:
               print(f"  -> 下载失败: {e}")
               continue

        # --- C. 收集元数据 (用于向量化) ---
        # 注意：这里的 r.summary 就是摘要，直接存下来，
        # 后续做 Embedding 时直接用这个字段，比去 PDF 里提取准确得多！
        meta = {
            "arxiv_id": paper_id,
            "title": r.title,
            "published_date": publish_date,
            "authors": [a.name for a in r.authors],
            "summary": r.summary.replace("\n", " "), # 清洗一下换行符
            "pdf_local_path": pdf_path,
            "url": r.entry_id,
            "primary_category": r.primary_category
        }
        metadata_list.append(meta)
        print(f"  -> 下载完成")

    # 4. 保存元数据记录到 JSONL 文件 (追加模式)
    json_path = os.path.join(SAVE_DIR, "metadata_log.jsonl")
    with open(json_path, "a", encoding="utf-8") as f:
        for meta in metadata_list:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    
    print(f"\n全部完成！元数据已保存至 {json_path}")

if __name__ == "__main__":
    run_downloader()