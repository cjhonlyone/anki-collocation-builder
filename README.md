# Anki Collocation Builder

从**牛津英语搭配词典**（Oxford Collocation Dictionary）提取动词搭配和介词搭配，按义项生成精美 Anki 卡片。

## 功能特点

- 📖 一个义项一张卡片，自动拆分多义词
- 🎯 只保留**动词搭配**和**介词搭配**（过滤形容词、副词等）
- 📝 保留所有例句（中英双语）
- 🎨 精美卡片样式：圆角、阴影、彩色分类标签
- 📥 输出 TSV 文件，直接导入 Anki

## 前置要求

- Python 3
- MDX-Server（位于 `../anki-vocab-builder/mdx-server/`）
- 牛津英语搭配词典 MDX 文件

```bash
pip install requests beautifulsoup4
```

## 使用方法

### 1. 启动 MDX-Server（仅 `-w`/`-f`/`-a` 模式需要）

```bash
cd ../anki-vocab-builder/mdx-server
python mdx_server.py "../../牛津英语搭配词典全索引/"
```

> `--all` 模式直接读取 MDX 文件，无需启动 MDX-Server。

### 2. 生成卡片

**处理整个词典：**
```bash
python collocation_generator.py --all
```
8399 个词头 → 10602 张卡片，约 30 秒完成（直接读取 MDX，无需 MDX-Server）。

**命令行指定单词：**
```bash
python collocation_generator.py -w pitch formidable accord
```

**从文件读取：**
```bash
python collocation_generator.py -f words.txt
```

**从 Anki 数据库提取难词：**
```bash
python collocation_generator.py -a ~/path/to/collection.anki2
```
筛选条件：ease factor < 200% 且 lapses > 2。

**限制数量：**
```bash
python collocation_generator.py --all --max 500
```

### 3. 导入 Anki

1. Anki → 工具 → 管理笔记类型 → 添加 → 基础 → 命名为「搭配卡片」
2. 添加「正面」「背面」两个字段，删除默认的 Front/Back
3. 点击「卡片」，复制 `anki_card_template.txt` 中的正面模板、背面模板和样式
4. 文件 → 导入 → 选择 `collocation_cards.txt`
5. 类型选择「搭配卡片」，分隔符: Tab，允许 HTML
6. 字段映射: 字段1→正面, 字段2→背面, 字段3→标签

## 输出文件

| 文件 | 说明 |
|------|------|
| `collocation_cards.txt` | TSV 卡片数据（正面、背面、标签） |
| `anki_card_style.css` | 卡片 CSS 样式 |
| `anki_card_template.txt` | 正面/背面模板 + 样式 |
| `skipped_words.log` | 跳过的单词记录 |

## 卡片示例

**正面**（提示面）：
> **pitch**
> *noun* `#1`
> sports field 运动场

**背面**（答案面）：
> **pitch** *noun* `#1` sports field 运动场
>
> `VERB + PITCH`
> **invade** | **run onto** 涌入／跑到球场
> ✦ *The pitch was invaded by angry fans.* 愤怒的球迷涌入球场。
>
> `PREPOSITION`
> **off the pitch** 离开球场
> ✦ *The players have just come off the pitch.* 选手们刚从球场下来。

## 搭配筛选规则

| 保留 | 丢弃 |
|------|------|
| VERBS | ADJECTIVE |
| VERB + WORD | ADVERB |
| WORD + VERB | WORD + NOUN |
| PREPOSITION | PHRASES |

如果某义项没有任何动词或介词搭配，则跳过该义项不生成卡片。
