import os
import json
import time
import logging
import psycopg2
from psycopg2 import pool, extras
from psycopg2.extras import Json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm  # 进度条库

# --- 配置区域 ---
DB_CONFIG = {
    "dbname": "pacoman",
    "user": "pacoman",
    "password": "114514",
    "host": "localhost",
    "port": "5433"
}

# Ollama 设置
OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "qwen3-embedding:0.6b"  # 您指定的模型名称
BATCH_SIZE = 50       # 每积攒多少篇写入一次数据库
MAX_WORKERS = 4       # 并发线程数 (建议设置为 CPU 核心数或 GPU 显存允许的并发数)
METADATA_FILE = "metadata_log.jsonl" # 您的数据源文件

# 日志设置
logging.basicConfig(
    filename='ingest_error.log', 
    level=logging.ERROR,
    format='%(asctime)s - %(message)s'
)

# --- 数据库连接池 ---
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1, maxconn=MAX_WORKERS + 2, **DB_CONFIG
    )
except Exception as e:
    print(f"❌ 无法连接数据库: {e}")
    exit(1)

def get_db_conn():
    return db_pool.getconn()

def release_db_conn(conn):
    db_pool.putconn(conn)

# --- 核心功能函数 ---

def check_model_dimension():
    """自动检测模型维度并建表"""
    print(f"🔍 正在检测模型 '{OLLAMA_MODEL}' 的维度...")
    try:
        resp = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": "test"})
        resp.raise_for_status()
        dim = len(resp.json()['embedding'])
        print(f"✅ 模型维度: {dim}")
    except Exception as e:
        print(f"❌ 无法连接 Ollama (请检查 ollama serve 是否启动): {e}")
        exit(1)

    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # 创建/更新表结构
        cur.execute("""
            CREATE TABLE IF NOT EXISTS papers_meta (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                arxiv_id VARCHAR(50) UNIQUE NOT NULL,
                title TEXT NOT NULL,
                authors TEXT[],
                published_date DATE,
                pdf_local_path TEXT,
                extracted_insights JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # 动态创建向量表
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS papers_embeddings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                paper_id UUID REFERENCES papers_meta(id) ON DELETE CASCADE,
                embedding_type VARCHAR(50),
                text_content TEXT,
                embedding vector({dim})
            );
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_papers_vec_hnsw 
            ON papers_embeddings USING hnsw (embedding vector_cosine_ops);
        """)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        release_db_conn(conn)
    
    return dim

def fetch_existing_ids():
    """获取数据库中已有的 arxiv_id，用于断点续传"""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT arxiv_id FROM papers_meta")
    existing = {row[0] for row in cur.fetchall()}
    cur.close()
    release_db_conn(conn)
    return existing

def process_single_paper(line_data):
    """
    单个任务函数：接收一行 JSON 数据，调用 Ollama 生成向量
    返回: (success_bool, data_dict_for_db, error_msg)
    """
    try:
        meta = json.loads(line_data)
        arxiv_id = meta.get('arxiv_id')
        title = meta.get('title')
        
        # 提取需要向量化的文本 (这里假设您已经在 metadata 里存了 summary)
        # 如果没有 summary，可能需要 fall back 到 core_problem
        text_to_embed = meta.get('summary', meta.get('title', ''))
        
        if not text_to_embed:
            return False, None, f"Skipped {arxiv_id}: No text to embed"

        # 调用 Ollama
        response = requests.post(
            OLLAMA_URL, 
            json={"model": OLLAMA_MODEL, "prompt": text_to_embed},
            timeout=60 # 设置超时防止卡死
        )
        response.raise_for_status()
        embedding = response.json().get('embedding')

        # 构造预备入库的数据包
        db_payload = {
            "meta": {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": meta.get('authors', []),
                "published_date": meta.get('published_date'),
                "pdf_local_path": meta.get('pdf_local_path'),
                "extracted_insights": Json(meta) # 存整个原始 JSON
            },
            "vector": {
                "embedding_type": "summary",
                "text_content": text_to_embed,
                "embedding": embedding
            }
        }
        return True, db_payload, None

    except Exception as e:
        return False, None, str(e)

