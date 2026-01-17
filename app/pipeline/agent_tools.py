# app/pipeline/agent_tools.py

def tool_sum(a: float, b: float) -> float:
    """
    Returns the sum of two numbers.
    """
    return a + b

def tool_subtract(a: float, b: float) -> float:
    """
    Returns the difference of two numbers.
    """
    return a - b

def tool_multiply(a: float, b: float) -> float:
    """
    Returns the product of two numbers.
    """
    return a * b

def tool_divide(a: float, b: float) -> float:
    """
    Returns the division result of two numbers.
    Raises ZeroDivisionError if b is 0.
    """
    if b == 0:
        raise ValueError("Division by zero is not allowed.")
    return a / b

# app/pipeline/agent_tools.py

TOOL_REGISTRY = {
    "sum": tool_sum,
    "subtract": tool_subtract,
    "multiply": tool_multiply,
    "divide": tool_divide,
}
