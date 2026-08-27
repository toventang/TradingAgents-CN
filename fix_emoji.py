#!/usr/bin/env python3
"""
Script to fix emoji and Chinese character encoding issues in Python files
"""
import os
import re
from pathlib import Path

def fix_emoji_in_file(filepath):
    """Fix emoji and Chinese character issues in a single file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Remove emoji and Chinese characters from logger messages
        content = re.sub(r'🔍', '[SEARCH]', content)
        content = re.sub(r'🔧', '[FIX]', content)
        content = re.sub(r'❌', '[ERROR]', content)
        content = re.sub(r'⚠️', '[WARN]', content)
        content = re.sub(r'📚', '[DB]', content)
        content = re.sub(r'💡', '[IDEA]', content)
        content = re.sub(r'✓', '[OK]', content)
        content = re.sub(r'⚡', '[FAST]', content)
        content = re.sub(r'🎯', '[TARGET]', content)
        content = re.sub(r'🚀', '[LAUNCH]', content)
        
        # Replace common Chinese phrases in logger messages
        replacements = {
            r'加载\s*\.env\s*文件': 'Loading .env file',
            r'加载前\s': 'Before loading ',
            r'加载后\s': 'After loading ',
            r'有值': 'set',
            r'空': 'empty',
            r'初始化失败': 'Initialization failed',
            r'使用备用配置': 'Using fallback configuration',
            r'使用最简配置': 'Using minimal configuration',
            r'线程安全地获取或创建集合': 'Get or create collection in thread-safe manner',
            r'尝试获取现有集合': 'Try to get existing collection',
            r'创建新集合': 'Create new collection',
            r'可能是并发创建': 'Might be concurrent creation',
            r'集合操作失败': 'Collection operation failed',
            r'缓存集合': 'Cache collection',
            r'禁用遥测': 'disable telemetry',
            r'关键': 'Key',
        }
        
        for pattern, replacement in replacements.items():
            content = re.sub(pattern, replacement, content)
        
        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Fixed: {filepath}")
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    """Main function to fix all Python files"""
    project_root = Path('z:\\Documents\\opensource\\AI\\TradingAgents-CN')
    
    # Find all Python files in tradingagents directory
    python_files = list(project_root.glob('**/*.py'))
    
    fixed_count = 0
    for filepath in python_files:
        if fix_emoji_in_file(filepath):
            fixed_count += 1
    
    print(f"\nTotal files fixed: {fixed_count}")

if __name__ == '__main__':
    main()
