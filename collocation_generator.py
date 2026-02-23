#!/usr/bin/env python3
"""
Anki 搭配卡片生成器 (Oxford Collocation Dictionary)

从牛津英语搭配词典提取动词搭配和介词搭配，
按义项（sense）为单位生成 Anki 卡片

使用前:
1. 启动 mdx-server: python mdx_server.py "牛津搭配词典目录路径"
2. 关闭 Anki (以便读取数据库)
3. 修改下方配置区的路径

使用方式:
  从 Anki 数据库读取: python collocation_generator.py
  从单词列表读取:     python collocation_generator.py -w word1 word2 word3
  从文件读取:         python collocation_generator.py -f words.txt
"""

import sqlite3
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import time
import re
import argparse
import sys
import logging

# ================== 配置区 ==================

ANKI_DB = "./collection.anki2"
MDX_SERVER_URL = "http://localhost:8000"
MDX_DICT_DIR = "../牛津英语搭配词典全索引"
FREQ_DICT_FILE = "eng_dict.txt"
OUTPUT_FILE = "collocation_cards.txt"
SKIPPED_LOG = "skipped_words.log"

# 难词筛选条件（从 Anki 提取时使用）
EASE_THRESHOLD = 2000
LAPSES_THRESHOLD = 2
MAX_WORDS = 100

# 绕过系统代理，直接连接 localhost
NO_PROXY = {"http": None, "https": None}

# 要保留的搭配类别（sl 属性值）
KEEP_SL_TYPES = {
    'verbs',        # VERBS（用于形容词/副词词条）
    'verbandhwd',   # VERB + WORD
    'hwdandverb',   # WORD + VERB
    'prep',         # PREPOSITION
}

# ================== 日志 ==================

logging.basicConfig(
    filename=SKIPPED_LOG,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    encoding='utf-8',
)
logger = logging.getLogger(__name__)

# ================== 词频字典 ==================

