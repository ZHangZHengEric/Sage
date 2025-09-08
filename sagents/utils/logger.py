import os
import logging
import inspect
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

class Logger:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, log_dir='logs'):
        if Logger._initialized:
            return
            
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Create logger
        self.logger = logging.getLogger('sage')
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        
        # Clear existing handlers to avoid duplicate logs
        if self.logger.handlers:
            self.logger.handlers.clear()
            
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
        console_handler.setFormatter(console_format)
        
        # File handler (rotating)
        log_file = os.path.join(log_dir, f'sage_{datetime.now().strftime("%Y%m%d")}.log')
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
        file_handler.setFormatter(file_format)
        
        # Add handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        
        Logger._initialized = True
    
    def _log(self, level, message):
        # Get caller frame info to include filename and line number
        # 使用inspect.stack获取调用栈，跳过前两层（_log方法和debug/info等方法）
        stack = inspect.stack()
        if len(stack) >= 3:
            caller_frame = stack[2][0]
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
        else:
            filename = 'unknown.py'
            lineno = 0
        
        # Get the level method and call it with the message
        log_method = getattr(self.logger, level)
        log_method(f"{message}", extra={'caller_filename': filename, 'caller_lineno': lineno})
    
    def debug(self, message):
        self._log('debug', message)
    
    def info(self, message):
        self._log('info', message)
    
    def warning(self, message):
        self._log('warning', message)
    
    def error(self, message):
        self._log('error', message)
    
    def critical(self, message):
        self._log('critical', message)

# Create a global logger instance for easy import
logger = Logger()