def batch_insert_to_db(batch_data):
    """
    批量写入数据库 (这也是最快的方式)
    """
    if not batch_data:
        return

    conn = get_db_conn()
    cur = conn.cursor()
    
    try:
        # 1. 批量插入 Meta 表
        # 使用 execute_values 提高性能
        meta_tuples = []
        for item in batch_data:
            m = item['meta']
            meta_tuples.append((
                m['arxiv_id'], m['title'], m['authors'], 
                m['published_date'], m['pdf_local_path'], m['extracted_insights']
            ))
            
        insert_meta_query = """
            INSERT INTO papers_meta 
            (arxiv_id, title, authors, published_date, pdf_local_path, extracted_insights)
            VALUES %s
            ON CONFLICT (arxiv_id) DO NOTHING
            RETURNING arxiv_id, id;
        """
        
        # execute_values 只是拼 SQL，不能直接 RETURNING 映射
        # 所以对于复杂关联，我们还是用 executemany 或者逐条 check (为了严谨这里用稍微慢一点但安全的方式)
        # 但为了大量数据的绝对速度，推荐分两步：
        
        # A 方案: 逐条插入 Meta 获取 ID (因为要处理 ON CONFLICT)
        paper_id_map = {} # arxiv_id -> uuid
        
        for m_tpl in meta_tuples:
            cur.execute("""
                INSERT INTO papers_meta 
                (arxiv_id, title, authors, published_date, pdf_local_path, extracted_insights)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (arxiv_id) DO UPDATE SET title = EXCLUDED.title -- 占位更新以触发 RETURNING
                RETURNING arxiv_id, id;
            """, m_tpl)
            res = cur.fetchone()
            if res:
                paper_id_map[res[0]] = res[1]

        # 2. 批量插入 Vector 表
        vector_tuples = []
        for item in batch_data:
            a_id = item['meta']['arxiv_id']
            if a_id in paper_id_map:
                pid = paper_id_map[a_id]
                v = item['vector']
                vector_tuples.append((
                    pid, v['embedding_type'], v['text_content'], v['embedding']
                ))
        
        if vector_tuples:
            extras.execute_values(
                cur,
                """
                INSERT INTO papers_embeddings (paper_id, embedding_type, text_content, embedding)
                VALUES %s
                """,
                vector_tuples
            )

        conn.commit()
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Database Batch Error: {e}")
        print(f"❌ 数据库写入批次失败: {e}")
    finally:
        cur.close()
        release_db_conn(conn)

# --- 主程序流程 ---
def main():
    # 1. 初始化
    check_model_dimension()
    existing_ids = fetch_existing_ids()
    print(f"📂 数据库中已有 {len(existing_ids)} 篇论文，将自动跳过。")

    # 2. 读取文件
    if not os.path.exists(METADATA_FILE):
        print(f"❌ 找不到数据文件: {METADATA_FILE}")
        return

    # 读取待处理的数据
    all_lines = []
    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            # 简单预检：如果 arxiv_id 已经在库里，直接跳过
            try:
                temp = json.loads(line)
                if temp.get('arxiv_id') not in existing_ids:
                    all_lines.append(line)
            except:
                continue
    
    total_tasks = len(all_lines)
    print(f"🚀 待处理任务数: {total_tasks} (已过滤重复)")
    if total_tasks == 0:
        return

    # 3. 并发处理与批量入库
    batch_buffer = []
    
    # 进度条
    pbar = tqdm(total=total_tasks, desc="Processing Papers")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_to_line = {executor.submit(process_single_paper, line): line for line in all_lines}
        
        for future in as_completed(future_to_line):
            success, result, error = future.result()
            
            if success:
                batch_buffer.append(result)
            else:
                logging.error(error)
            
            # 缓冲区满了，写入数据库
            if len(batch_buffer) >= BATCH_SIZE:
                batch_insert_to_db(batch_buffer)
                batch_buffer = [] # 清空
            
            pbar.update(1)
            
    # 4. 处理剩余的数据
    if batch_buffer:
        batch_insert_to_db(batch_buffer)
    
    pbar.close()
    print("\n✅ 所有任务处理完成！请查看 ingest_error.log 检查失败记录。")

if __name__ == "__main__":
    main()