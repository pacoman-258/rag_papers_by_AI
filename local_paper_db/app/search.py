import psycopg2
import requests
import json
import time
from typing import List, Dict, Tuple
from FlagEmbedding import FlagReranker

# ================= 配置区域 =================
# 1. 数据库配置
DB_CONFIG = {
    "dbname": "paper_db",
    "user": "postgres",
    "password": "yourpassword",
    "host": "localhost",
    "port": "5432"
}

# 2. Ollama 配置 (用于 Embedding 和 生成)
OLLAMA_API_URL = "http://localhost:11434/api"
EMBED_MODEL = "qwen3-embedding"  # 你的 Embedding 模型
CHAT_MODEL = "qwen3:0.6b"        # 你的聊天/推理模型 (生成答案用)

# 3. 检索参数
TOP_K_RETRIEVAL = 50  # 粗排召回数量
TOP_N_RERANK = 5      # 精排保留数量 (最终喂给 LLM 的篇数)

# ================= 初始化模型 =================

print("⏳ 正在加载重排序模型 (BAAI/bge-reranker-v2-m3)...")
# use_fp16=True 可以在 GPU 上加速并节省显存；如果没有 GPU，会自动跑在 CPU 上
reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)
print("✅ 重排序模型加载完成！")

# ================= 核心函数 =================

def get_ollama_embedding(text: str) -> List[float]:
    """调用 Ollama 获取向量"""
    try:
        url = f"{OLLAMA_API_URL}/embeddings"
        payload = {"model": EMBED_MODEL, "prompt": text.replace("\n", " ")}
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        print(f"❌ Embedding 获取失败: {e}")
        return []

def db_vector_search(query_vec: List[float], limit: int = 50) -> List[Dict]:
    """第一步：数据库粗排 (Vector Search)"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # 获取标题、摘要、方法论、以及向量距离
    sql = """
        SELECT 
            m.id,
            m.title,
            m.extracted_insights->>'summary_for_embedding' as summary,
            m.extracted_insights->>'methodology' as method,
            1 - (e.embedding <=> %s::vector) as similarity
        FROM papers_embeddings e
        JOIN papers_meta m ON e.paper_id = m.id
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """
    
    cur.execute(sql, (query_vec, query_vec, limit))
    rows = cur.fetchall()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "title": row[1],
            "text": row[2] if row[2] else "无摘要内容", # 用于重排序的文本
            "method": row[3],
            "initial_score": row[4]
        })
    
    cur.close()
    conn.close()
    return results

def rerank_documents(query: str, docs: List[Dict], top_n: int = 5) -> List[Dict]:
    """第二步：模型精排 (Cross-Encoder Reranking)"""
    if not docs:
        return []
    
    # 构造 Pair 数据: [[query, doc_text_1], [query, doc_text_2], ...]
    pairs = [[query, doc['text']] for doc in docs]
    
    # 计算相关性分数
    scores = reranker.compute_score(pairs)
    
    # 如果只有一个文档，compute_score 返回的是 float，不是 list
    if isinstance(scores, float):
        scores = [scores]
        
    # 将分数写入文档对象
    for doc, score in zip(docs, scores):
        doc['rerank_score'] = score
        
    # 按分数降序排列
    ranked_docs = sorted(docs, key=lambda x: x['rerank_score'], reverse=True)
    
    return ranked_docs[:top_n]

def generate_answer(query: str, context_docs: List[Dict]):
    """第三步：LLM 生成回答"""
    
    # 1. 构建上下文 Prompt
    context_str = ""
    print(f"\n📚 最终引用的 {len(context_docs)} 篇论文:")
    
    for i, doc in enumerate(context_docs):
        print(f"   {i+1}. [{doc['rerank_score']:.2f}] {doc['title']}")
        context_str += f"""
        --- 论文 {i+1} ---
        标题: {doc['title']}
        核心内容: {doc['text']}
        方法论: {doc['method']}
        ------------------
        """
    
    prompt = f"""你是一个专业的学术研究助理。请根据以下参考论文的内容回答用户的问题。
    如果参考论文中没有相关信息，请直接说明“资料不足”。
    请引用论文编号（如 [1]）来支持你的回答。

    参考论文：
    {context_str}

    用户问题：{query}

    你的回答：
    """

    # 2. 调用 Ollama Chat 接口 (流式输出体验更好)
    url = f"{OLLAMA_API_URL}/chat"
    payload = {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True # 开启流式输出
    }
    
    print("\n🤖 AI 回答中:\n" + "="*50)
    
    with requests.post(url, json=payload, stream=True) as resp:
        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    print(content, end="", flush=True)
                except:
                    pass
    print("\n" + "="*50 + "\n")

# ================= 主程序入口 =================

def main():
    while True:
        query = input("\n🔍 请输入你的问题 (输入 q 退出): ").strip()
        if query.lower() == 'q':
            break
        if not query:
            continue
            
        start_time = time.time()
        
        # 1. Embedding + 向量检索 (粗排)
        print("   ↳ 正在检索数据库 (Top 50)...")
        query_vec = get_ollama_embedding(query)
        coarse_results = db_vector_search(query_vec, limit=TOP_K_RETRIEVAL)
        
        if not coarse_results:
            print("⚠️ 未找到相关论文。")
            continue
            
        # 2. Reranking (精排)
        print(f"   ↳ 正在进行语义重排序 (从 {len(coarse_results)} 篇中选 {TOP_N_RERANK} 篇)...")
        final_results = rerank_documents(query, coarse_results, top_n=TOP_N_RERANK)
        
        # 3. LLM 生成
        generate_answer(query, final_results)
        
        end_time = time.time()
        print(f"⚡ 总耗时: {end_time - start_time:.2f}秒")

if __name__ == "__main__":
    main()