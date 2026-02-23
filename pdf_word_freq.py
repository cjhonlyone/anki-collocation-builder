#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF 单词频次统计脚本
支持单个或批量 PDF 文件处理，提取单词并统计频次
"""

import re
import csv
import argparse
from pathlib import Path
from collections import Counter
from typing import Dict, List, Set
import pypdf


class WordFrequencyAnalyzer:
    def __init__(self, dict_file: str = "eng_dict.txt"):
        """
        初始化分析器
        
        Args:
            dict_file: 词形词典文件路径
        """
        self.lemma_dict, self.line_numbers = self._load_lemma_dict(dict_file)
        self.stopwords = self._get_stopwords()
    
    def _load_lemma_dict(self, dict_file: str):
        """
        加载词形还原字典
        每行第一个单词是基础形式，后续是变体
        
        Returns:
            (lemma_dict, line_numbers): 词形映射字典和行号字典
            lemma_dict: {变体: 基础形式}
            line_numbers: {基础形式: 行号}
        """
        lemma_dict = {}
        line_numbers = {}
        try:
            with open(dict_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    words = line.strip().split()
                    if not words:
                        continue
                    
                    base_form = words[0].lower()
                    # 记录基础形式的行号
                    line_numbers[base_form] = line_num
                    
                    # 基础形式映射到自身
                    lemma_dict[base_form] = base_form
                    
                    # 所有变体映射到基础形式
                    for word in words[1:]:
                        word = word.lower()
                        if word not in lemma_dict:  # 优先保留高频词的映射
                            lemma_dict[word] = base_form
            
            print(f"✓ 加载词形字典: {len(lemma_dict)} 个词形")
        except FileNotFoundError:
            print(f"⚠ 未找到词形字典文件 {dict_file}，将不进行词形还原")
        
        return lemma_dict, line_numbers
    
    def _get_stopwords(self) -> Set[str]:
        """
        获取英文停用词列表
        """
        # 常见英文停用词
        stopwords = {
            'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have',
            'i', 'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you',
            'do', 'at', 'this', 'but', 'his', 'by', 'from', 'they',
            'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one',
            'all', 'would', 'there', 'their', 'what', 'so', 'up', 'out',
            'if', 'about', 'who', 'get', 'which', 'go', 'me', 'when',
            'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know',
            'take', 'people', 'into', 'year', 'your', 'good', 'some',
            'could', 'them', 'see', 'other', 'than', 'then', 'now',
            'look', 'only', 'come', 'its', 'over', 'think', 'also',
            'back', 'after', 'use', 'two', 'how', 'our', 'work',
            'first', 'well', 'way', 'even', 'new', 'want', 'because',
            'any', 'these', 'give', 'day', 'most', 'us', 'is', 'was',
            'are', 'been', 'has', 'had', 'were', 'said', 'did', 'am'
        }
        return stopwords
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        从 PDF 文件中提取文本
        
        Args:
            pdf_path: PDF 文件路径
            
        Returns:
            提取的文本内容
        """
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = pypdf.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text()
                
                print(f"  ✓ 提取 {num_pages} 页内容")
        except Exception as e:
            print(f"  ✗ 读取失败: {e}")
        
        return text
    
    def process_text(self, text: str) -> Counter:
        """
        处理文本：分词、过滤、词形还原、统计
        
        Args:
            text: 输入文本
            
        Returns:
            单词频次计数器
        """
        # 转为小写
        text = text.lower()
        
        # 提取单词（包括连字符的单词）
        # 匹配字母和连字符组成的单词
        words = re.findall(r'\b[a-z]+(?:-[a-z]+)*\b', text)
        
        # 过滤和统计
        word_counter = Counter()
        
        for word in words:
            # 跳过单字母单词（除了 'a' 和 'i'，但它们在停用词中）
            if len(word) < 2:
                continue
            
            # 跳过包含数字的词（已在正则中排除）
            
            # 词形还原
            lemma = self.lemma_dict.get(word, word)
            
            # 跳过停用词
            if lemma in self.stopwords:
                continue
            
            word_counter[lemma] += 1
        
        return word_counter
    
    def analyze_pdfs(self, pdf_paths: List[str]) -> Counter:
        """
        分析一个或多个 PDF 文件
        
        Args:
            pdf_paths: PDF 文件路径列表
            
        Returns:
            合并的单词频次计数器
        """
        total_counter = Counter()
        
        for pdf_path in pdf_paths:
            print(f"\n处理: {Path(pdf_path).name}")
            text = self.extract_text_from_pdf(pdf_path)
            word_counter = self.process_text(text)
            total_counter.update(word_counter)
            print(f"  ✓ 提取 {sum(word_counter.values())} 个有效单词")
        
        return total_counter
    
    def save_to_csv(self, word_counter: Counter, output_file: str):
        """
        将统计结果保存到 CSV 文件
        
        Args:
            word_counter: 单词频次计数器
            output_file: 输出文件路径
        """
        try:
            with open(output_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Word', 'Frequency', 'DictLineNumber'])
                
                # 按频次降序排序
                for word, freq in word_counter.most_common():
                    line_num = self.line_numbers.get(word, '')
                    writer.writerow([word, freq, line_num])
            
            print(f"\n✓ 结果已保存到: {output_file}")
            print(f"  - 总计: {len(word_counter)} 个不同单词")
            print(f"  - 总词数: {sum(word_counter.values())} 次")
        except Exception as e:
            print(f"\n✗ 保存失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='PDF 单词频次统计工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  单个文件:
    python pdf_word_freq.py document.pdf
  
  批量文件:
    python pdf_word_freq.py doc1.pdf doc2.pdf doc3.pdf
  
  指定输出文件:
    python pdf_word_freq.py document.pdf -o results.csv
  
  使用自定义词典:
    python pdf_word_freq.py document.pdf -d my_dict.txt
        """
    )
    
    parser.add_argument(
        'pdf_files',
        nargs='+',
        help='一个或多个 PDF 文件路径'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='word_frequency.csv',
        help='输出 CSV 文件名 (默认: word_frequency.csv)'
    )
    
    parser.add_argument(
        '-d', '--dict',
        default='eng_dict.txt',
        help='词形字典文件路径 (默认: eng_dict.txt)'
    )
    
    args = parser.parse_args()
    
    # 验证输入文件
    valid_pdfs = []
    for pdf_path in args.pdf_files:
        if Path(pdf_path).exists():
            valid_pdfs.append(pdf_path)
        else:
            print(f"⚠ 文件不存在: {pdf_path}")
    
    if not valid_pdfs:
        print("\n✗ 没有有效的 PDF 文件")
        return
    
    # 如果只有一个PDF且用户未指定输出文件名，则使用PDF文件名
    output_file = args.output
    if len(valid_pdfs) == 1 and args.output == 'word_frequency.csv':
        pdf_name = Path(valid_pdfs[0]).stem  # 获取不带扩展名的文件名
        output_file = f"{pdf_name}_word_frequency.csv"
    
    print(f"\n{'='*60}")
    print(f"PDF 单词频次统计")
    print(f"{'='*60}")
    print(f"待处理文件: {len(valid_pdfs)} 个")
    
    # 分析
    analyzer = WordFrequencyAnalyzer(args.dict)
    word_counter = analyzer.analyze_pdfs(valid_pdfs)
    
    # 保存结果
    analyzer.save_to_csv(word_counter, output_file)
    
    # 显示前 10 个高频词
    print(f"\n{'='*60}")
    print("Top 10 高频词:")
    print(f"{'='*60}")
    for word, freq in word_counter.most_common(10):
        print(f"  {word:20s} {freq:6d}")


if __name__ == "__main__":
    main()
