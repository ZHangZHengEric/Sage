from typing import Dict, Any
from .tool_base import ToolBase
from sagents.utils.logger import logger
import math

class Calculator(ToolBase):
    """A collection of mathematical calculation tools"""
    
    def __init__(self):
        logger.debug("Initializing Calculator tool")
        super().__init__()
        
    @ToolBase.tool()
    def calculate(self,expression: str) -> Dict[str, Any]:
        """Evaluate a mathematical expression.
        
        Args:
            expression (str): The mathematical expression to evaluate (e.g. "2+3*5")
                Supports basic operations and math module functions.
                
        Returns:
            Dict[str, Any]: Dictionary containing result/error information
            
        Examples:
            >>> calc = Calculator()
            >>> calc.calculate("2+3*5")
            {'result': 17, 'error': None, 'expression': '2+3*5', 'status': 'success'}
        """
        logger.info(f"Calculating expression: {expression}")
        try:
            result = eval(expression, {"__builtins__": None}, {
                "math": math,
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "pi": math.pi,
                "e": math.e
            })
            logger.debug(f"Calculation result for '{expression}': {result}")
            return {
                "result": result,
                "expression": expression,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error calculating '{expression}': {str(e)}")
            return {
                "error": str(e),
                "expression": expression,
                "status": "error"
            }

    @ToolBase.tool()
    def factorial(self,n: int) -> Dict[str, Any]:
        """Calculate the factorial of a number.
        
        Args:
            n (int): The number to calculate factorial for (must be positive integer)
                Maximum supported value depends on system memory.
                
        Returns:
            Dict[str, Any]: Dictionary containing:
                - result: The factorial result if successful
                - error: Error message if failed
                - input: The original input number
                - status: "success" or "error"
        """
        logger.info(f"Calculating factorial for: {n}")
        try:
            if n < 0:
                logger.warning(f"Invalid factorial input (negative): {n}")
                raise ValueError("Factorial is only defined for non-negative integers")
            result = math.factorial(n)
            logger.debug(f"Factorial result for {n}: {result}")
            return {
                "result": result,
                "input": n,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error calculating factorial for {n}: {str(e)}")
            return {
                "error": str(e),
                "input": n,
                "status": "error"
            }