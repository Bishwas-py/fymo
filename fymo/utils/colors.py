"""Terminal color utilities"""


class Color:
    """ANSI color codes for terminal output"""
    
    # Regular colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Styles
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    
    # Aliases
    OK = GREEN
    SUCCESS = GREEN
    WARNING = YELLOW
    FAIL = RED
    ERROR = RED
    INFO = CYAN
    
    # Reset
    ENDC = '\033[0m'
    RESET = '\033[0m'
    
    @classmethod
    def print_success(cls, message: str):
        """Print a success message"""
        print(f"{cls.SUCCESS}✓ {message}{cls.ENDC}")
    
    @classmethod
    def print_error(cls, message: str):
        """Print an error message"""
        print(f"{cls.ERROR}✗ {message}{cls.ENDC}")
    
    @classmethod
    def print_warning(cls, message: str):
        """Print a warning message"""
        print(f"{cls.WARNING}⚠ {message}{cls.ENDC}")
    
    @classmethod
    def print_info(cls, message: str):
        """Print an info message"""
        print(f"{cls.INFO}ℹ {message}{cls.ENDC}")
