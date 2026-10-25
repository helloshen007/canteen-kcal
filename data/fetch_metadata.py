"""兼容旧命令：下载固定版本元数据并校验 SHA，不生成真值。"""
from data.prepare import main

if __name__ == '__main__':
    main(['--metadata-only'])