def load_freq_dict(dict_file):
    """加载词频字典，返回 {word_form: rank} 映射（所有词形都映射到同一行号）"""
    freq_map = {}
    try:
        with open(dict_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                words = line.strip().split()
                for word in words:
                    word = word.lower()
                    if word not in freq_map:
                        freq_map[word] = line_num
        print(f"✅ 加载词频字典: {len(freq_map)} 个词形, {line_num} 行")
    except FileNotFoundError:
        print(f"⚠️  未找到词频字典文件: {dict_file}")
    return freq_map

# ================== 步骤1: 获取单词列表 ==================

def get_words_from_list(word_list):
    """从单词列表获取单词"""
    results = []
    for word in word_list:
        word = word.strip().lower()
        word = re.sub(r'[^a-zA-Z\s-]', '', word)
        word = re.sub(r'\s+', ' ', word).strip()
        if word and len(word) > 1:
            results.append({'word': word})
    return results


def get_words_from_file(filename):
    """从文件读取单词列表（每行一个单词）"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            words = [line.strip() for line in f if line.strip()]
        return get_words_from_list(words)
    except FileNotFoundError:
        print(f"❌ 文件未找到: {filename}")
        return []
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return []


def get_difficult_words():
    """从 Anki 数据库提取难词"""
    anki_path = Path(ANKI_DB)
    if not anki_path.exists():
        print(f"❌ 找不到 Anki 数据库: {ANKI_DB}")
        return []

    conn = sqlite3.connect(ANKI_DB)
    query = f"""
    SELECT DISTINCT
        substr(n.flds, 1, instr(n.flds || char(31), char(31)) - 1) as word,
        c.factor as ease,
        c.lapses
    FROM cards c
    JOIN notes n ON c.nid = n.id
    WHERE c.factor < {EASE_THRESHOLD}
      AND c.lapses > {LAPSES_THRESHOLD}
      AND c.type = 2
    ORDER BY c.lapses DESC, c.factor ASC
    LIMIT {MAX_WORDS}
    """

    results = []
    for row in conn.execute(query):
        word = row[0].strip() if row[0] else ""
        word = re.sub(r'<[^>]+>', '', word)
        word = re.sub(r'sound[^\s]*', '', word, flags=re.IGNORECASE)
        word = re.sub(r'[^a-zA-Z\s-]', '', word)
        word = re.sub(r'\s+', ' ', word).strip()
        word = word.split()[0] if word.split() else ""
        if word and len(word) > 1 and word.isalpha():
            results.append({'word': word.lower()})

    conn.close()
    return results


def get_all_dictionary_words(mdx_dir=None):
    """从 MDX 词典文件提取所有词头"""
    mdx_dir = Path(mdx_dir or MDX_DICT_DIR)
    if not mdx_dir.exists():
        print(f"❌ 找不到词典目录: {mdx_dir}")
        return []

    mdx_files = list(mdx_dir.glob("*.mdx"))
    if not mdx_files:
        print(f"❌ 在 {mdx_dir} 中未找到 .mdx 文件")
        return []

    mdx_file = mdx_files[0]
    print(f"  📖 读取词典索引: {mdx_file.name}")

    try:
        sys.path.insert(0, str(Path(__file__).parent / "../anki-vocab-builder/mdx-server"))
        from mdict_query import IndexBuilder
        builder = IndexBuilder(str(mdx_file))
        keys = builder.get_mdx_keys()
    except ImportError:
        print("❌ 无法加载 mdict_query 模块")
        print("  请确保 ../anki-vocab-builder/mdx-server/ 目录存在")
        return []
    except Exception as e:
        print(f"❌ 读取 MDX 文件失败: {e}")
        return []

    # 只保留纯英文单词（含连字符），过滤掉短语、反查索引、中文等
    english_words = set()
    for k in keys:
        k = k.strip()
        if k and re.match(r'^[a-zA-Z]+(-[a-zA-Z]+)*$', k):
            english_words.add(k.lower())

    words_sorted = sorted(english_words)
    print(f"  📊 词典共有 {len(words_sorted)} 个英文词头")
    return [{'word': w} for w in words_sorted]

# ================== 步骤2: 查询词典 ==================

# 全局直接查询器（--all 模式复用）
_mdx_builder = None

def _get_mdx_builder(mdx_dir=None):
    """获取或创建 MDX IndexBuilder 实例"""
    global _mdx_builder
    if _mdx_builder is not None:
        return _mdx_builder

    mdx_dir = Path(mdx_dir or MDX_DICT_DIR)
    mdx_files = list(mdx_dir.glob("*.mdx"))
    if not mdx_files:
        return None

    try:
        sys.path.insert(0, str(Path(__file__).parent / "../anki-vocab-builder/mdx-server"))
        from mdict_query import IndexBuilder
        _mdx_builder = IndexBuilder(str(mdx_files[0]))
        return _mdx_builder
    except Exception:
        return None


def query_mdx_direct(word, mdx_dir=None):
    """直接查询 MDX 文件（无需 MDX-Server，速度更快）"""
    builder = _get_mdx_builder(mdx_dir)
    if builder is None:
        return None
    try:
        content = builder.mdx_lookup(word)
        if content:
            return ''.join(content)
    except Exception:
        pass
    return None


def check_mdx_server():
    """检测 MDX-Server 是否运行"""
    try:
        response = requests.get(f"{MDX_SERVER_URL}/test", timeout=15, proxies=NO_PROXY)
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.Timeout:
        print("  ⚠️  服务器响应慢，但可能仍在运行")
        choice = input("  继续? (y/n): ").strip().lower()
        return choice == 'y'
    except Exception:
        return False


def query_mdx_server(word):
    """通过 MDX-Server 查询单词"""
    try:
        url = f"{MDX_SERVER_URL}/{word}"
        response = requests.get(url, timeout=30, proxies=NO_PROXY)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            return response.text
    except requests.exceptions.Timeout:
        print(f"(超时)", end=" ")
    except Exception:
        pass
    return None

# ================== 步骤3: 解析牛津搭配词典 HTML ==================

def parse_collocation_html(html_content, word):
    """
    解析牛津搭配词典 HTML，按义项拆分为多张卡片
    只保留动词搭配和介词搭配

    HTML 结构:
      <entry>
        <h>word</h>
        <head>
          <p-blk><p>noun</p></p-blk>
          <n-num>1</n-num>
          <def>definition <chn>中文</chn></def>
        </head>
        <sl-g-blk sl="verbandhwd|prep|...">
          <sl-g-head>VERB + PITCH</sl-g-head>
          <sl-g>
            <sb-g>
              <cl>collocation word <chn>中文</chn></cl>
              <x-blk><x>example <chn>中文</chn></x></x-blk>
            </sb-g>
          </sl-g>
        </sl-g-blk>
      </entry>
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    entries = soup.find_all('entry')

    if not entries:
        return []

    cards = []

    for entry in entries:
        # 提取词头
        h_elem = entry.find('h')
        headword = h_elem.get_text(strip=True) if h_elem else word

        # 提取词性
        head = entry.find('head')
        pos = ""
        sense_num = ""
        def_en = ""
        def_cn = ""

        if head:
            p_elem = head.find('p')
            pos = p_elem.get_text(strip=True) if p_elem else ""

            n_num_elem = head.find('n-num')
            sense_num = n_num_elem.get_text(strip=True) if n_num_elem else ""

            def_elem = head.find('def')
            if def_elem:
                chn_elem = def_elem.find('chn')
                def_cn = chn_elem.get_text(strip=True) if chn_elem else ""
                # 英文释义：去掉中文部分
                for chn in def_elem.find_all('chn'):
                    chn.decompose()
                for chnsep in def_elem.find_all('chnsep'):
                    chnsep.decompose()
                def_en = def_elem.get_text(strip=True)

        # 提取搭配（只保留动词和介词）
        collocation_groups = []
        sl_g_blks = entry.find_all('sl-g-blk')

        for blk in sl_g_blks:
            sl_type = blk.get('sl', '')
            if sl_type not in KEEP_SL_TYPES:
                continue

            # 类别标题（规范化空格）
            head_elem = blk.find('sl-g-head')
            category_title = head_elem.get_text() if head_elem else sl_type.upper()
            category_title = re.sub(r'\s+', ' ', category_title).strip()

            # 提取搭配词组和例句
            collocation_items = []
            sb_gs = blk.find_all('sb-g')

            for sb_g in sb_gs:
                item = _parse_sb_g(sb_g)
                if item:
                    collocation_items.append(item)

            if collocation_items:
                collocation_groups.append({
                    'category': category_title,
                    'items': collocation_items,
                })

        # 如果没有动词/介词搭配，跳过该义项
        if not collocation_groups:
            continue

        cards.append({
            'word': headword,
            'pos': pos,
            'sense_num': sense_num,
            'def_en': def_en,
            'def_cn': def_cn,
            'collocation_groups': collocation_groups,
        })

    return cards


def _parse_sb_g(sb_g):
    """解析一个 <sb-g> 块，提取搭配词和例句"""
    # 提取搭配词
    collocations = []
    chn_text = ""

    for cl in sb_g.find_all('cl', recursive=False):
        # 复制节点以避免修改原始 soup
        cl_copy = cl.__copy__()
        # 提取中文
        chn = cl.find('chn')
        if chn:
            chn_text = chn.get_text(strip=True)
        # 提取英文搭配词（去掉 chn 和 chnsep）
        for tag in cl.find_all(['chn', 'chnsep']):
            tag.decompose()
        cl_text = cl.get_text(strip=True)
        if cl_text:
            collocations.append(cl_text)

    if not collocations:
        return None

    # 提取例句
    examples = []
    for x_blk in sb_g.find_all('x-blk', recursive=False):
        x_elem = x_blk.find('x')
        if x_elem:
            x_chn = x_elem.find('chn')
            ex_cn = x_chn.get_text(strip=True) if x_chn else ""
            # 去掉中文获取英文例句
            for tag in x_elem.find_all(['chn', 'chnsep', 'fthzmark']):
                tag.decompose()
            ex_en = x_elem.get_text(strip=True)
            if ex_en:
                examples.append({'en': ex_en, 'cn': ex_cn})

    return {
        'words': collocations,
        'chn': chn_text,
        'examples': examples,
    }

# ================== 步骤4: 生成 Anki 卡片字段 ==================

def generate_collocations_html(card):
    """生成搭配内容 HTML（包含中英文，由模板 CSS 控制显隐）"""
    groups_html = ""
    for group in card['collocation_groups']:
        groups_html += f'<div class="colloc-group">'
        groups_html += f'<div class="colloc-category">{group["category"]}</div>'

        for item in group['items']:
            groups_html += '<div class="colloc-item">'
            words_str = ' <span class="sep">|</span> '.join(
                f'<span class="colloc-word">{w}</span>' for w in item['words']
            )
            if item['chn']:
                words_str += f'<span class="colloc-chn">{item["chn"]}</span>'
            groups_html += f'<div class="colloc-words">{words_str}</div>'

            for ex in item['examples']:
                groups_html += '<div class="colloc-example">'
                groups_html += f'<div class="ex-en">✦ {ex["en"]}</div>'
                if ex['cn']:
                    groups_html += f'<div class="ex-cn">{ex["cn"]}</div>'
                groups_html += '</div>'

            groups_html += '</div>'
        groups_html += '</div>'

    return groups_html


def generate_anki_import_file(all_cards):
    """生成 Anki 导入文件 (TSV)
    格式: Word<tab>POS<tab>SenseNum<tab>DefEN<tab>DefCN<tab>Collocations<tab>FreqRank<tab>Tags
    """
    lines = []
    for card in all_cards:
        colloc = generate_collocations_html(card).replace('\n', '').replace('\r', '')
        freq_rank = str(card.get('freq_rank', ''))
        fields = [
            card['word'],
            card['pos'],
            card['sense_num'],
            card['def_en'],
            card['def_cn'],
            colloc,
            freq_rank,
            card['word'],  # tag
        ]
        lines.append('\t'.join(fields))
    return '\n'.join(lines)

# ================== CSS 样式 ==================

CARD_CSS = '''/* Anki 搭配卡片样式 */

.card {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  font-size: 16px;
  text-align: left;
  background: #f5f5f5;
  padding: 20px;
}

.colloc-card {
  max-width: 600px;
  margin: 0 auto;
  background: #fff;
  padding: 28px;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}

/* 单词 */
.word {
  font-size: 36px;
  font-weight: bold;
  color: #2c3e50;
  margin-bottom: 6px;
}

/* 词性 + 义项编号 */
.meta {
  margin-bottom: 12px;
}

.pos {
  color: #9b59b6;
  font-style: italic;
  font-size: 16px;
  font-weight: 600;
  margin-right: 10px;
}

.sense-num {
  display: inline-block;
  background: #e74c3c;
  color: white;
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: bold;
  font-size: 14px;
}

.freq-rank {
  font-size: 14px;
  color: #95a5a6;
  font-weight: normal;
  margin-left: 8px;
}

/* 释义 */
.definition {
  padding: 12px 16px;
  background: #f8f9fa;
  border-radius: 8px;
  border-left: 4px solid #3498db;
  margin-bottom: 8px;
}

.def-en {
  color: #2c3e50;
  font-size: 18px;
  font-weight: 500;
}

.def-cn {
  color: #7f8c8d;
  font-size: 16px;
  margin-left: 8px;
}

/* 分割线 */
.divider {
  margin: 20px 0;
  border: none;
  border-top: 2px solid #ecf0f1;
}

/* 搭配组 */
.colloc-group {
  margin-bottom: 20px;
}

.colloc-category {
  font-size: 13px;
  font-weight: 700;
  color: #e67e22;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 4px 10px;
  background: #fef5e7;
  border-radius: 4px;
  margin-bottom: 10px;
  display: inline-block;
}

/* 搭配条目 */
.colloc-item {
  margin-bottom: 12px;
  padding-left: 8px;
}

.colloc-words {
  margin-bottom: 4px;
  line-height: 1.8;
}

.colloc-word {
  color: #2980b9;
  font-weight: 600;
  font-size: 16px;
}

.sep {
  color: #bdc3c7;
  margin: 0 4px;
}

.colloc-chn {
  color: #7f8c8d;
  font-size: 14px;
  margin-left: 8px;
}

/* 例句 */
.colloc-example {
  padding: 6px 12px;
  margin: 4px 0 4px 12px;
  border-left: 2px solid #e0e0e0;
}

.ex-en {
  color: #555;
  font-style: italic;
  font-size: 15px;
  line-height: 1.6;
}

.ex-cn {
  color: #95a5a6;
  font-size: 14px;
  line-height: 1.5;
  margin-left: 16px;
}

/* 正面隐藏中文 */
.hide-cn .def-cn,
.hide-cn .colloc-chn,
.hide-cn .ex-cn {
  display: none;
}
'''

CARD_TEMPLATE_FRONT = '''<div class="colloc-card hide-cn">
  <div class="word">{{Word}}{{#FreqRank}}<span class="freq-rank">#{{FreqRank}}</span>{{/FreqRank}}</div>
  <div class="meta">
    <span class="pos">{{POS}}</span>
    {{#SenseNum}}<span class="sense-num">#{{SenseNum}}</span>{{/SenseNum}}
  </div>
  {{#DefEN}}
  <div class="definition">
    <span class="def-en">{{DefEN}}</span>
    <span class="def-cn">{{DefCN}}</span>
  </div>
  {{/DefEN}}
  <hr class="divider">
  <div class="colloc-content">{{Collocations}}</div>
</div>'''

CARD_TEMPLATE_BACK = '''<div class="colloc-card">
  <div class="word">{{Word}}{{#FreqRank}}<span class="freq-rank">#{{FreqRank}}</span>{{/FreqRank}}</div>
  <div class="meta">
    <span class="pos">{{POS}}</span>
    {{#SenseNum}}<span class="sense-num">#{{SenseNum}}</span>{{/SenseNum}}
  </div>
  {{#DefEN}}
  <div class="definition">
    <span class="def-en">{{DefEN}}</span>
    <span class="def-cn">{{DefCN}}</span>
  </div>
  {{/DefEN}}
  <hr class="divider">
  <div class="colloc-content">{{Collocations}}</div>
</div>'''

# ================== 主程序 ==================

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Anki 搭配卡片生成器 - 从牛津搭配词典生成搭配卡片',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  处理整个词典:
    python collocation_generator.py --all

  从命令行单词列表:
    python collocation_generator.py -w pitch formidable accord

  从文件读取:
    python collocation_generator.py -f words.txt

  从 Anki 数据库读取:
    python collocation_generator.py -a collection.anki2
        '''
    )
    parser.add_argument('-w', '--words', nargs='+', metavar='WORD',
                        help='单词列表（空格分隔）')
    parser.add_argument('-f', '--file', metavar='FILE',
                        help='包含单词列表的文件（每行一个单词）')
    parser.add_argument('-a', '--anki', metavar='DB',
                        help='从 Anki 数据库提取难词')
    parser.add_argument('--all', action='store_true',
                        help='处理整个词典的所有单词')
    parser.add_argument('--mdx-dir', metavar='DIR',
                        help=f'MDX 词典目录（默认: {MDX_DICT_DIR}）')
    parser.add_argument('--max', type=int, default=0,
                        help='最多处理的单词数（0 = 不限制）')
    parser.add_argument('--freq', metavar='FILE',
                        help=f'词频字典文件（默认: {FREQ_DICT_FILE}）')
    return parser.parse_args()


def main():
    print("=" * 60)
    print("  Anki 搭配卡片生成器 (Oxford Collocation Dictionary)")
    print("=" * 60)
    print()

    args = parse_arguments()

    # 清空日志
    open(SKIPPED_LOG, 'w').close()

    # 检查查询方式
    use_direct = args.all  # --all 模式自动使用直接查询
    mdx_dir = args.mdx_dir

    if use_direct:
        print("🔍 初始化直接词典查询...")
        builder = _get_mdx_builder(mdx_dir)
        if builder is None:
            print("❌ 无法加载 MDX 词典文件")
            return
        print("✅ 词典加载完成\n")
    else:
        print("🔍 检查 MDX-Server 连接...")
        if not check_mdx_server():
            print(f"❌ 无法连接到 MDX-Server: {MDX_SERVER_URL}")
            print()
            print("请先启动 mdx-server:")
            print('  cd ../anki-vocab-builder/mdx-server')
            print('  python mdx_server.py "../../牛津英语搭配词典全索引/"')
            return
        print(f"✅ MDX-Server 运行正常\n")

    # 加载词频字典
    freq_file = args.freq or FREQ_DICT_FILE
    freq_map = load_freq_dict(freq_file)

    # 获取单词列表
    if args.all:
        print("📚 从词典提取所有词头...")
        word_list = get_all_dictionary_words(mdx_dir)
    elif args.words:
        print(f"📚 从命令行参数读取单词 ({len(args.words)} 个)...")
        word_list = get_words_from_list(args.words)
    elif args.file:
        print(f"📚 从文件读取单词: {args.file}...")
        word_list = get_words_from_file(args.file)
    elif args.anki:
        print(f"📚 从 Anki 数据库提取难词: {args.anki}...")
        global ANKI_DB
        ANKI_DB = args.anki
        word_list = get_difficult_words()
    else:
        print("❌ 请指定单词来源: --all, -w, -f, 或 -a")
        print("  用 --help 查看帮助")
        return

    if not word_list:
        print("❌ 未找到单词")
        return

    if args.max > 0 and len(word_list) > args.max:
        print(f"⚠️  单词数量超过限制，将只处理前 {args.max} 个")
        word_list = word_list[:args.max]

    # 去重
    seen = set()
    unique_words = []
    for w in word_list:
        if w['word'] not in seen:
            seen.add(w['word'])
            unique_words.append(w)
    word_list = unique_words

    print(f"✅ 找到 {len(word_list)} 个单词\n")

    # 查询并解析
    print("🔍 查询词典并解析搭配...\n")
    all_cards = []
    failed_words = []
    total = len(word_list)
    success_count = 0
    # 大批量时减少输出
    verbose = total <= 50

    for i, item in enumerate(word_list, 1):
        word = item['word']

        if verbose:
            print(f"[{i}/{total}] {word:20}", end=" ", flush=True)
        elif i % 200 == 0 or i == total:
            print(f"  进度: {i}/{total} ({i*100//total}%)  卡片: {len(all_cards)}  成功: {success_count}", flush=True)

        # 查询
        if use_direct:
            html = query_mdx_direct(word, mdx_dir)
        else:
            html = query_mdx_server(word)

        if html:
            cards = parse_collocation_html(html, word)
            if cards:
                # 附加词频序号
                rank = freq_map.get(word.lower(), '')
                for card in cards:
                    card['freq_rank'] = str(rank)
                all_cards.extend(cards)
                success_count += 1
                if verbose:
                    print(f"→ {len(cards)} 张卡片 ✓")
            else:
                if verbose:
                    print("→ 无动词/介词搭配 ✗")
                logger.info(f"SKIP {word}: 无动词/介词搭配")
                failed_words.append(word)
        else:
            if verbose:
                print("→ 查询失败 ✗")
            logger.info(f"SKIP {word}: 查询失败")
            failed_words.append(word)

    print()

    if not all_cards:
        print("❌ 未生成任何卡片")
        return

    # 生成导入文件
    print("📝 生成 Anki 导入文件...")
    import_content = generate_anki_import_file(all_cards)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(import_content)

    # 保存样式
    css_file = "anki_card_style.css"
    with open(css_file, 'w', encoding='utf-8') as f:
        f.write(CARD_CSS)

    # 保存模板
    template_file = "anki_card_template.txt"
    with open(template_file, 'w', encoding='utf-8') as f:
        f.write("=== 正面模板 ===\n")
        f.write(CARD_TEMPLATE_FRONT)
        f.write("\n\n=== 背面模板 ===\n")
        f.write(CARD_TEMPLATE_BACK)
        f.write("\n\n=== 样式(CSS) ===\n")
        f.write(CARD_CSS)

    # 完成
    print()
    print("=" * 60)
    print("✅ 完成!")
    print(f"  生成卡片: {len(all_cards)} 张")
    print(f"  来自单词: {len(word_list) - len(failed_words)} / {len(word_list)}")
    print(f"  导入文件: {OUTPUT_FILE}")
    print(f"  样式文件: {css_file}")
    print(f"  模板文件: {template_file}")

    if failed_words:
        print(f"\n⚠️  跳过的单词 ({len(failed_words)} 个):")
        print(f"  {', '.join(failed_words[:20])}")
        if len(failed_words) > 20:
            print(f"  ... 还有 {len(failed_words) - 20} 个")
        print(f"  详见日志: {SKIPPED_LOG}")

    print()
    print("📌 导入步骤:")
    print("  1. 在 Anki 中: 工具 → 管理笔记类型 → 添加")
    print("  2. 选择「基础」，命名为「搭配卡片」")
    print("  3. 字段: 添加 Word, POS, SenseNum, DefEN, DefCN, Collocations, FreqRank")
    print("     （删除默认的 Front/Back）")
    print("  4. 点击「卡片」，复制 anki_card_template.txt 中的:")
    print("     - 正面模板 → 粘贴到「正面模板」")
    print("     - 背面模板 → 粘贴到「背面模板」")
    print("     - 样式 → 粘贴到「样式」")
    print(f"  5. 文件 → 导入，选择 {OUTPUT_FILE}")
    print("  6. 类型选择「搭配卡片」，分隔符: Tab，允许HTML")
    print("  7. 字段映射: Word, POS, SenseNum, DefEN, DefCN, Collocations, FreqRank, 标签")


if __name__ == "__main__":
    main()
